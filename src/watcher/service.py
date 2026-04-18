import asyncio
import logging
import os
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ..core.manager import HybridManager
from ..core.ignore_list import is_ignored
from ..core.models import FileStatus

logger = logging.getLogger(__name__)

class SyncEventHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, watch_path: str, manager: HybridManager):
        self.queue = queue
        self.loop = loop
        self.watch_path = os.path.abspath(watch_path)
        self.manager = manager

    def _is_inside_sync_root(self, path: str) -> bool:
        try:
            common = os.path.commonpath([self.watch_path, os.path.abspath(path)])
        except ValueError:
            return False
        return common == self.watch_path

    def _remote_path_for_local(self, local_path: str) -> str:
        relative_path = os.path.relpath(local_path, self.watch_path)
        remote_path = os.path.join(self.manager.remote_root, relative_path).replace(os.sep, '/')
        if remote_path.startswith("//"):
            remote_path = remote_path[1:]
        return remote_path

    async def _is_stub(self, local_path: str) -> bool:
        """Determines if a local modification should be ignored because it's a stub."""
        try:
            if not os.path.exists(local_path) or os.path.getsize(local_path) != 0:
                return False
        except OSError:
            return False
        
        remote_path = self._remote_path_for_local(local_path)
        item = await self.manager.db.get_item(remote_path)
        return item is not None and item['status'] == FileStatus.OFFLINE.value

    def _should_ignore(self, path: str) -> bool:
        path_obj = Path(path)
        if any(part.startswith('.') for part in path_obj.parts):
            return True
        ignored_parts = {
            "__pycache__",
            "Cache",
            "cache",
            "Code Cache",
            "GPUCache",
            "storage",
            "Trash",
            "Trash-1000",
        }
        return any(part in ignored_parts for part in path_obj.parts)

    def on_modified(self, event):
        if (
            not event.is_directory
            and self._is_inside_sync_root(event.src_path)
            and not self._should_ignore(event.src_path)
        ):
            # We can't await in the event handler, so we put the task
            # and let the consumer check if it's a stub
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("upload", event.src_path))

    def on_created(self, event):
        if event.is_directory or self._should_ignore(event.src_path):
            return
        if self._is_inside_sync_root(event.src_path):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("upload", event.src_path))
        else:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("external_created", event.src_path, 0))

    def on_deleted(self, event):
        if (
            not event.is_directory
            and self._is_inside_sync_root(event.src_path)
            and not self._should_ignore(event.src_path)
        ):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("delete_or_export", event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        if self._should_ignore(event.src_path) or self._should_ignore(event.dest_path):
            return

        src_inside = self._is_inside_sync_root(event.src_path)
        dest_inside = self._is_inside_sync_root(event.dest_path)

        if src_inside and dest_inside:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("move", event.src_path, event.dest_path))
        elif src_inside and not dest_inside:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("export_move", event.src_path, event.dest_path))
        elif not src_inside and dest_inside:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("upload", event.dest_path))

class AsyncWatcher:
    def __init__(self, manager: HybridManager, watch_path: str):
        self.manager = manager
        self.watch_path = os.path.abspath(watch_path)
        self.queue = asyncio.Queue()
        self.outbound_move_window = float(os.getenv("CLOUDBRIDGE_OUTBOUND_MOVE_WINDOW", "10"))
        self.pending_outbound_moves: dict[str, list[dict]] = {}
        self.pending_external_stubs: dict[str, list[dict]] = {}
        
        if not os.path.exists(self.watch_path):
            os.makedirs(self.watch_path)

    def _default_extra_watch_paths(self) -> list[str]:
        configured = os.getenv("CLOUDBRIDGE_OUTBOUND_WATCHES")
        if configured:
            candidates = [p.strip() for p in configured.split(os.pathsep) if p.strip()]
        else:
            home = Path.home()
            candidates = [
                str(home),
            ]

        paths = []
        for candidate in candidates:
            path = os.path.abspath(os.path.expanduser(candidate))
            if path != self.watch_path and os.path.isdir(path):
                paths.append(path)
        return paths

    def _watch_roots(self) -> list[str]:
        roots = [self.watch_path, *self._default_extra_watch_paths()]
        unique_roots = []
        for root in sorted(set(roots), key=len):
            if any(os.path.commonpath([existing, root]) == existing for existing in unique_roots):
                continue
            unique_roots.append(root)
        return unique_roots

    def _remember_outbound_move(self, basename: str, pending: dict):
        self.pending_outbound_moves.setdefault(basename, []).append(pending)

    def _pop_outbound_move(self, basename: str):
        pending_items = self.pending_outbound_moves.get(basename)
        if not pending_items:
            return None
        pending = pending_items.pop()
        if not pending_items:
            self.pending_outbound_moves.pop(basename, None)
        return pending

    def _remove_outbound_move(self, basename: str, remote_path: str) -> bool:
        pending_items = self.pending_outbound_moves.get(basename)
        if not pending_items:
            return False
        kept = [item for item in pending_items if item["remote_path"] != remote_path]
        removed = len(kept) != len(pending_items)
        if kept:
            self.pending_outbound_moves[basename] = kept
        else:
            self.pending_outbound_moves.pop(basename, None)
        return removed

    def _remember_external_stub(self, basename: str, pending: dict):
        self.pending_external_stubs.setdefault(basename, []).append(pending)

    def _pop_external_stub(self, basename: str):
        pending_items = self.pending_external_stubs.get(basename)
        if not pending_items:
            return None
        pending = pending_items.pop()
        if not pending_items:
            self.pending_external_stubs.pop(basename, None)
        return pending

    def _remove_external_stub(self, basename: str, dest_path: str) -> bool:
        pending_items = self.pending_external_stubs.get(basename)
        if not pending_items:
            return False
        kept = [item for item in pending_items if item["dest_path"] != dest_path]
        removed = len(kept) != len(pending_items)
        if kept:
            self.pending_external_stubs[basename] = kept
        else:
            self.pending_external_stubs.pop(basename, None)
        return removed

    async def _hydrate_outbound_move(self, remote_path: str, dest_path: str):
        if not os.path.exists(dest_path):
            logger.info("Outbound move destination disappeared before hydration: %s", dest_path)
            return
        if os.path.getsize(dest_path) != 0:
            logger.info("Outbound move destination already contains real data, leaving as-is: %s", dest_path)
            return

        logger.info("Hydrating outbound move destination %s from %s", dest_path, remote_path)
        await self.manager.download_file_to_path(remote_path, dest_path)
        await self.manager.delete_remote_file(remote_path)

    async def start(self):
        """Starts the watcher and processing loop."""
        loop = asyncio.get_running_loop()
        handler = SyncEventHandler(self.queue, loop, self.watch_path, self.manager)
        observer = Observer()
        watch_roots = self._watch_roots()
        for root in watch_roots:
            observer.schedule(handler, root, recursive=True)
        observer.start()
        
        logger.info("Watcher started on %s", ", ".join(watch_roots))
        
        try:
            while True:
                # Get the next task
                task = await self.queue.get()
                try:
                    action = task[0]
                    local_path = task[1]

                    if action == "upload":
                        remote_path = handler._remote_path_for_local(local_path)
                        if is_ignored(remote_path):
                            logger.info("Ignoring local-only path %s (%s)", remote_path, action)
                            continue
                        if os.path.exists(local_path):
                            # BREAK LOOP: Don't upload if it's already a stub
                            is_stub = await handler._is_stub(local_path)
                            if is_stub:
                                logger.debug("Ignoring stub modification for %s", local_path)
                            else:
                                await self.manager.upload_file(local_path, remote_path)
                    elif action == "delete_or_export":
                        remote_path = handler._remote_path_for_local(local_path)
                        if is_ignored(remote_path):
                            logger.info("Ignoring local-only path %s (%s)", remote_path, action)
                            continue
                        item = await self.manager.db.get_item(remote_path)
                        if item and item["status"] == FileStatus.OFFLINE.value:
                            basename = os.path.basename(local_path)
                            logger.info("Possible outbound move detected for offline stub: %s", remote_path)
                            external_stub = self._pop_external_stub(basename)
                            if external_stub:
                                await self._hydrate_outbound_move(remote_path, external_stub["dest_path"])
                                continue

                            self._remember_outbound_move(
                                basename,
                                {
                                    "remote_path": remote_path,
                                    "deleted_path": local_path,
                                },
                            )
                            loop.call_later(
                                self.outbound_move_window,
                                self.queue.put_nowait,
                                ("expire_outbound_move", basename, remote_path),
                            )
                        else:
                            await self.manager.delete_remote_file(remote_path)
                    elif action == "move":
                        remote_path = handler._remote_path_for_local(local_path)
                        if is_ignored(remote_path):
                            logger.info("Ignoring local-only path %s (%s)", remote_path, action)
                            continue
                        dest_path = task[2]
                        rel_dest = os.path.relpath(dest_path, self.watch_path)
                        remote_dest = os.path.join(self.manager.remote_root, rel_dest).replace(os.sep, '/')
                        await self.manager.move_remote_file(remote_path, remote_dest)
                    elif action == "export_move":
                        remote_path = handler._remote_path_for_local(local_path)
                        if is_ignored(remote_path):
                            logger.info("Ignoring local-only path %s (%s)", remote_path, action)
                            continue
                        dest_path = task[2]
                        item = await self.manager.db.get_item(remote_path)
                        if not item or item["status"] != FileStatus.OFFLINE.value:
                            logger.info("Outbound move ignored because source is not an offline stub: %s", remote_path)
                            continue
                        logger.info("Outbound move detected, hydrating %s into %s", remote_path, dest_path)
                        await self._hydrate_outbound_move(remote_path, dest_path)
                    elif action == "external_created":
                        dest_path = local_path
                        attempt = task[2]
                        if not os.path.exists(dest_path):
                            continue
                        if os.path.getsize(dest_path) != 0:
                            logger.debug("External create is not a stub, leaving as-is: %s", dest_path)
                            continue

                        basename = os.path.basename(dest_path)
                        pending = self._pop_outbound_move(basename)
                        if pending:
                            await self._hydrate_outbound_move(pending["remote_path"], dest_path)
                            continue

                        logger.debug("External 0-byte file is waiting for matching outbound move: %s", dest_path)
                        self._remember_external_stub(basename, {"dest_path": dest_path})
                        loop.call_later(
                            self.outbound_move_window,
                            self.queue.put_nowait,
                            ("expire_external_stub", basename, dest_path),
                        )
                    elif action == "expire_outbound_move":
                        basename = task[1]
                        remote_path = task[2]
                        if self._remove_outbound_move(basename, remote_path):
                            logger.info("Outbound move window expired; syncing deletion to cloud: %s", remote_path)
                            await self.manager.delete_remote_file(remote_path)
                    elif action == "expire_external_stub":
                        basename = task[1]
                        dest_path = task[2]
                        if self._remove_external_stub(basename, dest_path):
                            logger.debug("External 0-byte file did not match an outbound move: %s", dest_path)
                except Exception as e:
                    logger.exception("Error processing watcher task %s: %s", task, e)
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            observer.stop()
            observer.join()
            logger.info("Watcher stopped")

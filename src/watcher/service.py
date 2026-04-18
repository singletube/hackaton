import asyncio
import logging
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ..core.manager import HybridManager
from ..core.ignore_list import is_ignored

logger = logging.getLogger(__name__)

class SyncEventHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, watch_path: str, manager: HybridManager):
        self.queue = queue
        self.loop = loop
        self.watch_path = watch_path
        self.manager = manager

    async def _is_stub(self, local_path: str) -> bool:
        """Determines if a local modification should be ignored because it's a stub."""
        try:
            if not os.path.exists(local_path) or os.path.getsize(local_path) != 0:
                return False
        except OSError:
            return False
        
        # Determine remote path
        relative_path = os.path.relpath(local_path, self.watch_path)
        remote_path = os.path.join(self.manager.remote_root, relative_path).replace(os.sep, '/')
        if remote_path.startswith("//"):
            remote_path = remote_path[1:]

        from ..core.models import FileStatus
        item = await self.manager.db.get_item(remote_path)
        return item is not None and item['status'] == FileStatus.OFFLINE.value

    def _should_ignore(self, path: str) -> bool:
        return os.path.basename(path).startswith('.')

    def on_modified(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            # We can't await in the event handler, so we put the task
            # and let the consumer check if it's a stub
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("upload", event.src_path))

    def on_created(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("upload", event.src_path))

    def on_deleted(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("delete", event.src_path))

    def on_moved(self, event):
        if not event.is_directory and not self._should_ignore(event.dest_path):
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ("move", event.src_path, event.dest_path))

class AsyncWatcher:
    def __init__(self, manager: HybridManager, watch_path: str):
        self.manager = manager
        self.watch_path = os.path.abspath(watch_path)
        self.queue = asyncio.Queue()
        
        if not os.path.exists(self.watch_path):
            os.makedirs(self.watch_path)

    async def start(self):
        """Starts the watcher and processing loop."""
        loop = asyncio.get_running_loop()
        handler = SyncEventHandler(self.queue, loop, self.watch_path, self.manager)
        observer = Observer()
        observer.schedule(handler, self.watch_path, recursive=True)
        observer.start()
        
        logger.info("Watcher started on %s", self.watch_path)
        
        try:
            while True:
                # Get the next task
                task = await self.queue.get()
                try:
                    action = task[0]
                    local_path = task[1]
                    
                    # Determine remote path
                    relative_path = os.path.relpath(local_path, self.watch_path)
                    remote_path = os.path.join(self.manager.remote_root, relative_path).replace(os.sep, '/')
                    if remote_path.startswith("//"):
                        remote_path = remote_path[1:]

                    if is_ignored(remote_path):
                        logger.info("Ignoring local-only path %s (%s)", remote_path, action)
                        continue
                    
                    if action == "upload":
                        if os.path.exists(local_path):
                            # BREAK LOOP: Don't upload if it's already a stub
                            is_stub = await handler._is_stub(local_path)
                            if is_stub:
                                logger.debug("Ignoring stub modification for %s", local_path)
                            else:
                                await self.manager.upload_file(local_path, remote_path)
                    elif action == "delete":
                        await self.manager.delete_remote_file(remote_path)
                    elif action == "move":
                        dest_path = task[2]
                        rel_dest = os.path.relpath(dest_path, self.watch_path)
                        remote_dest = os.path.join(self.manager.remote_root, rel_dest).replace(os.sep, '/')
                        await self.manager.move_remote_file(remote_path, remote_dest)
                except Exception as e:
                    logger.exception("Error processing watcher task %s: %s", task, e)
                finally:
                    self.queue.task_done()
        except asyncio.CancelledError:
            observer.stop()
            observer.join()
            logger.info("Watcher stopped")

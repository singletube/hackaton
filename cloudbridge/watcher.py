from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


@dataclass(slots=True)
class WatchEvent:
    src_path: str
    event_type: str
    is_directory: bool


class _AsyncWatchHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue[WatchEvent], loop: asyncio.AbstractEventLoop):
        self._queue = queue
        self._loop = loop

    def on_any_event(self, event: FileSystemEvent) -> None:
        payload = WatchEvent(
            src_path=event.src_path,
            event_type=event.event_type,
            is_directory=event.is_directory,
        )
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)


class LocalWatcher:
    def __init__(self, root: Path, *, recursive: bool = True) -> None:
        self._root = root.resolve()
        self._recursive = recursive
        self._observer = Observer()
        self._queue: asyncio.Queue[WatchEvent] = asyncio.Queue()
        self._handler: _AsyncWatchHandler | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._handler is not None:
            return
        self._handler = _AsyncWatchHandler(self._queue, loop)
        self._observer.schedule(self._handler, str(self._root), recursive=self._recursive)
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)
        self._handler = None

    async def next_event(self) -> WatchEvent:
        return await self._queue.get()


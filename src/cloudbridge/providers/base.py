from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from ..models import EntryKind, RemoteEntry
from ..paths import normalize_virtual_path


class CloudProvider(ABC):
    name: str

    @abstractmethod
    async def list_directory(self, path: str) -> list[RemoteEntry]:
        raise NotImplementedError

    @abstractmethod
    async def stat(self, path: str) -> RemoteEntry | None:
        raise NotImplementedError

    @abstractmethod
    async def ensure_directory(self, path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upload_file(self, local_path: str, remote_path: str, overwrite: bool = True) -> RemoteEntry:
        raise NotImplementedError

    @abstractmethod
    async def download_file(self, remote_path: str, local_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str, permanently: bool = True) -> None:
        raise NotImplementedError

    @abstractmethod
    async def move(self, source_path: str, target_path: str, overwrite: bool = True) -> None:
        raise NotImplementedError

    @abstractmethod
    async def publish(self, path: str) -> str:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    async def walk(self, root: str = "/", concurrency: int = 8) -> list[RemoteEntry]:
        normalized_root = normalize_virtual_path(root)
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        results: list[RemoteEntry] = []
        seen: set[str] = set()
        if normalized_root != "/":
            seen.add(normalized_root)
        await queue.put(normalized_root)

        async def worker() -> None:
            while True:
                current = await queue.get()
                if current is None:
                    queue.task_done()
                    return
                try:
                    children = await self.list_directory(current)
                    for child in children:
                        results.append(child)
                        if child.kind is EntryKind.DIRECTORY and child.path not in seen:
                            seen.add(child.path)
                            await queue.put(child.path)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max(1, concurrency))]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        return results


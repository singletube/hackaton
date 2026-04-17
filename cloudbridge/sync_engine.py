from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .hybrid_manager import HybridManager
from .models import FileStatus
from .provider import CloudProvider, ProviderError
from .state_db import StateDB


@dataclass(slots=True)
class SyncStats:
    uploaded_files: int = 0
    downloaded_files: int = 0
    created_cloud_dirs: int = 0
    created_local_dirs: int = 0
    errors: int = 0


class SyncEngine:
    def __init__(
        self,
        *,
        local_root: Path,
        cloud_root: str,
        provider: CloudProvider,
        state_db: StateDB,
        max_depth: int = -1,
    ) -> None:
        self._local_root = local_root.resolve()
        self._cloud_root = str(cloud_root or "disk:/")
        self._provider = provider
        self._state_db = state_db
        self._max_depth = max_depth
        self._ensured_cloud_dirs: set[str] = set()

    async def sync(self) -> SyncStats:
        manager = HybridManager(
            local_root=self._local_root,
            provider=self._provider,
            state_db=self._state_db,
        )
        await manager.discover(
            cloud_root=self._cloud_root,
            recursive=True,
            max_depth=self._max_depth,
        )

        rows = await self._state_db.list_all(include_deleted=False)
        stats = SyncStats()

        to_cloud_dirs = [
            row for row in rows
            if row["kind"] == "dir" and bool(row["local_exists"]) and not bool(row["cloud_exists"])
        ]
        to_cloud_dirs.sort(key=lambda row: str(row["path"]).count("/"))

        to_local_dirs = [
            row for row in rows
            if row["kind"] == "dir" and bool(row["cloud_exists"]) and not bool(row["local_exists"])
        ]
        to_local_dirs.sort(key=lambda row: str(row["path"]).count("/"))

        to_cloud_files = [
            row for row in rows
            if row["kind"] == "file" and bool(row["local_exists"]) and not bool(row["cloud_exists"])
        ]
        to_cloud_files.sort(key=lambda row: str(row["path"]))

        to_local_files = [
            row for row in rows
            if row["kind"] == "file" and bool(row["cloud_exists"]) and not bool(row["local_exists"])
        ]
        to_local_files.sort(key=lambda row: str(row["path"]))

        for row in to_cloud_dirs:
            await self._sync_dir_to_cloud(str(row["path"]), stats)
        for row in to_local_dirs:
            await self._sync_dir_to_local(str(row["path"]), stats)
        for row in to_cloud_files:
            await self._sync_file_to_cloud(str(row["path"]), stats)
        for row in to_local_files:
            await self._sync_file_to_local(str(row["path"]), stats)

        await manager.discover(
            cloud_root=self._cloud_root,
            recursive=True,
            max_depth=self._max_depth,
        )
        return stats

    async def _sync_dir_to_cloud(self, rel_path: str, stats: SyncStats) -> None:
        cloud_path = self._to_cloud_path(rel_path)
        try:
            await self._state_db.update_status(rel_path, FileStatus.SYNCING)
            await self._ensure_cloud_parents(rel_path)
            await self._provider.ensure_dir(cloud_path)
            await self._state_db.set_presence(rel_path, cloud_exists=True)
            await self._state_db.update_status(rel_path, FileStatus.SYNCED)
            self._ensured_cloud_dirs.add(cloud_path)
            stats.created_cloud_dirs += 1
        except (OSError, ProviderError) as exc:
            await self._state_db.update_status(rel_path, FileStatus.ERROR, error=str(exc))
            stats.errors += 1

    async def _sync_dir_to_local(self, rel_path: str, stats: SyncStats) -> None:
        local_path = self._to_local_path(rel_path)
        try:
            await self._state_db.update_status(rel_path, FileStatus.SYNCING)
            local_path.mkdir(parents=True, exist_ok=True)
            await self._state_db.set_presence(rel_path, local_exists=True)
            await self._state_db.update_status(rel_path, FileStatus.SYNCED)
            stats.created_local_dirs += 1
        except OSError as exc:
            await self._state_db.update_status(rel_path, FileStatus.ERROR, error=str(exc))
            stats.errors += 1

    async def _sync_file_to_cloud(self, rel_path: str, stats: SyncStats) -> None:
        local_path = self._to_local_path(rel_path)
        cloud_path = self._to_cloud_path(rel_path)
        try:
            await self._state_db.update_status(rel_path, FileStatus.SYNCING)
            await self._ensure_cloud_parents(rel_path)
            await self._provider.upload_file(local_path, cloud_path)
            await self._state_db.set_presence(rel_path, cloud_exists=True)
            await self._state_db.update_status(rel_path, FileStatus.SYNCED)
            stats.uploaded_files += 1
        except (OSError, ProviderError) as exc:
            await self._state_db.update_status(rel_path, FileStatus.ERROR, error=str(exc))
            stats.errors += 1

    async def _sync_file_to_local(self, rel_path: str, stats: SyncStats) -> None:
        local_path = self._to_local_path(rel_path)
        cloud_path = self._to_cloud_path(rel_path)
        try:
            await self._state_db.update_status(rel_path, FileStatus.SYNCING)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            await self._provider.download_file(cloud_path, local_path)
            await self._state_db.set_presence(rel_path, local_exists=True)
            await self._state_db.update_status(rel_path, FileStatus.SYNCED)
            stats.downloaded_files += 1
        except (OSError, ProviderError) as exc:
            await self._state_db.update_status(rel_path, FileStatus.ERROR, error=str(exc))
            stats.errors += 1

    async def _ensure_cloud_parents(self, rel_path: str) -> None:
        parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        if not parent:
            return
        progressive: list[str] = []
        for part in parent.split("/"):
            progressive.append(part)
            rel_dir = "/".join(progressive)
            cloud_dir = self._to_cloud_path(rel_dir)
            if cloud_dir in self._ensured_cloud_dirs:
                continue
            await self._provider.ensure_dir(cloud_dir)
            self._ensured_cloud_dirs.add(cloud_dir)

    def _to_cloud_path(self, rel_path: str) -> str:
        rel = rel_path.strip("/")
        root = self._cloud_root.strip()
        if root in ("disk:", "disk:/"):
            return "disk:/" if not rel else f"disk:/{rel}"
        if not root:
            return rel
        if not rel:
            return root
        return f"{root.rstrip('/')}/{rel}"

    def _to_local_path(self, rel_path: str) -> Path:
        local_path = (self._local_root / Path(rel_path)).resolve()
        if self._local_root not in local_path.parents and local_path != self._local_root:
            raise OSError(f"Refusing path outside local root: {rel_path}")
        return local_path

import shutil
import uuid
from pathlib import Path

import pytest

from cloudbridge.models import CloudEntry, FileKind
from cloudbridge.state_db import StateDB
from cloudbridge.sync_engine import SyncEngine


class FakeSyncProvider:
    def __init__(self) -> None:
        self.dirs: set[str] = {"disk:/", "disk:/cloud_dir"}
        self.files: dict[str, bytes] = {"disk:/cloud_only.txt": b"from-cloud"}

    async def list_dir(self, path: str):
        target = self._norm(path)
        entries = []

        for directory in sorted(self.dirs):
            if directory == target:
                continue
            if self._parent(directory) == target:
                entries.append(
                    CloudEntry(
                        path=directory,
                        name=directory.rsplit("/", 1)[-1],
                        kind=FileKind.DIRECTORY,
                        size=None,
                        etag=None,
                        modified_at=None,
                    )
                )
        for file_path, data in sorted(self.files.items()):
            if self._parent(file_path) == target:
                entries.append(
                    CloudEntry(
                        path=file_path,
                        name=file_path.rsplit("/", 1)[-1],
                        kind=FileKind.FILE,
                        size=len(data),
                        etag=None,
                        modified_at=None,
                    )
                )
        return entries

    async def read_range(self, path: str, offset: int, size: int) -> bytes:
        payload = self.files[self._norm(path)]
        return payload[offset : offset + size]

    async def ensure_dir(self, path: str) -> None:
        normalized = self._norm(path)
        self._ensure_parent_dirs(normalized)
        self.dirs.add(normalized)

    async def upload_file(self, local_path: Path, cloud_path: str) -> None:
        normalized = self._norm(cloud_path)
        self._ensure_parent_dirs(normalized)
        self.files[normalized] = local_path.read_bytes()

    async def download_file(self, cloud_path: str, local_path: Path) -> None:
        payload = self.files[self._norm(cloud_path)]
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(payload)

    async def delete(self, path: str) -> None:
        normalized = self._norm(path)
        self.files.pop(normalized, None)
        self.dirs.discard(normalized)

    async def share_link(self, path: str) -> str:
        return f"https://example.test/share/{self._norm(path)}"

    async def close(self) -> None:
        return None

    def _ensure_parent_dirs(self, path: str) -> None:
        parent = self._parent(path)
        while parent is not None:
            self.dirs.add(parent)
            if parent == "disk:/":
                break
            parent = self._parent(parent)

    @staticmethod
    def _norm(path: str) -> str:
        raw = str(path or "").strip()
        if raw in ("disk:", "disk:/", ""):
            return "disk:/"
        if raw.startswith("disk:/"):
            return f"disk:/{raw[len('disk:/') :].strip('/')}"
        return f"disk:/{raw.strip('/')}"

    @staticmethod
    def _parent(path: str):
        normalized = FakeSyncProvider._norm(path)
        if normalized == "disk:/":
            return None
        tail = normalized[len("disk:/") :]
        if "/" not in tail:
            return "disk:/"
        return f"disk:/{tail.rsplit('/', 1)[0]}"


@pytest.mark.asyncio
async def test_sync_engine_bidirectional_tree_alignment() -> None:
    case_dir = Path.cwd() / ".tmp_tests" / f"sync_{uuid.uuid4().hex}"
    local_root = case_dir / "local"
    local_root.mkdir(parents=True, exist_ok=True)

    (local_root / "local_dir" / "sub").mkdir(parents=True, exist_ok=True)
    (local_root / "upload.txt").write_text("from-local", encoding="utf-8")

    db = StateDB(case_dir / "state.db")
    await db.connect()
    await db.init_schema()

    provider = FakeSyncProvider()
    engine = SyncEngine(
        local_root=local_root,
        cloud_root="disk:/",
        provider=provider,
        state_db=db,
        max_depth=-1,
    )
    stats = await engine.sync()

    assert stats.errors == 0
    assert stats.uploaded_files >= 1
    assert stats.downloaded_files >= 1
    assert stats.created_cloud_dirs >= 1
    assert stats.created_local_dirs >= 1

    assert "disk:/upload.txt" in provider.files
    assert provider.files["disk:/upload.txt"] == b"from-local"
    assert (local_root / "cloud_only.txt").read_text(encoding="utf-8") == "from-cloud"
    assert (local_root / "cloud_dir").is_dir()

    upload_row = await db.get("upload.txt")
    cloud_only_row = await db.get("cloud_only.txt")
    cloud_dir_row = await db.get("cloud_dir")
    local_dir_row = await db.get("local_dir")

    assert upload_row is not None and upload_row["local_exists"] == 1 and upload_row["cloud_exists"] == 1
    assert cloud_only_row is not None and cloud_only_row["local_exists"] == 1 and cloud_only_row["cloud_exists"] == 1
    assert cloud_dir_row is not None and cloud_dir_row["local_exists"] == 1 and cloud_dir_row["cloud_exists"] == 1
    assert local_dir_row is not None and local_dir_row["local_exists"] == 1 and local_dir_row["cloud_exists"] == 1

    await db.close()
    shutil.rmtree(case_dir, ignore_errors=True)

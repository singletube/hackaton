import shutil
import uuid
from pathlib import Path

import pytest

from cloudbridge.hybrid_manager import HybridManager
from cloudbridge.models import CloudEntry, FileKind
from cloudbridge.state_db import StateDB


class FakeProvider:
    def __init__(self) -> None:
        self._data = {
            "disk:/": [
                CloudEntry(path="disk:/reports", name="reports", kind=FileKind.DIRECTORY),
                CloudEntry(path="disk:/remote.txt", name="remote.txt", kind=FileKind.FILE),
            ],
            "disk:/reports": [
                CloudEntry(
                    path="disk:/reports/2026.txt",
                    name="2026.txt",
                    kind=FileKind.FILE,
                )
            ],
        }

    async def list_dir(self, path: str) -> list[CloudEntry]:
        return self._data.get(path, [])

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_discover_merges_cloud_and_local() -> None:
    case_dir = Path.cwd() / ".tmp_tests" / f"hybrid_{uuid.uuid4().hex}"
    local_root = case_dir / "local"
    local_root.mkdir(parents=True, exist_ok=True)
    (local_root / "notes.txt").write_text("hello", encoding="utf-8")

    db = StateDB(case_dir / "state.db")
    await db.connect()
    await db.init_schema()

    manager = HybridManager(
        local_root=local_root,
        provider=FakeProvider(),
        state_db=db,
    )

    stats = await manager.discover(cloud_root="disk:/", recursive=True, max_depth=2)
    assert stats.cloud_items == 3
    assert stats.local_items == 1
    assert stats.merged_items >= 3

    remote = await db.get("remote.txt")
    nested = await db.get("reports/2026.txt")
    local = await db.get("notes.txt")

    assert remote is not None
    assert nested is not None
    assert local is not None
    assert remote["cloud_exists"] == 1
    assert local["local_exists"] == 1

    await db.close()
    shutil.rmtree(case_dir, ignore_errors=True)

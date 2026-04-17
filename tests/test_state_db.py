import shutil
import uuid
from pathlib import Path

import pytest

from cloudbridge.models import CloudEntry, FileKind, FileStatus, LocalEntry
from cloudbridge.state_db import StateDB


@pytest.mark.asyncio
async def test_state_db_upserts_cloud_and_local() -> None:
    case_dir = Path.cwd() / ".tmp_tests" / f"state_db_{uuid.uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    db = StateDB(case_dir / "state.db")
    await db.connect()
    await db.init_schema()

    cloud_count = await db.upsert_cloud_entries(
        [
            CloudEntry(
                path="docs/spec.md",
                name="spec.md",
                kind=FileKind.FILE,
                size=42,
            )
        ]
    )
    local_count = await db.upsert_local_entries(
        [LocalEntry(path="docs", name="docs", kind=FileKind.DIRECTORY)]
    )

    record = await db.get("docs/spec.md")
    assert cloud_count == 1
    assert local_count == 1
    assert record is not None
    assert record["cloud_exists"] == 1
    assert record["status"] == FileStatus.DISCOVERED.value

    await db.mark_local_event(
        "docs/spec.md",
        name="spec.md",
        kind=FileKind.FILE.value,
        status=FileStatus.QUEUED,
        exists=True,
    )
    updated = await db.get("docs/spec.md")
    assert updated is not None
    assert updated["status"] == FileStatus.QUEUED.value
    assert updated["local_exists"] == 1

    # Test pinning
    await db.set_pinned("docs/spec.md", True)
    pinned_items = await db.get_pinned()
    assert len(pinned_items) == 1
    assert pinned_items[0]["path"] == "docs/spec.md"

    # Test unpinning
    await db.set_pinned("docs/spec.md", False)
    pinned_items = await db.get_pinned()
    assert len(pinned_items) == 0

    await db.close()
    shutil.rmtree(case_dir, ignore_errors=True)

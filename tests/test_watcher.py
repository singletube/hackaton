from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.models import EntryKind, JobOperation, RemoteEntry
from cloudbridge.state import StateDB
from cloudbridge.watcher import LocalWatcher


@pytest.mark.asyncio
async def test_local_watcher_queues_upload_and_remote_delete_for_synced_file(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory")
    try:
        await watcher.seed()

        tracked_file = sync_root / "report.txt"
        tracked_file.write_text("payload", encoding="utf-8")

        first_changes = await watcher.poll()
        assert first_changes.uploaded_paths == ("/report.txt",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.UPLOAD
        assert jobs[0].path == "/report.txt"
        await state.complete_job(jobs[0].id)
        await state.upsert_remote_entries(
            "memory",
            [
                RemoteEntry(
                    path="/report.txt",
                    name="report.txt",
                    parent_path="/",
                    kind=EntryKind.FILE,
                    size=7,
                )
            ],
        )
        await state.resolve_entry_state("/report.txt")

        tracked_file.unlink()

        second_changes = await watcher.poll()
        assert second_changes.deleted_paths == ("/report.txt",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.DELETE_REMOTE
        assert jobs[0].path == "/report.txt"
    finally:
        await state.close()


@pytest.mark.asyncio
async def test_local_watcher_skips_remote_delete_for_local_only_file(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory")
    try:
        await watcher.seed()

        tracked_file = sync_root / "draft.txt"
        tracked_file.write_text("payload", encoding="utf-8")

        first_changes = await watcher.poll()
        assert first_changes.uploaded_paths == ("/draft.txt",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.UPLOAD
        await state.complete_job(jobs[0].id)

        tracked_file.unlink()

        second_changes = await watcher.poll()
        assert second_changes.deleted_paths == ("/draft.txt",)
        jobs = await state.claim_jobs(10)
        assert jobs == []
    finally:
        await state.close()

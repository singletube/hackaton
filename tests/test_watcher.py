from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.filesystem import materialize_remote_placeholders
from cloudbridge.models import EntryKind, JobOperation, RemoteEntry
from cloudbridge.state import StateDB
from cloudbridge.watcher import LocalWatcher


@pytest.mark.asyncio
async def test_local_watcher_queues_upload_and_remote_delete_for_synced_file(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory", backend="poll")
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
    watcher = LocalWatcher(state, sync_root, "memory", backend="poll")
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


@pytest.mark.asyncio
async def test_local_watcher_processes_notified_paths_with_watchdog_backend(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory", backend="watchdog")
    try:
        await watcher.seed()

        tracked_file = sync_root / "event.txt"
        tracked_file.write_text("payload", encoding="utf-8")
        watcher.notify("/event.txt")

        first_changes = await watcher.poll(timeout=0)
        assert first_changes.uploaded_paths == ("/event.txt",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.UPLOAD
        await state.complete_job(jobs[0].id)
        await state.upsert_remote_entries(
            "memory",
            [
                RemoteEntry(
                    path="/event.txt",
                    name="event.txt",
                    parent_path="/",
                    kind=EntryKind.FILE,
                    size=7,
                )
            ],
        )
        await state.resolve_entry_state("/event.txt")

        tracked_file.unlink()
        watcher.notify("/event.txt", deleted=True)

        second_changes = await watcher.poll(timeout=0)
        assert second_changes.deleted_paths == ("/event.txt",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.DELETE_REMOTE
    finally:
        await watcher.close()
        await state.close()


@pytest.mark.asyncio
async def test_local_watcher_deletes_remote_placeholder_with_watchdog_backend(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    remote_entry = RemoteEntry(
        path="/photo.jpg",
        name="photo.jpg",
        parent_path="/",
        kind=EntryKind.FILE,
        size=5_000_000,
    )

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory", backend="watchdog")
    try:
        await state.upsert_remote_entries("memory", [remote_entry])
        materialize_remote_placeholders(sync_root, [remote_entry])
        await watcher.seed()

        placeholder_path = sync_root / "photo.jpg"
        placeholder_path.unlink()
        watcher.notify("/photo.jpg", deleted=True)

        changes = await watcher.poll(timeout=0)
        assert changes.deleted_paths == ("/photo.jpg",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.DELETE_REMOTE
        assert jobs[0].path == "/photo.jpg"
    finally:
        await watcher.close()
        await state.close()


@pytest.mark.asyncio
async def test_local_watcher_moves_remote_placeholder_with_watchdog_backend(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir(parents=True, exist_ok=True)

    remote_entry = RemoteEntry(
        path="/photo.jpg",
        name="photo.jpg",
        parent_path="/",
        kind=EntryKind.FILE,
        size=5_000_000,
    )

    state = StateDB(tmp_path / "state.db")
    await state.connect()
    watcher = LocalWatcher(state, sync_root, "memory", backend="watchdog")
    try:
        await state.upsert_remote_entries("memory", [remote_entry])
        materialize_remote_placeholders(sync_root, [remote_entry])
        await watcher.seed()

        source_path = sync_root / "photo.jpg"
        target_path = sync_root / "renamed.jpg"
        source_path.rename(target_path)
        watcher._record_filesystem_event(
            type(
                "MoveEvent",
                (),
                {
                    "event_type": "moved",
                    "is_directory": False,
                    "src_path": str(source_path),
                    "dest_path": str(target_path),
                },
            )()
        )

        changes = await watcher.poll(timeout=0)
        assert changes.uploaded_paths == ("/renamed.jpg",)
        assert changes.deleted_paths == ("/photo.jpg",)
        jobs = await state.claim_jobs(10)
        assert len(jobs) == 1
        assert jobs[0].operation is JobOperation.MOVE_REMOTE
        assert jobs[0].path == "/photo.jpg"
        assert jobs[0].target_path == "/renamed.jpg"
    finally:
        await watcher.close()
        await state.close()

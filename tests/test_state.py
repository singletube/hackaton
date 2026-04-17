from __future__ import annotations

from pathlib import Path

import pytest

from cloudbridge.models import EntryKind, LocalEntry, RemoteEntry, SyncState
from cloudbridge.state import StateDB


@pytest.mark.asyncio
async def test_snapshots_merge_and_clear_stale_rows(tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    await state.connect()
    try:
        remote_entries = [
            RemoteEntry(path="/docs", name="docs", parent_path="/", kind=EntryKind.DIRECTORY),
            RemoteEntry(path="/docs/spec.txt", name="spec.txt", parent_path="/docs", kind=EntryKind.FILE, size=42),
        ]
        await state.apply_remote_snapshot("yandex", remote_entries, revision="remote-1")
        await state.apply_local_snapshot(
            "yandex",
            [LocalEntry(path="/notes.txt", name="notes.txt", parent_path="/", kind=EntryKind.FILE, size=11)],
            revision="local-1",
        )

        root_entries = await state.list_directory("/")
        states = {entry.path: entry.sync_state for entry in root_entries}
        assert states["/docs"] is SyncState.PLACEHOLDER
        assert states["/notes.txt"] is SyncState.LOCAL_ONLY

        await state.apply_remote_snapshot("yandex", [], revision="remote-2")
        assert await state.get_entry("/docs") is None
        assert await state.get_entry("/notes.txt") is not None
    finally:
        await state.close()


import asyncio
import pytest
from pathlib import Path
from cloudbridge.watcher import LocalWatcher

@pytest.mark.asyncio
async def test_local_watcher(tmp_path):
    watcher = LocalWatcher(tmp_path, recursive=False)
    loop = asyncio.get_running_loop()
    
    # Start watching
    watcher.start(loop)

    # Trigger a file creation event
    test_file = tmp_path / "new_file.txt"
    test_file.write_text("hello")

    # Wait for the event
    try:
        # We use asyncio.wait_for to prevent infinite hang if event isn't caught
        event = await asyncio.wait_for(watcher.next_event(), timeout=2.0)
        assert event.src_path == str(test_file)
        assert event.event_type in ["created", "modified"]
        assert not event.is_directory
    finally:
        watcher.stop()

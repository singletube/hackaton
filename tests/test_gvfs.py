import os
from pathlib import Path
from unittest.mock import patch

import pytest
from cloudbridge.gvfs import add_bookmark, remove_bookmark, get_bookmarks_path

def test_gvfs_add_and_remove_bookmark(tmp_path, monkeypatch):
    # Setup isolated config dir
    config_dir = tmp_path / ".config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))

    mountpoint = tmp_path / "mnt"
    uri = f"file://{mountpoint.resolve().as_posix()}"

    # Try adding before gtk-3.0 dir exists
    add_bookmark(mountpoint, "TestCloud")
    
    # Should not crash, and shouldn't create anything yet since we expect the parent to exist 
    # (actually our logic says `if not bm_path.parent.exists(): return`)
    bm_path = get_bookmarks_path()
    assert not bm_path.exists()

    # Now create the directory
    bm_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Add bookmark
    add_bookmark(mountpoint, "TestCloud")
    assert bm_path.exists()
    content = bm_path.read_text()
    assert f"{uri} TestCloud" in content

    # Add again, should not duplicate
    add_bookmark(mountpoint, "TestCloud")
    lines = bm_path.read_text().splitlines()
    assert len(lines) == 1

    # Remove bookmark
    remove_bookmark(mountpoint)
    content = bm_path.read_text()
    assert uri not in content

def test_gvfs_remove_nonexistent(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    
    # Removing when file doesn't exist should not crash
    remove_bookmark(tmp_path / "mnt")
    
    bm_path = get_bookmarks_path()
    bm_path.parent.mkdir(parents=True, exist_ok=True)
    bm_path.write_text("file:///other Other\n")
    
    # Removing when not in file should not crash and not modify
    remove_bookmark(tmp_path / "mnt")
    assert bm_path.read_text() == "file:///other Other\n"

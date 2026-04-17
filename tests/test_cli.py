from __future__ import annotations

from pathlib import Path

from cloudbridge.cli import resolve_cli_path


def test_resolve_cli_path_maps_absolute_local_paths_inside_sync_root(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir()
    local_path = sync_root / "photos" / "turtle.jpg"
    local_path.parent.mkdir(parents=True)
    local_path.write_text("x", encoding="utf-8")

    assert resolve_cli_path(sync_root, str(local_path)) == "/photos/turtle.jpg"


def test_resolve_cli_path_keeps_external_absolute_paths_unchanged(tmp_path: Path) -> None:
    sync_root = tmp_path / "mirror"
    sync_root.mkdir()
    external_path = tmp_path / "Downloads" / "turtle.jpg"
    external_path.parent.mkdir(parents=True)
    external_path.write_text("x", encoding="utf-8")

    assert resolve_cli_path(sync_root, str(external_path)) == str(external_path)

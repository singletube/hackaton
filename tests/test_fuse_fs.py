import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path
import stat

try:
    import pyfuse3
except ImportError:
    pyfuse3 = None

from cloudbridge.fuse_fs import CloudBridgeFS
from cloudbridge.state_db import StateDB
from cloudbridge.models import CloudEntry, FileKind

pytestmark = pytest.mark.skipif(pyfuse3 is None, reason="pyfuse3 is not installed (Linux only)")

@pytest.fixture
def fake_db(tmp_path):
    db = StateDB(tmp_path / "state.db")
    return db

@pytest.mark.asyncio
async def test_cloudbridgefs_getattr_and_readdir(fake_db, tmp_path):
    await fake_db.connect()
    await fake_db.init_schema()
    
    # Add a mock entry
    await fake_db.upsert_cloud_entries([
        CloudEntry(path="folder", name="folder", kind=FileKind.DIRECTORY, size=0),
        CloudEntry(path="folder/file.txt", name="file.txt", kind=FileKind.FILE, size=1024)
    ])

    fs = CloudBridgeFS(
        local_root=tmp_path / "local",
        cloud_root="disk:/",
        state_db=fake_db,
        provider=None
    )
    
    await fs.refresh_index()
    
    # Root should exist
    root_attr = await fs.getattr(pyfuse3.ROOT_INODE)
    assert root_attr.st_mode & stat.S_IFDIR
    
    # Get children of root
    children = fs._children.get(pyfuse3.ROOT_INODE, [])
    assert len(children) == 1
    
    folder_inode = children[0]
    folder_attr = await fs.getattr(folder_inode)
    assert folder_attr.st_mode & stat.S_IFDIR
    
    # Get children of folder
    folder_children = fs._children.get(folder_inode, [])
    assert len(folder_children) == 1
    
    file_inode = folder_children[0]
    file_attr = await fs.getattr(file_inode)
    assert file_attr.st_mode & stat.S_IFREG
    assert file_attr.st_size == 1024

    await fake_db.close()

@pytest.mark.asyncio
async def test_cloudbridgefs_read_cloud_cache(fake_db, tmp_path):
    await fake_db.connect()
    await fake_db.init_schema()
    
    # Add a file
    await fake_db.upsert_cloud_entries([
        CloudEntry(path="file.txt", name="file.txt", kind=FileKind.FILE, size=10)
    ])

    mock_provider = AsyncMock()
    mock_provider.read_range.return_value = b"helloworld"

    local_dir = tmp_path / "local"
    local_dir.mkdir(parents=True, exist_ok=True)

    fs = CloudBridgeFS(
        local_root=local_dir,
        cloud_root="disk:/",
        state_db=fake_db,
        provider=mock_provider
    )
    
    await fs.refresh_index()
    
    # Find the inode for file.txt
    file_inode = fs._children.get(pyfuse3.ROOT_INODE, [])[0]
    node = fs._inode_to_node[file_inode]
    assert not node.local_exists
    
    # First read (should hit provider, download, and cache)
    data = await fs.read(file_inode, 0, 10)
    assert data == b"helloworld"
    
    # Check if cached locally
    local_file = local_dir / "file.txt"
    assert local_file.exists()
    assert local_file.read_bytes() == b"helloworld"
    
    # Internal node state should be updated
    assert node.local_exists

    # Second read should read from local, not provider
    mock_provider.read_range.reset_mock()
    data2 = await fs.read(file_inode, 0, 5)
    assert data2 == b"hello"
    mock_provider.read_range.assert_not_called()

    await fake_db.close()

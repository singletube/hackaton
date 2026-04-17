from __future__ import annotations

import asyncio
import errno
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import pyfuse3
    import pyfuse3_asyncio
except ImportError:
    pyfuse3 = None
    pyfuse3_asyncio = None

from .config import Settings
from .provider import CloudProvider
from .state_db import StateDB


def _parent_path(path: str) -> str:
    if not path or "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def _base_name(path: str) -> str:
    if not path:
        return ""
    if "/" not in path:
        return path
    return path.rsplit("/", 1)[1]


@dataclass(slots=True)
class _Node:
    inode: int
    path: str
    name: str
    is_dir: bool
    size: int
    local_exists: bool
    cloud_exists: bool
    modified_at_ns: Optional[int] = None


class _CloudBridgeFSBase:
    pass

BaseClass = pyfuse3.Operations if pyfuse3 else _CloudBridgeFSBase

class CloudBridgeFS(BaseClass):
    def __init__(
        self,
        *,
        local_root: Path,
        cloud_root: str,
        state_db: StateDB,
        provider: Optional[CloudProvider],
    ) -> None:
        super().__init__()
        self._local_root = local_root.resolve()
        self._cloud_root = cloud_root.rstrip("/")
        self._state_db = state_db
        self._provider = provider

        self._next_inode = pyfuse3.ROOT_INODE + 1
        self._path_to_node: dict[str, _Node] = {}
        self._inode_to_node: dict[int, _Node] = {}
        self._children: dict[int, list[int]] = {}

    async def refresh_index(self) -> None:
        rows = await self._state_db.list_all()
        self._path_to_node.clear()
        self._inode_to_node.clear()
        self._children.clear()
        self._next_inode = pyfuse3.ROOT_INODE + 1

        root = _Node(
            inode=pyfuse3.ROOT_INODE,
            path="",
            name="",
            is_dir=True,
            size=0,
            local_exists=True,
            cloud_exists=True,
        )
        self._register_node(root)

        for row in rows:
            rel_path = str(row["path"] or "").strip("/")
            if not rel_path:
                continue

            parent_parts = rel_path.split("/")[:-1]
            progressive = []
            for part in parent_parts:
                progressive.append(part)
                parent_path = "/".join(progressive)
                if parent_path not in self._path_to_node:
                    self._add_or_update_node(
                        path=parent_path,
                        is_dir=True,
                        size=0,
                        local_exists=True,
                        cloud_exists=True,
                    )

            is_dir = row["kind"] == "dir"
            self._add_or_update_node(
                path=rel_path,
                is_dir=is_dir,
                size=int(row["size"] or 0),
                local_exists=bool(row["local_exists"]),
                cloud_exists=bool(row["cloud_exists"]),
            )

        for node in sorted(self._inode_to_node.values(), key=lambda x: x.path):
            if node.inode == pyfuse3.ROOT_INODE:
                continue
            parent_path = _parent_path(node.path)
            parent = self._path_to_node.get(parent_path)
            if parent is None:
                continue
            self._children.setdefault(parent.inode, []).append(node.inode)

        for inode, children in self._children.items():
            children.sort(key=lambda child_inode: self._inode_to_node[child_inode].name)

    async def lookup(self, parent_inode: int, name: bytes, ctx=None):  # type: ignore[override]
        parent = self._inode_to_node.get(parent_inode)
        if parent is None or not parent.is_dir:
            raise pyfuse3.FUSEError(errno.ENOENT)

        decoded_name = name.decode("utf-8")
        if decoded_name in ("", "."):
            return await self.getattr(parent_inode, ctx)
        if decoded_name == "..":
            parent_path = _parent_path(parent.path)
            parent_node = self._path_to_node.get(parent_path, parent)
            return await self.getattr(parent_node.inode, ctx)

        child_path = decoded_name if not parent.path else f"{parent.path}/{decoded_name}"
        child = self._path_to_node.get(child_path)
        if child is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        return await self.getattr(child.inode, ctx)

    async def getattr(self, inode: int, ctx=None):  # type: ignore[override]
        node = self._inode_to_node.get(inode)
        if node is None:
            raise pyfuse3.FUSEError(errno.ENOENT)

        entry = pyfuse3.EntryAttributes()
        now_ns = time.time_ns()
        uid = os.getuid() if hasattr(os, "getuid") else 0
        gid = os.getgid() if hasattr(os, "getgid") else 0

        entry.st_ino = inode
        entry.st_uid = uid
        entry.st_gid = gid
        entry.st_rdev = 0
        entry.st_blksize = 512
        entry.st_nlink = 2 if node.is_dir else 1
        entry.entry_timeout = 1.0
        entry.attr_timeout = 1.0

        if node.is_dir:
            entry.st_mode = stat.S_IFDIR | 0o755
            entry.st_size = 0
            entry.st_blocks = 0
            entry.st_atime_ns = now_ns
            entry.st_mtime_ns = now_ns
            entry.st_ctime_ns = now_ns
            return entry

        local_path = self._local_root / node.path
        if node.local_exists and local_path.exists():
            st = await asyncio.to_thread(local_path.stat)
            entry.st_mode = stat.S_IFREG | 0o644
            entry.st_size = st.st_size
            entry.st_blocks = max(1, (st.st_size + 511) // 512)
            entry.st_atime_ns = int(st.st_atime_ns)
            entry.st_mtime_ns = int(st.st_mtime_ns)
            entry.st_ctime_ns = int(st.st_ctime_ns)
            return entry

        entry.st_mode = stat.S_IFREG | 0o444
        entry.st_size = node.size
        entry.st_blocks = max(1, (node.size + 511) // 512) if node.size else 0
        entry.st_atime_ns = now_ns
        entry.st_mtime_ns = now_ns
        entry.st_ctime_ns = now_ns
        return entry

    async def opendir(self, inode: int, ctx):  # type: ignore[override]
        node = self._inode_to_node.get(inode)
        if node is None or not node.is_dir:
            raise pyfuse3.FUSEError(errno.ENOTDIR)
        return inode

    async def readdir(self, inode: int, off: int, token):  # type: ignore[override]
        node = self._inode_to_node.get(inode)
        if node is None or not node.is_dir:
            raise pyfuse3.FUSEError(errno.ENOTDIR)

        children = self._children.get(inode, [])
        for index, child_inode in enumerate(children, start=1):
            if index <= off:
                continue
            child = self._inode_to_node[child_inode]
            attrs = await self.getattr(child_inode)
            if not pyfuse3.readdir_reply(
                token, child.name.encode("utf-8"), attrs, index
            ):
                break

    async def open(self, inode: int, flags: int, ctx):  # type: ignore[override]
        node = self._inode_to_node.get(inode)
        if node is None:
            raise pyfuse3.FUSEError(errno.ENOENT)
        if node.is_dir:
            raise pyfuse3.FUSEError(errno.EISDIR)
        return pyfuse3.FileInfo(fh=inode)

    async def read(self, fh: int, off: int, size: int):  # type: ignore[override]
        node = self._inode_to_node.get(fh)
        if node is None or node.is_dir:
            raise pyfuse3.FUSEError(errno.EINVAL)
        if size <= 0:
            return b""

        local_path = self._local_root / node.path
        if node.local_exists and local_path.exists():
            return await asyncio.to_thread(self._read_local_range, local_path, off, size)

        if node.cloud_exists and self._provider is not None:
            # Simple caching: if reading from cloud, download the entire file locally first
            # and update the state db to mark it as local_exists.
            try:
                cloud_path = self._to_cloud_path(node.path)
                data = await self._provider.read_range(cloud_path, 0, node.size)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(local_path.write_bytes, data)
                node.local_exists = True
                
                # We could update StateDB here to reflect local_exists=1
                # But for now, we just serve from the newly downloaded local file
                return await asyncio.to_thread(self._read_local_range, local_path, off, size)
            except Exception as e:
                print(f"Failed to cache {node.path}: {e}")
                # Fallback to direct read
                cloud_path = self._to_cloud_path(node.path)
                return await self._provider.read_range(cloud_path, off, size)

        raise pyfuse3.FUSEError(errno.ENOENT)

    async def release(self, fh: int):  # type: ignore[override]
        return None

    async def releasedir(self, fh: int):  # type: ignore[override]
        return None

    def _add_or_update_node(
        self,
        *,
        path: str,
        is_dir: bool,
        size: int,
        local_exists: bool,
        cloud_exists: bool,
    ) -> None:
        existing = self._path_to_node.get(path)
        if existing is not None:
            existing.is_dir = existing.is_dir or is_dir
            existing.size = size if size else existing.size
            existing.local_exists = existing.local_exists or local_exists
            existing.cloud_exists = existing.cloud_exists or cloud_exists
            return

        inode = pyfuse3.ROOT_INODE if path == "" else self._next_inode
        if path != "":
            self._next_inode += 1

        node = _Node(
            inode=inode,
            path=path,
            name=_base_name(path),
            is_dir=is_dir,
            size=size,
            local_exists=local_exists,
            cloud_exists=cloud_exists,
        )
        self._register_node(node)

    def _register_node(self, node: _Node) -> None:
        self._path_to_node[node.path] = node
        self._inode_to_node[node.inode] = node

    def _to_cloud_path(self, rel_path: str) -> str:
        if not rel_path:
            return self._cloud_root or "disk:/"
        if self._cloud_root in ("", "disk:"):
            return f"disk:/{rel_path}"
        if self._cloud_root.endswith("/"):
            return f"{self._cloud_root}{rel_path}"
        return f"{self._cloud_root}/{rel_path}"

    @staticmethod
    def _read_local_range(path: Path, offset: int, size: int) -> bytes:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read(size)


async def mount_cloudbridge(
    *,
    mountpoint: Path,
    settings: Settings,
    allow_other: bool = False,
) -> None:
    pyfuse3_asyncio.enable()
    state_db = StateDB(settings.db_path)
    await state_db.connect()
    await state_db.init_schema()

    provider: Optional[CloudProvider] = None
    try:
        from .__main__ import get_provider
        provider = get_provider(settings)
    except ValueError:
        print("No valid provider configuration found. Continuing without cloud access.")

    fs = CloudBridgeFS(
        local_root=settings.local_root,
        cloud_root=settings.cloud_root,
        state_db=state_db,
        provider=provider,
    )
    await fs.refresh_index()

    mountpoint.mkdir(parents=True, exist_ok=True)
    options = set(pyfuse3.default_options)
    options.add("fsname=cloudbridge")
    options.add("ro")
    options.add("auto_unmount")
    if allow_other:
        options.add("allow_other")

    pyfuse3.init(fs, str(mountpoint), options)
    try:
        await pyfuse3.main()
    finally:
        pyfuse3.close(unmount=True)
        if provider is not None:
            await provider.close()
        await state_db.close()


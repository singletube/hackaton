from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FileKind(str, Enum):
    FILE = "file"
    DIRECTORY = "dir"


class FileStatus(str, Enum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    SYNCING = "syncing"
    SYNCED = "synced"
    ERROR = "error"
    DELETED = "deleted"


@dataclass(slots=True)
class CloudEntry:
    path: str
    name: str
    kind: FileKind
    size: Optional[int] = None
    etag: Optional[str] = None
    modified_at: Optional[str] = None


@dataclass(slots=True)
class LocalEntry:
    path: str
    name: str
    kind: FileKind
    size: Optional[int] = None
    modified_at: Optional[str] = None


@dataclass(slots=True)
class DiscoverStats:
    cloud_items: int
    local_items: int
    merged_items: int


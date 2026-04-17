from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EntryKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


class SyncState(StrEnum):
    SYNCED = "synced"
    PLACEHOLDER = "placeholder"
    LOCAL_ONLY = "local_only"
    QUEUED = "queued"
    SYNCING = "syncing"
    ERROR = "error"


class JobOperation(StrEnum):
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE_REMOTE = "delete_remote"
    DELETE_LOCAL = "delete_local"
    MOVE_REMOTE = "move_remote"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class RemoteEntry:
    path: str
    name: str
    parent_path: str
    kind: EntryKind
    size: int | None = None
    modified_at: datetime | None = None
    etag: str | None = None
    checksum: str | None = None
    public_url: str | None = None


@dataclass(slots=True, frozen=True)
class LocalEntry:
    path: str
    name: str
    parent_path: str
    kind: EntryKind
    size: int | None = None
    modified_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class IndexedEntry:
    path: str
    name: str
    parent_path: str
    provider: str
    remote_kind: EntryKind | None
    local_kind: EntryKind | None
    remote_size: int | None
    local_size: int | None
    remote_modified_at: datetime | None
    local_modified_at: datetime | None
    remote_etag: str | None
    remote_hash: str | None
    public_url: str | None
    has_remote: bool
    has_local: bool
    sync_state: SyncState
    last_error: str | None

    @property
    def kind(self) -> EntryKind | None:
        return self.local_kind or self.remote_kind

    @property
    def size(self) -> int | None:
        return self.local_size if self.has_local else self.remote_size

    @property
    def kind_conflict(self) -> bool:
        return self.local_kind is not None and self.remote_kind is not None and self.local_kind != self.remote_kind


@dataclass(slots=True, frozen=True)
class SyncJob:
    id: int
    operation: JobOperation
    path: str
    target_path: str | None
    status: JobStatus
    priority: int
    attempts: int
    max_attempts: int
    payload: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def infer_sync_state(
    *,
    has_local: bool,
    has_remote: bool,
    local_kind: EntryKind | None,
    remote_kind: EntryKind | None,
    current_state: SyncState | None = None,
    last_error: str | None = None,
) -> SyncState:
    if current_state in {SyncState.QUEUED, SyncState.SYNCING}:
        return current_state
    if last_error:
        return SyncState.ERROR
    if has_local and has_remote and local_kind and remote_kind and local_kind != remote_kind:
        return SyncState.ERROR
    if has_local and has_remote:
        return SyncState.SYNCED
    if has_local:
        return SyncState.LOCAL_ONLY
    return SyncState.PLACEHOLDER

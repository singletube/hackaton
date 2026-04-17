from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import aiosqlite

from .models import (
    EntryKind,
    IndexedEntry,
    JobOperation,
    JobStatus,
    LocalEntry,
    RemoteEntry,
    SyncJob,
    SyncState,
    infer_sync_state,
)
from .paths import normalize_virtual_path


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parse_kind(value: str | None) -> EntryKind | None:
    return EntryKind(value) if value else None


def _parse_sync_state(value: str) -> SyncState:
    return SyncState(value)


class StateDB:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._connection is not None:
            return
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        await connection.execute("PRAGMA journal_mode=WAL;")
        await connection.execute("PRAGMA synchronous=NORMAL;")
        await connection.execute("PRAGMA foreign_keys=ON;")
        self._connection = connection
        await self.initialize()

    async def close(self) -> None:
        if self._connection is None:
            return
        await self._connection.close()
        self._connection = None

    async def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS entries (
                path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent_path TEXT NOT NULL,
                provider TEXT NOT NULL,
                remote_kind TEXT,
                local_kind TEXT,
                remote_size INTEGER,
                local_size INTEGER,
                remote_modified_at TEXT,
                local_modified_at TEXT,
                remote_etag TEXT,
                remote_hash TEXT,
                public_url TEXT,
                has_remote INTEGER NOT NULL DEFAULT 0,
                has_local INTEGER NOT NULL DEFAULT 0,
                remote_revision TEXT,
                local_revision TEXT,
                sync_state TEXT NOT NULL DEFAULT 'placeholder',
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_entries_parent_path ON entries(parent_path)",
            "CREATE INDEX IF NOT EXISTS idx_entries_sync_state ON entries(sync_state)",
            "CREATE INDEX IF NOT EXISTS idx_entries_provider ON entries(provider)",
            """
            CREATE TABLE IF NOT EXISTS sync_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                path TEXT NOT NULL,
                target_path TEXT,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                payload TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_jobs_pending_dedupe
            ON sync_jobs(dedupe_key)
            WHERE status IN ('queued', 'running')
            """,
            "CREATE INDEX IF NOT EXISTS idx_sync_jobs_status ON sync_jobs(status, priority, created_at)",
        ]
        async with self._lock:
            connection = self._require_connection()
            for statement in statements:
                await connection.execute(statement)
            await connection.commit()

    async def apply_remote_snapshot(self, provider: str, entries: Iterable[RemoteEntry], revision: str) -> None:
        await self.upsert_remote_entries(provider, entries, revision=revision)
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET has_remote = 0,
                    remote_kind = NULL,
                    remote_size = NULL,
                    remote_modified_at = NULL,
                    remote_etag = NULL,
                    remote_hash = NULL,
                    public_url = NULL,
                    remote_revision = NULL,
                    updated_at = ?
                WHERE provider = ?
                  AND has_remote = 1
                  AND COALESCE(remote_revision, '') != ?
                """,
                (now, provider, revision),
            )
            await self._recompute_states(connection)
            await self._purge_orphans(connection)
            await connection.commit()

    async def apply_local_snapshot(self, provider: str, entries: Iterable[LocalEntry], revision: str) -> None:
        await self.upsert_local_entries(provider, entries, revision=revision)
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET has_local = 0,
                    local_kind = NULL,
                    local_size = NULL,
                    local_modified_at = NULL,
                    local_revision = NULL,
                    updated_at = ?
                WHERE provider = ?
                  AND has_local = 1
                  AND COALESCE(local_revision, '') != ?
                """,
                (now, provider, revision),
            )
            await self._recompute_states(connection)
            await self._purge_orphans(connection)
            await connection.commit()

    async def upsert_remote_entries(
        self,
        provider: str,
        entries: Iterable[RemoteEntry],
        *,
        revision: str | None = None,
    ) -> None:
        now = _utc_now().isoformat()
        payload = [
            (
                entry.path,
                entry.name,
                entry.parent_path,
                provider,
                entry.kind.value,
                entry.size,
                _serialize_datetime(entry.modified_at),
                entry.etag,
                entry.checksum,
                entry.public_url,
                revision,
                now,
                now,
            )
            for entry in entries
        ]
        if not payload:
            return
        async with self._lock:
            connection = self._require_connection()
            await connection.executemany(
                """
                INSERT INTO entries (
                    path,
                    name,
                    parent_path,
                    provider,
                    remote_kind,
                    remote_size,
                    remote_modified_at,
                    remote_etag,
                    remote_hash,
                    public_url,
                    remote_revision,
                    has_remote,
                    sync_state,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'placeholder', ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    parent_path = excluded.parent_path,
                    provider = excluded.provider,
                    remote_kind = excluded.remote_kind,
                    remote_size = excluded.remote_size,
                    remote_modified_at = excluded.remote_modified_at,
                    remote_etag = excluded.remote_etag,
                    remote_hash = excluded.remote_hash,
                    public_url = excluded.public_url,
                    remote_revision = excluded.remote_revision,
                    has_remote = 1,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            await self._recompute_states(connection)
            await connection.commit()

    async def upsert_local_entries(
        self,
        provider: str,
        entries: Iterable[LocalEntry],
        *,
        revision: str | None = None,
    ) -> None:
        now = _utc_now().isoformat()
        payload = [
            (
                entry.path,
                entry.name,
                entry.parent_path,
                provider,
                entry.kind.value,
                entry.size,
                _serialize_datetime(entry.modified_at),
                revision,
                now,
                now,
            )
            for entry in entries
        ]
        if not payload:
            return
        async with self._lock:
            connection = self._require_connection()
            await connection.executemany(
                """
                INSERT INTO entries (
                    path,
                    name,
                    parent_path,
                    provider,
                    local_kind,
                    local_size,
                    local_modified_at,
                    local_revision,
                    has_local,
                    sync_state,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'local_only', ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    parent_path = excluded.parent_path,
                    provider = excluded.provider,
                    local_kind = excluded.local_kind,
                    local_size = excluded.local_size,
                    local_modified_at = excluded.local_modified_at,
                    local_revision = excluded.local_revision,
                    has_local = 1,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
            await self._recompute_states(connection)
            await connection.commit()

    async def clear_remote_prefix(self, provider: str, path: str) -> None:
        normalized = normalize_virtual_path(path)
        prefix = f"{normalized}/%"
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET has_remote = 0,
                    remote_kind = NULL,
                    remote_size = NULL,
                    remote_modified_at = NULL,
                    remote_etag = NULL,
                    remote_hash = NULL,
                    public_url = NULL,
                    remote_revision = NULL,
                    updated_at = ?
                WHERE provider = ?
                  AND (path = ? OR path LIKE ?)
                """,
                (now, provider, normalized, prefix),
            )
            await self._recompute_states(connection)
            await self._purge_orphans(connection)
            await connection.commit()

    async def clear_local_prefix(self, provider: str, path: str) -> None:
        normalized = normalize_virtual_path(path)
        prefix = f"{normalized}/%"
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET has_local = 0,
                    local_kind = NULL,
                    local_size = NULL,
                    local_modified_at = NULL,
                    local_revision = NULL,
                    updated_at = ?
                WHERE provider = ?
                  AND (path = ? OR path LIKE ?)
                """,
                (now, provider, normalized, prefix),
            )
            await self._recompute_states(connection)
            await self._purge_orphans(connection)
            await connection.commit()

    async def list_directory(self, path: str) -> list[IndexedEntry]:
        normalized = normalize_virtual_path(path)
        async with self._lock:
            connection = self._require_connection()
            cursor = await connection.execute(
                """
                SELECT *
                FROM entries
                WHERE parent_path = ?
                  AND (has_remote = 1 OR has_local = 1)
                ORDER BY CASE COALESCE(local_kind, remote_kind) WHEN 'directory' THEN 0 ELSE 1 END,
                         name COLLATE NOCASE ASC
                """,
                (normalized,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def list_entries_by_states(self, *states: SyncState) -> list[IndexedEntry]:
        if not states:
            return []
        placeholders = ",".join("?" for _ in states)
        async with self._lock:
            connection = self._require_connection()
            cursor = await connection.execute(
                f"""
                SELECT *
                FROM entries
                WHERE sync_state IN ({placeholders})
                ORDER BY path COLLATE NOCASE ASC
                """,
                [state.value for state in states],
            )
            rows = await cursor.fetchall()
        return [self._row_to_entry(row) for row in rows]

    async def get_entry(self, path: str) -> IndexedEntry | None:
        normalized = normalize_virtual_path(path)
        async with self._lock:
            connection = self._require_connection()
            cursor = await connection.execute("SELECT * FROM entries WHERE path = ?", (normalized,))
            row = await cursor.fetchone()
        return self._row_to_entry(row) if row else None

    async def set_sync_state(self, path: str, state: SyncState, last_error: str | None = None) -> None:
        normalized = normalize_virtual_path(path)
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET sync_state = ?, last_error = ?, updated_at = ?
                WHERE path = ?
                """,
                (state.value, last_error, now, normalized),
            )
            await connection.commit()

    async def enqueue_job(
        self,
        operation: JobOperation,
        path: str,
        *,
        target_path: str | None = None,
        priority: int = 100,
        max_attempts: int = 3,
        payload: dict[str, object] | None = None,
    ) -> None:
        normalized_path = normalize_virtual_path(path)
        normalized_target = normalize_virtual_path(target_path) if target_path else None
        now = _utc_now().isoformat()
        dedupe_key = f"{operation.value}:{normalized_path}:{normalized_target or ''}"
        serialized_payload = json.dumps(payload, sort_keys=True) if payload else None
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                INSERT OR IGNORE INTO sync_jobs (
                    dedupe_key,
                    operation,
                    path,
                    target_path,
                    status,
                    priority,
                    attempts,
                    max_attempts,
                    payload,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    dedupe_key,
                    operation.value,
                    normalized_path,
                    normalized_target,
                    JobStatus.QUEUED.value,
                    priority,
                    max_attempts,
                    serialized_payload,
                    now,
                    now,
                ),
            )
            await connection.commit()

    async def claim_jobs(self, limit: int) -> list[SyncJob]:
        if limit <= 0:
            return []
        async with self._lock:
            connection = self._require_connection()
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                """
                SELECT *
                FROM sync_jobs
                WHERE status = ?
                ORDER BY priority ASC, created_at ASC
                LIMIT ?
                """,
                (JobStatus.QUEUED.value, limit),
            )
            rows = await cursor.fetchall()
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                now = _utc_now().isoformat()
                await connection.execute(
                    f"""
                    UPDATE sync_jobs
                    SET status = ?, started_at = ?, updated_at = ?
                    WHERE id IN ({placeholders})
                    """,
                    [JobStatus.RUNNING.value, now, now, *ids],
                )
            await connection.commit()
        return [self._row_to_job(row, status_override=JobStatus.RUNNING) for row in rows]

    async def complete_job(self, job_id: int) -> None:
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE sync_jobs
                SET status = ?, finished_at = ?, updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (JobStatus.DONE.value, now, now, job_id),
            )
            await connection.commit()

    async def resolve_entry_state(self, path: str) -> None:
        normalized = normalize_virtual_path(path)
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE entries
                SET sync_state = CASE
                    WHEN last_error IS NOT NULL THEN 'error'
                    WHEN has_local = 1 AND has_remote = 1 AND local_kind IS NOT NULL AND remote_kind IS NOT NULL AND local_kind != remote_kind THEN 'error'
                    WHEN has_local = 1 AND has_remote = 1 THEN 'synced'
                    WHEN has_local = 1 THEN 'local_only'
                    ELSE 'placeholder'
                END
                WHERE path = ?
                """,
                (normalized,),
            )
            await self._purge_orphans(connection)
            await connection.commit()

    async def fail_job(self, job: SyncJob, error: str) -> None:
        next_attempt = job.attempts + 1
        next_status = JobStatus.QUEUED if next_attempt < job.max_attempts else JobStatus.FAILED
        now = _utc_now().isoformat()
        async with self._lock:
            connection = self._require_connection()
            await connection.execute(
                """
                UPDATE sync_jobs
                SET attempts = ?, status = ?, last_error = ?, updated_at = ?, finished_at = CASE WHEN ? = 'failed' THEN ? ELSE finished_at END
                WHERE id = ?
                """,
                (next_attempt, next_status.value, error, now, next_status.value, now, job.id),
            )
            await connection.commit()

    async def _recompute_states(self, connection: aiosqlite.Connection) -> None:
        await connection.execute(
            """
            UPDATE entries
            SET sync_state = CASE
                WHEN sync_state IN ('queued', 'syncing') THEN sync_state
                WHEN last_error IS NOT NULL THEN 'error'
                WHEN has_local = 1 AND has_remote = 1 AND local_kind IS NOT NULL AND remote_kind IS NOT NULL AND local_kind != remote_kind THEN 'error'
                WHEN has_local = 1 AND has_remote = 1 THEN 'synced'
                WHEN has_local = 1 THEN 'local_only'
                ELSE 'placeholder'
            END
            """
        )

    async def _purge_orphans(self, connection: aiosqlite.Connection) -> None:
        await connection.execute(
            """
            DELETE FROM entries
            WHERE has_local = 0
              AND has_remote = 0
              AND path NOT IN (
                SELECT path
                FROM sync_jobs
                WHERE status IN ('queued', 'running')
              )
            """
        )

    def _row_to_entry(self, row: sqlite3.Row) -> IndexedEntry:
        return IndexedEntry(
            path=row["path"],
            name=row["name"],
            parent_path=row["parent_path"],
            provider=row["provider"],
            remote_kind=_parse_kind(row["remote_kind"]),
            local_kind=_parse_kind(row["local_kind"]),
            remote_size=row["remote_size"],
            local_size=row["local_size"],
            remote_modified_at=_parse_datetime(row["remote_modified_at"]),
            local_modified_at=_parse_datetime(row["local_modified_at"]),
            remote_etag=row["remote_etag"],
            remote_hash=row["remote_hash"],
            public_url=row["public_url"],
            has_remote=bool(row["has_remote"]),
            has_local=bool(row["has_local"]),
            sync_state=_parse_sync_state(row["sync_state"]),
            last_error=row["last_error"],
        )

    def _row_to_job(self, row: sqlite3.Row, *, status_override: JobStatus | None = None) -> SyncJob:
        return SyncJob(
            id=row["id"],
            operation=JobOperation(row["operation"]),
            path=row["path"],
            target_path=row["target_path"],
            status=status_override or JobStatus(row["status"]),
            priority=row["priority"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            payload=row["payload"],
            last_error=row["last_error"],
            created_at=_parse_datetime(row["created_at"]) or _utc_now(),
            updated_at=_parse_datetime(row["updated_at"]) or _utc_now(),
        )

    def _require_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("StateDB is not connected.")
        return self._connection

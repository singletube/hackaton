from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import aiosqlite

from .models import CloudEntry, FileStatus, LocalEntry


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class StateDB:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA synchronous=NORMAL;")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init_schema(self) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('file', 'dir')),
                size INTEGER,
                etag TEXT,
                status TEXT NOT NULL,
                local_exists INTEGER NOT NULL DEFAULT 0,
                cloud_exists INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                modified_at TEXT,
                error TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_files_status
            ON files(status)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_files_prefix
            ON files(path)
            """
        )
        await conn.commit()

    async def upsert_cloud_entries(self, entries: Iterable[CloudEntry]) -> int:
        rows = []
        now = _utc_now()
        for item in entries:
            rows.append(
                (
                    item.path,
                    item.name,
                    item.kind.value,
                    item.size,
                    item.etag,
                    FileStatus.DISCOVERED.value,
                    item.modified_at,
                    now,
                )
            )

        if not rows:
            return 0

        conn = self._require_conn()
        await conn.executemany(
            """
            INSERT INTO files(
                path, name, kind, size, etag, status, cloud_exists, pinned, modified_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                size = excluded.size,
                etag = excluded.etag,
                status = CASE
                    WHEN files.status = 'deleted' THEN 'discovered'
                    ELSE files.status
                END,
                cloud_exists = 1,
                modified_at = COALESCE(excluded.modified_at, files.modified_at),
                updated_at = excluded.updated_at
            """,
            rows,
        )
        await conn.commit()
        return len(rows)

    async def upsert_local_entries(self, entries: Iterable[LocalEntry]) -> int:
        rows = []
        now = _utc_now()
        for item in entries:
            rows.append(
                (
                    item.path,
                    item.name,
                    item.kind.value,
                    item.size,
                    FileStatus.DISCOVERED.value,
                    item.modified_at,
                    now,
                )
            )

        if not rows:
            return 0

        conn = self._require_conn()
        await conn.executemany(
            """
            INSERT INTO files(
                path, name, kind, size, status, local_exists, modified_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                size = excluded.size,
                status = CASE
                    WHEN files.status = 'deleted' THEN 'discovered'
                    ELSE files.status
                END,
                local_exists = 1,
                modified_at = COALESCE(excluded.modified_at, files.modified_at),
                updated_at = excluded.updated_at
            """,
            rows,
        )
        await conn.commit()
        return len(rows)

    async def reconcile_snapshot(
        self,
        *,
        cloud_paths: Iterable[str],
        local_paths: Iterable[str],
    ) -> None:
        conn = self._require_conn()
        now = _utc_now()

        await conn.execute("CREATE TEMP TABLE IF NOT EXISTS _snapshot_cloud(path TEXT PRIMARY KEY)")
        await conn.execute("CREATE TEMP TABLE IF NOT EXISTS _snapshot_local(path TEXT PRIMARY KEY)")
        await conn.execute("DELETE FROM _snapshot_cloud")
        await conn.execute("DELETE FROM _snapshot_local")

        cloud_rows = [(path,) for path in cloud_paths if path]
        local_rows = [(path,) for path in local_paths if path]

        if cloud_rows:
            await conn.executemany(
                "INSERT OR IGNORE INTO _snapshot_cloud(path) VALUES (?)",
                cloud_rows,
            )
        if local_rows:
            await conn.executemany(
                "INSERT OR IGNORE INTO _snapshot_local(path) VALUES (?)",
                local_rows,
            )

        await conn.execute(
            """
            UPDATE files
            SET cloud_exists = CASE
                WHEN EXISTS(SELECT 1 FROM _snapshot_cloud c WHERE c.path = files.path) THEN 1
                ELSE 0
            END
            """
        )
        await conn.execute(
            """
            UPDATE files
            SET local_exists = CASE
                WHEN EXISTS(SELECT 1 FROM _snapshot_local l WHERE l.path = files.path) THEN 1
                ELSE 0
            END
            """
        )
        await conn.execute(
            """
            UPDATE files
            SET status = ?, updated_at = ?
            WHERE local_exists = 0 AND cloud_exists = 0 AND status != ?
            """,
            (FileStatus.DELETED.value, now, FileStatus.DELETED.value),
        )
        await conn.commit()

    async def mark_local_event(
        self,
        path: str,
        *,
        name: str,
        kind: str,
        status: FileStatus,
        exists: bool,
    ) -> None:
        now = _utc_now()
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO files(
                path, name, kind, status, local_exists, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                status = excluded.status,
                local_exists = excluded.local_exists,
                updated_at = excluded.updated_at
            """,
            (
                path,
                name,
                kind,
                status.value,
                1 if exists else 0,
                now,
            ),
        )
        await conn.commit()

    async def update_status(
        self,
        path: str,
        status: FileStatus,
        *,
        error: Optional[str] = None,
    ) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            UPDATE files
            SET status = ?, error = ?, updated_at = ?
            WHERE path = ?
            """,
            (status.value, error, _utc_now(), path),
        )
        await conn.commit()

    async def set_presence(
        self,
        path: str,
        *,
        local_exists: Optional[bool] = None,
        cloud_exists: Optional[bool] = None,
    ) -> None:
        conn = self._require_conn()
        clauses: list[str] = []
        values: list[object] = []
        if local_exists is not None:
            clauses.append("local_exists = ?")
            values.append(1 if local_exists else 0)
        if cloud_exists is not None:
            clauses.append("cloud_exists = ?")
            values.append(1 if cloud_exists else 0)
        if not clauses:
            return
        clauses.append("updated_at = ?")
        values.append(_utc_now())
        values.append(path)
        await conn.execute(
            f"UPDATE files SET {', '.join(clauses)} WHERE path = ?",
            values,
        )
        await conn.commit()

    async def get(self, path: str) -> Optional[dict]:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT * FROM files WHERE path = ?", (path,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def count_all(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT COUNT(*) AS c FROM files")
        row = await cursor.fetchone()
        return int(row["c"])

    async def count_present(self) -> int:
        conn = self._require_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS c FROM files WHERE local_exists = 1 OR cloud_exists = 1"
        )
        row = await cursor.fetchone()
        return int(row["c"])

    async def get_pinned(self) -> list[dict]:
        conn = self._require_conn()
        cursor = await conn.execute("SELECT * FROM files WHERE pinned = 1")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def set_pinned(self, path: str, pinned: bool) -> None:
        conn = self._require_conn()
        await conn.execute(
            "UPDATE files SET pinned = ?, updated_at = ? WHERE path = ?",
            (1 if pinned else 0, _utc_now(), path),
        )
        await conn.commit()

    async def list_all(self, *, include_deleted: bool = True) -> list[dict]:
        conn = self._require_conn()
        if include_deleted:
            cursor = await conn.execute("SELECT * FROM files ORDER BY path ASC")
        else:
            cursor = await conn.execute(
                """
                SELECT * FROM files
                WHERE local_exists = 1 OR cloud_exists = 1
                ORDER BY path ASC
                """
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_changed(self, limit: int = 100) -> list[dict]:
        conn = self._require_conn()
        cursor = await conn.execute(
            """
            SELECT * FROM files
            WHERE status IN (?, ?, ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (
                FileStatus.QUEUED.value,
                FileStatus.SYNCING.value,
                FileStatus.ERROR.value,
                limit,
            ),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("StateDB is not connected")
        return self._conn

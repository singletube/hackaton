from __future__ import annotations

from datetime import UTC, datetime

from cloudbridge.models import EntryKind, IndexedEntry, JobOperation, JobStatus, SyncJob, SyncJobResult, SyncState
from cloudbridge.notifications import (
    format_entry_error_notification,
    format_sync_batch_notification,
    format_sync_job_notification,
)


def _build_job(operation: JobOperation, *, path: str = "/docs/report.txt", target_path: str | None = None) -> SyncJob:
    now = datetime.now(tz=UTC)
    return SyncJob(
        id=1,
        operation=operation,
        path=path,
        target_path=target_path,
        status=JobStatus.DONE,
        priority=100,
        attempts=0,
        max_attempts=3,
        payload=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


def test_format_sync_job_notification_for_successful_upload() -> None:
    summary, body = format_sync_job_notification(
        SyncJobResult(job=_build_job(JobOperation.UPLOAD), succeeded=True),
    )

    assert summary == "CloudBridge: загрузка завершена"
    assert body == "/docs/report.txt"


def test_format_sync_job_notification_for_failed_move() -> None:
    summary, body = format_sync_job_notification(
        SyncJobResult(
            job=_build_job(JobOperation.MOVE_REMOTE, target_path="/docs/archive/report.txt"),
            succeeded=False,
            error="permission denied",
        ),
    )

    assert summary == "CloudBridge: ошибка перемещения"
    assert "/docs/report.txt -> /docs/archive/report.txt" in body
    assert "permission denied" in body


def test_format_sync_batch_notification_summarizes_many_events() -> None:
    payload = format_sync_batch_notification(
        [
            SyncJobResult(job=_build_job(JobOperation.UPLOAD, path="/first.txt"), succeeded=True),
            SyncJobResult(job=_build_job(JobOperation.DOWNLOAD, path="/second.txt"), succeeded=False, error="timeout"),
        ],
    )

    assert payload is not None
    summary, body = payload
    assert summary == "CloudBridge: синхронизация завершена с ошибками"
    assert "успешно: 1" in body
    assert "ошибки: 1" in body
    assert "/first.txt" in body


def test_format_entry_error_notification_for_kind_conflict() -> None:
    entry = IndexedEntry(
        path="/docs/report",
        name="report",
        parent_path="/docs",
        provider="memory",
        remote_kind=EntryKind.FILE,
        local_kind=EntryKind.DIRECTORY,
        remote_size=42,
        local_size=None,
        remote_modified_at=None,
        local_modified_at=None,
        remote_etag=None,
        remote_hash=None,
        public_url=None,
        has_remote=True,
        has_local=True,
        sync_state=SyncState.ERROR,
        last_error=None,
    )

    summary, body = format_entry_error_notification(entry)

    assert summary == "CloudBridge: конфликт типа файла"
    assert "/docs/report" in body

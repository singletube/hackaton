from __future__ import annotations

import shutil
import subprocess

from .models import IndexedEntry, JobOperation, SyncJobResult


def send_desktop_notification(summary: str, body: str = "") -> bool:
    if not shutil.which("notify-send"):
        return False
    command = ["notify-send", summary]
    if body:
        command.append(body)
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def format_sync_job_notification(event: SyncJobResult) -> tuple[str, str]:
    job = event.job
    operation_titles = {
        JobOperation.UPLOAD: ("CloudBridge: загрузка завершена", "CloudBridge: ошибка загрузки"),
        JobOperation.DOWNLOAD: ("CloudBridge: скачивание завершено", "CloudBridge: ошибка скачивания"),
        JobOperation.DELETE_REMOTE: ("CloudBridge: файл удален из облака", "CloudBridge: ошибка удаления из облака"),
        JobOperation.DELETE_LOCAL: ("CloudBridge: локальная копия удалена", "CloudBridge: ошибка локального удаления"),
        JobOperation.MOVE_REMOTE: ("CloudBridge: перемещение завершено", "CloudBridge: ошибка перемещения"),
    }
    success_title, error_title = operation_titles[job.operation]
    if event.succeeded:
        if job.operation is JobOperation.MOVE_REMOTE and job.target_path:
            return success_title, f"{job.path} -> {job.target_path}"
        return success_title, job.path
    body = job.path
    if job.operation is JobOperation.MOVE_REMOTE and job.target_path:
        body = f"{job.path} -> {job.target_path}"
    if event.error:
        body = f"{body}\n{event.error}"
    return error_title, body


def format_sync_batch_notification(events: list[SyncJobResult]) -> tuple[str, str] | None:
    if not events:
        return None
    if len(events) == 1:
        return format_sync_job_notification(events[0])
    succeeded = sum(1 for event in events if event.succeeded)
    failed = len(events) - succeeded
    if failed:
        summary = "CloudBridge: синхронизация завершена с ошибками"
    else:
        summary = "CloudBridge: синхронизация завершена"
    parts = [f"успешно: {succeeded}"]
    if failed:
        parts.append(f"ошибки: {failed}")
    body = ", ".join(parts)
    body += f"\nпервый элемент: {events[0].job.path}"
    return summary, body


def format_entry_error_notification(entry: IndexedEntry) -> tuple[str, str]:
    if entry.kind_conflict:
        return "CloudBridge: конфликт типа файла", f"{entry.path}\nлокальный и облачный типы не совпадают"
    if entry.last_error:
        return "CloudBridge: ошибка синхронизации", f"{entry.path}\n{entry.last_error}"
    return "CloudBridge: ошибка синхронизации", entry.path

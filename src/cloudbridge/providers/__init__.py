from __future__ import annotations

from .base import CloudProvider
from .nextcloud import NextcloudProvider
from .yandex_disk import YandexDiskProvider

__all__ = ["CloudProvider", "NextcloudProvider", "YandexDiskProvider"]


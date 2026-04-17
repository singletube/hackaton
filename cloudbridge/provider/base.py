from __future__ import annotations

from typing import Protocol

from cloudbridge.models import CloudEntry


class ProviderError(RuntimeError):
    """Raised when provider API calls fail."""


class CloudProvider(Protocol):
    async def list_dir(self, path: str) -> list[CloudEntry]:
        raise NotImplementedError

    async def read_range(self, path: str, offset: int, size: int) -> bytes:
        raise NotImplementedError

    async def share_link(self, path: str) -> str:
        """Create and return a public share link for the given path."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

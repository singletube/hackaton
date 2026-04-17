from __future__ import annotations

from .base import CloudProvider


class NextcloudProvider(CloudProvider):
    name = "nextcloud"

    def __getattribute__(self, item: str):
        if item in {
            "list_directory",
            "stat",
            "ensure_directory",
            "upload_file",
            "download_file",
            "delete",
            "move",
            "publish",
        }:
            raise NotImplementedError("NextcloudProvider is not implemented in the first core iteration.")
        return super().__getattribute__(item)

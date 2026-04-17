from abc import ABC, abstractmethod
from typing import List, AsyncIterator, Optional
from ..models import CloudItem

class StorageProvider(ABC):
    @abstractmethod
    async def list_files(self, path: str = "/") -> List[CloudItem]:
        """Lists files in the given remote path."""
        pass

    @abstractmethod
    async def get_file_content(self, path: str, start: int = 0, end: Optional[int] = None) -> AsyncIterator[bytes]:
        """Downloads file content as an async stream, optionally with a range."""
        pass

    @abstractmethod
    async def upload_file(self, local_path: str, remote_path: str):
        """Uploads a local file to the remote storage."""
        pass

    @abstractmethod
    async def create_directory(self, path: str):
        """Creates a directory in the cloud."""
        pass

    @abstractmethod
    async def delete_file(self, path: str):
        """Deletes a file or directory from the cloud."""
        pass

    @abstractmethod
    async def move_file(self, src_path: str, dest_path: str):
        """Moves/renames a file or directory in the cloud."""
        pass

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime

class ItemType(str, Enum):
    FILE = "file"
    DIRECTORY = "dir"

class FileStatus(str, Enum):
    OFFLINE = "offline"      # Only on cloud
    SYNCING = "syncing"      # In progress
    SYNCED = "synced"        # Local matches cloud
    MODIFIED = "modified"    # Local changed, needs upload
    ERROR = "error"          # Something went wrong

class CloudItem(BaseModel):
    path: str
    name: str
    type: ItemType
    size: int = 0
    modified_at: datetime
    inode: Optional[int] = None
    etag: Optional[str] = None
    mime_type: Optional[str] = None
    resource_id: Optional[str] = None

class LocalState(BaseModel):
    path: str
    status: FileStatus
    last_sync: datetime
    local_path: Optional[str] = None
    hash: Optional[str] = None

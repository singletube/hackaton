import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from cloudbridge.provider.yandex import YandexDiskProvider
from cloudbridge.models import FileKind
from cloudbridge.provider.base import ProviderError

@pytest.fixture
def ya_provider():
    return YandexDiskProvider(token="fake_token")

@pytest.mark.asyncio
async def test_yandex_list_dir(ya_provider):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {
        "_embedded": {
            "items": [
                {
                    "path": "disk:/folder",
                    "name": "folder",
                    "type": "dir",
                    "modified": "2026-04-17T12:00:00Z"
                },
                {
                    "path": "disk:/test.txt",
                    "name": "test.txt",
                    "type": "file",
                    "size": 100,
                    "md5": "abc123md5",
                    "modified": "2026-04-17T12:00:00Z"
                }
            ],
            "total": 2
        }
    }

    mock_req = MagicMock()
    mock_req.__aenter__.return_value = mock_resp
    mock_req.__aexit__.return_value = False

    mock_session = MagicMock()
    mock_session.request.return_value = mock_req

    with patch.object(ya_provider, '_ensure_session', return_value=mock_session):
        entries = await ya_provider.list_dir("disk:/")
        assert len(entries) == 2
        
        assert entries[0].name == "folder"
        assert entries[0].kind == FileKind.DIRECTORY
        
        assert entries[1].name == "test.txt"
        assert entries[1].kind == FileKind.FILE
        assert entries[1].size == 100
        assert entries[1].etag == "abc123md5"

@pytest.mark.asyncio
async def test_yandex_read_range(ya_provider):
    # Mock for download link
    mock_link_resp = AsyncMock()
    mock_link_resp.status = 200
    mock_link_resp.json.return_value = {"href": "https://downloader.ya.ru/file"}

    mock_link_req = MagicMock()
    mock_link_req.__aenter__.return_value = mock_link_resp
    mock_link_req.__aexit__.return_value = False

    # Mock for file data
    mock_data_resp = AsyncMock()
    mock_data_resp.status = 206
    mock_data_resp.read.return_value = b"testdata"

    mock_data_req = MagicMock()
    mock_data_req.__aenter__.return_value = mock_data_resp
    mock_data_req.__aexit__.return_value = False

    mock_session = MagicMock()
    mock_session.request.return_value = mock_link_req
    mock_session.get.return_value = mock_data_req

    with patch.object(ya_provider, '_ensure_session', return_value=mock_session):
        data = await ya_provider.read_range("disk:/test.txt", 0, 8)
        assert data == b"testdata"
        mock_session.get.assert_called_once()
        args, kwargs = mock_session.get.call_args
        assert kwargs["headers"]["Range"] == "bytes=0-7"

@pytest.mark.asyncio
async def test_yandex_share_link(ya_provider):
    # Mock for publish (PUT)
    mock_put_resp = AsyncMock()
    mock_put_resp.status = 200
    mock_put_resp.json.return_value = {}

    mock_put_req = MagicMock()
    mock_put_req.__aenter__.return_value = mock_put_resp
    mock_put_req.__aexit__.return_value = False

    # Mock for get link (GET)
    mock_get_resp = AsyncMock()
    mock_get_resp.status = 200
    mock_get_resp.json.return_value = {"public_url": "https://yadi.sk/d/12345"}

    mock_get_req = MagicMock()
    mock_get_req.__aenter__.return_value = mock_get_resp
    mock_get_req.__aexit__.return_value = False

    mock_session = MagicMock()
    
    # request is called twice, first PUT then GET
    mock_session.request.side_effect = [mock_put_req, mock_get_req]

    with patch.object(ya_provider, '_ensure_session', return_value=mock_session):
        link = await ya_provider.share_link("disk:/test.txt")
        assert link == "https://yadi.sk/d/12345"
        assert mock_session.request.call_count == 2

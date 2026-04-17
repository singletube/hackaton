import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from cloudbridge.provider.nextcloud import NextCloudProvider
from cloudbridge.models import FileKind
from cloudbridge.provider.base import ProviderError

@pytest.fixture
def nc_provider():
    return NextCloudProvider(
        base_url="https://nc.example.com",
        username="user",
        password="password"
    )

@pytest.mark.asyncio
async def test_nextcloud_list_dir(nc_provider):
    xml_response = b"""<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:" xmlns:s="http://sabredav.org/ns" xmlns:oc="http://owncloud.org/dav">
     <d:response>
      <d:href>/remote.php/dav/files/user/</d:href>
      <d:propstat>
       <d:prop>
        <d:getlastmodified>Mon, 01 Jan 2026 00:00:00 GMT</d:getlastmodified>
        <d:resourcetype><d:collection/></d:resourcetype>
       </d:prop>
       <d:status>HTTP/1.1 200 OK</d:status>
      </d:propstat>
     </d:response>
     <d:response>
      <d:href>/remote.php/dav/files/user/test.txt</d:href>
      <d:propstat>
       <d:prop>
        <d:getlastmodified>Tue, 02 Jan 2026 00:00:00 GMT</d:getlastmodified>
        <d:resourcetype/>
        <d:getcontentlength>123</d:getcontentlength>
        <d:getetag>"abcdef"</d:getetag>
       </d:prop>
       <d:status>HTTP/1.1 200 OK</d:status>
      </d:propstat>
     </d:response>
    </d:multistatus>
    """

    mock_resp = AsyncMock()
    mock_resp.status = 207
    mock_resp.read.return_value = xml_response

    mock_req = MagicMock()
    mock_req.__aenter__.return_value = mock_resp
    mock_req.__aexit__.return_value = False

    mock_session = MagicMock()
    mock_session.request.return_value = mock_req

    with patch.object(nc_provider, '_ensure_session', return_value=mock_session):
        entries = await nc_provider.list_dir("")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.name == "test.txt"
        assert entry.kind == FileKind.FILE
        assert entry.size == 123
        assert entry.etag == "abcdef"
        assert entry.path == "test.txt"

@pytest.mark.asyncio
async def test_nextcloud_read_range(nc_provider):
    mock_resp = AsyncMock()
    mock_resp.status = 206
    mock_resp.read.return_value = b"testdata"

    mock_req = MagicMock()
    mock_req.__aenter__.return_value = mock_resp
    mock_req.__aexit__.return_value = False

    mock_session = MagicMock()
    mock_session.get.return_value = mock_req

    with patch.object(nc_provider, '_ensure_session', return_value=mock_session):
        data = await nc_provider.read_range("test.txt", 0, 8)
        assert data == b"testdata"
        mock_session.get.assert_called_once()
        args, kwargs = mock_session.get.call_args
        assert "headers" in kwargs
        assert kwargs["headers"]["Range"] == "bytes=0-7"

@pytest.mark.asyncio
async def test_nextcloud_share_link(nc_provider):
    xml_response = b"""<?xml version="1.0"?>
    <ocs>
     <meta><status>ok</status><statuscode>100</statuscode><message/></meta>
     <data>
      <id>1</id>
      <share_type>3</share_type>
      <url>https://nc.example.com/s/abcdefg</url>
     </data>
    </ocs>
    """

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.read.return_value = xml_response

    mock_req = MagicMock()
    mock_req.__aenter__.return_value = mock_resp
    mock_req.__aexit__.return_value = False

    mock_session = MagicMock()
    mock_session.post.return_value = mock_req

    with patch.object(nc_provider, '_ensure_session', return_value=mock_session):
        link = await nc_provider.share_link("test.txt")
        assert link == "https://nc.example.com/s/abcdefg"
        mock_session.post.assert_called_once()

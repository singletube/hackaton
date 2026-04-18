from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import aiohttp
import pytest
from aiohttp import web

from cloudbridge.config import AppConfig
from cloudbridge.providers import NextcloudProvider
from cloudbridge.setup import run_nextcloud_login_flow


@pytest.fixture
async def nextcloud_server() -> tuple[str, dict[str, object]]:
    state: dict[str, object] = {
        "user_id": "nc-user",
        "username": "alice",
        "password": "app-password",
        "directories": {"/", "/docs"},
        "files": {"/docs/readme.txt": b"hello"},
        "shares": {},
        "poll_ready": True,
    }

    def authenticate(request: web.Request) -> None:
        auth = request.headers.get("Authorization", "")
        expected = aiohttp.BasicAuth(str(state["username"]), str(state["password"])).encode()
        if auth != expected:
            raise web.HTTPUnauthorized(text="Unauthorized")

    def normalize_request_path(raw_path: str) -> str:
        normalized = raw_path.strip("/")
        return "/" if not normalized else f"/{normalized}"

    def dav_href(path: str) -> str:
        root = f"/remote.php/dav/files/{state['user_id']}"
        if path == "/":
            return f"{root}/"
        if path in state["directories"]:
            return f"{root}{quote(path)}/"
        return f"{root}{quote(path)}"

    def parent_path(path: str) -> str:
        normalized = normalize_request_path(path)
        if normalized == "/":
            return "/"
        parent = normalized.rsplit("/", 1)[0]
        return parent or "/"

    def entry_xml(path: str) -> str:
        is_directory = path in state["directories"]
        resource_type = "<d:collection />" if is_directory else ""
        size = "" if is_directory else str(len(state["files"][path]))
        modified = format_datetime(datetime.now().astimezone())
        return (
            "<d:response>"
            f"<d:href>{dav_href(path)}</d:href>"
            "<d:propstat>"
            "<d:prop>"
            f"<d:getlastmodified>{modified}</d:getlastmodified>"
            f"<d:getetag>\"{abs(hash(path))}\"</d:getetag>"
            f"<d:getcontentlength>{size}</d:getcontentlength>"
            f"<oc:size>{size}</oc:size>"
            f"<d:resourcetype>{resource_type}</d:resourcetype>"
            "</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status>"
            "</d:propstat>"
            "</d:response>"
        )

    async def handle_user(request: web.Request) -> web.Response:
        authenticate(request)
        return web.json_response(
            {
                "ocs": {
                    "meta": {"status": "ok", "statuscode": 100, "message": "OK"},
                    "data": {"id": state["user_id"]},
                }
            }
        )

    async def handle_shares(request: web.Request) -> web.Response:
        authenticate(request)
        shares: dict[str, str] = state["shares"]  # type: ignore[assignment]
        if request.method == "GET":
            path = normalize_request_path(request.query.get("path", "/"))
            data = []
            if path in shares:
                data.append({"share_type": 3, "url": shares[path], "path": path})
            return web.json_response(
                {
                    "ocs": {
                        "meta": {"status": "ok", "statuscode": 100, "message": "OK"},
                        "data": data,
                    }
                }
            )
        form = await request.post()
        path = normalize_request_path(str(form.get("path") or "/"))
        url = f"http://public.example.test/s/{quote(path.strip('/').replace('/', '-'))}"
        shares[path] = url
        return web.json_response(
            {
                "ocs": {
                    "meta": {"status": "ok", "statuscode": 100, "message": "OK"},
                    "data": {"share_type": 3, "url": url, "path": path},
                }
            }
        )

    async def handle_login_v2(request: web.Request) -> web.Response:
        host = f"http://{request.host}"
        return web.json_response(
            {
                "login": f"{host}/login-confirm",
                "poll": {"endpoint": f"{host}/login-v2/poll", "token": "poll-token"},
            }
        )

    async def handle_login_poll(request: web.Request) -> web.Response:
        form = await request.post()
        if form.get("token") != "poll-token":
            raise web.HTTPForbidden(text="Invalid token")
        if not state["poll_ready"]:
            raise web.HTTPNotFound(text="Pending")
        host = f"http://{request.host}"
        return web.json_response(
            {
                "server": host,
                "loginName": state["username"],
                "appPassword": state["password"],
            }
        )

    async def handle_dav(request: web.Request) -> web.Response:
        authenticate(request)
        if request.match_info["user_id"] != state["user_id"]:
            raise web.HTTPNotFound(text="Unknown user")
        raw_tail = request.match_info.get("tail", "")
        current_path = normalize_request_path(raw_tail)
        directories: set[str] = state["directories"]  # type: ignore[assignment]
        files: dict[str, bytes] = state["files"]  # type: ignore[assignment]

        if request.method == "PROPFIND":
            if current_path not in directories and current_path not in files:
                raise web.HTTPNotFound(text="Missing")
            depth = request.headers.get("Depth", "0")
            paths = [current_path]
            if depth == "1" and current_path in directories:
                paths.extend(sorted(path for path in directories if path != current_path and parent_path(path) == current_path))
                paths.extend(sorted(path for path in files if parent_path(path) == current_path))
            xml = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                + "".join(entry_xml(path) for path in paths)
                + "</d:multistatus>"
            )
            return web.Response(status=207, text=xml, content_type="application/xml")

        if request.method == "MKCOL":
            if current_path in directories:
                return web.Response(status=405)
            if parent_path(current_path) not in directories:
                return web.Response(status=409)
            directories.add(current_path)
            return web.Response(status=201)

        if request.method == "PUT":
            if parent_path(current_path) not in directories:
                raise web.HTTPConflict(text="Missing parent")
            files[current_path] = await request.read()
            return web.Response(status=201)

        if request.method == "GET":
            if current_path not in files:
                raise web.HTTPNotFound(text="Missing")
            return web.Response(status=200, body=files[current_path])

        if request.method == "DELETE":
            removed = False
            if current_path in files:
                files.pop(current_path, None)
                removed = True
            prefixes = [path for path in files if path.startswith(f"{current_path}/")]
            for path in prefixes:
                files.pop(path, None)
                removed = True
            nested_directories = [path for path in directories if path != "/" and (path == current_path or path.startswith(f"{current_path}/"))]
            for path in nested_directories:
                directories.remove(path)
                removed = True
            if not removed:
                raise web.HTTPNotFound(text="Missing")
            return web.Response(status=204)

        if request.method == "MOVE":
            destination_header = request.headers.get("Destination")
            if not destination_header:
                raise web.HTTPBadRequest(text="Missing Destination")
            destination_path = normalize_request_path(
                urlparse(destination_header).path.split(f"/remote.php/dav/files/{state['user_id']}", 1)[1]
            )
            if current_path in files:
                files[destination_path] = files.pop(current_path)
            elif current_path in directories:
                directories.add(destination_path)
                moved_directories = sorted(
                    path for path in directories if path != current_path and path.startswith(f"{current_path}/")
                )
                moved_files = {path: files[path] for path in files if path.startswith(f"{current_path}/")}
                directories.remove(current_path)
                for path in moved_directories:
                    directories.remove(path)
                for path in moved_directories:
                    suffix = path[len(current_path) :]
                    directories.add(f"{destination_path}{suffix}")
                for path, content in moved_files.items():
                    files.pop(path, None)
                    suffix = path[len(current_path) :]
                    files[f"{destination_path}{suffix}"] = content
            else:
                raise web.HTTPNotFound(text="Missing")
            return web.Response(status=201)

        raise web.HTTPMethodNotAllowed(request.method, ["PROPFIND", "MKCOL", "PUT", "GET", "DELETE", "MOVE"])

    app = web.Application()
    app.router.add_route("POST", "/index.php/login/v2", handle_login_v2)
    app.router.add_route("POST", "/login-v2/poll", handle_login_poll)
    app.router.add_route("GET", "/ocs/v1.php/cloud/user", handle_user)
    app.router.add_route("GET", "/ocs/v2.php/apps/files_sharing/api/v1/shares", handle_shares)
    app.router.add_route("POST", "/ocs/v2.php/apps/files_sharing/api/v1/shares", handle_shares)
    app.router.add_route("*", "/remote.php/dav/files/{user_id}/{tail:.*}", handle_dav)
    app.router.add_route("*", "/remote.php/dav/files/{user_id}", handle_dav)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    socket = site._server.sockets[0]
    base_url = f"http://127.0.0.1:{socket.getsockname()[1]}"
    try:
        yield base_url, state
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_nextcloud_provider_supports_crud_and_publish(nextcloud_server: tuple[str, dict[str, object]], tmp_path: Path) -> None:
    base_url, _state = nextcloud_server
    provider = NextcloudProvider(base_url, "alice", "app-password")
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"image")
    try:
        await provider.ensure_directory("/photos")
        uploaded = await provider.upload_file(str(source), "/photos/photo.jpg")
        assert uploaded.path == "/photos/photo.jpg"

        listed = await provider.list_directory("/photos")
        assert [entry.path for entry in listed] == ["/photos/photo.jpg"]

        downloaded = tmp_path / "downloaded.jpg"
        await provider.download_file("/photos/photo.jpg", str(downloaded))
        assert downloaded.read_bytes() == b"image"

        await provider.move("/photos/photo.jpg", "/photos/renamed.jpg")
        moved = await provider.stat("/photos/renamed.jpg")
        assert moved is not None
        assert moved.path == "/photos/renamed.jpg"

        published = await provider.publish("/photos/renamed.jpg")
        assert published.startswith("http://public.example.test/")

        await provider.delete("/photos/renamed.jpg")
        assert await provider.stat("/photos/renamed.jpg") is None
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_nextcloud_login_flow_and_persisted_config(nextcloud_server: tuple[str, dict[str, object]], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    base_url, _state = nextcloud_server
    opened: list[str] = []
    monkeypatch.setattr("cloudbridge.setup.webbrowser.open", lambda url: opened.append(url) or True)

    result = await run_nextcloud_login_flow(base_url, timeout=5.0, poll_interval=0.1)

    config = AppConfig(
        app_home=tmp_path / "app",
        sync_root=tmp_path / "mirror",
        database_path=tmp_path / "app" / "state.db",
        provider_name="nextcloud",
        yandex_token=None,
        nextcloud_url=result.server_url,
        nextcloud_username=result.login_name,
        nextcloud_password=result.app_password,
    )
    config_path = config.write_persisted_settings()
    loaded = AppConfig.from_env({"CLOUDBRIDGE_CONFIG": str(config_path)})

    assert opened == [result.login_url]
    assert result.login_name == "alice"
    assert result.app_password == "app-password"
    assert loaded.provider_name == "nextcloud"
    assert loaded.nextcloud_url == base_url
    assert loaded.nextcloud_username == "alice"

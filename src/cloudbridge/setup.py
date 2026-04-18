from __future__ import annotations

import asyncio
import uuid
import webbrowser
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin

import aiohttp


@dataclass(slots=True, frozen=True)
class NextcloudLoginPrompt:
    login_url: str
    poll_url: str
    browser_opened: bool


@dataclass(slots=True, frozen=True)
class NextcloudLoginResult:
    server_url: str
    login_name: str
    app_password: str
    login_url: str
    browser_opened: bool


@dataclass(slots=True, frozen=True)
class YandexDevicePrompt:
    verification_url: str
    user_code: str
    expires_in: int | None
    requested_scope: str | None
    browser_opened: bool


@dataclass(slots=True, frozen=True)
class YandexDeviceLoginResult:
    access_token: str
    refresh_token: str | None
    verification_url: str
    user_code: str
    expires_in: int | None
    requested_scope: str | None
    browser_opened: bool


async def run_nextcloud_login_flow(
    server_url: str,
    *,
    open_browser: bool = True,
    timeout: float = 600.0,
    poll_interval: float = 1.0,
    on_ready: Callable[[NextcloudLoginPrompt], None] | None = None,
) -> NextcloudLoginResult:
    base_url = server_url.rstrip("/")
    client_timeout = aiohttp.ClientTimeout(total=max(timeout, 30.0))
    async with aiohttp.ClientSession(timeout=client_timeout, raise_for_status=False) as session:
        async with session.post(f"{base_url}/index.php/login/v2", headers={"Accept": "application/json"}) as response:
            if response.status not in {200, 201}:
                text = await response.text()
                raise RuntimeError(f"Не удалось запустить вход в Nextcloud: HTTP {response.status}: {text}")
            payload = await response.json(content_type=None)

        login_url = str(payload.get("login") or "").strip()
        poll = payload.get("poll") or {}
        poll_endpoint = str(poll.get("endpoint") or "").strip()
        token = str(poll.get("token") or "").strip()
        if not login_url or not poll_endpoint or not token:
            raise RuntimeError(f"Nextcloud вернул неожиданный ответ при запуске входа: {payload!r}")

        browser_opened = False
        if open_browser:
            try:
                browser_opened = bool(await asyncio.to_thread(webbrowser.open, login_url))
            except Exception:
                browser_opened = False

        poll_url = urljoin(f"{base_url}/", poll_endpoint)
        if on_ready is not None:
            on_ready(
                NextcloudLoginPrompt(
                    login_url=login_url,
                    poll_url=poll_url,
                    browser_opened=browser_opened,
                )
            )
        deadline = asyncio.get_running_loop().time() + max(timeout, poll_interval)
        while True:
            async with session.post(poll_url, data={"token": token}, headers={"Accept": "application/json"}) as response:
                if response.status == 200:
                    credentials = await response.json(content_type=None)
                    login_name = str(credentials.get("loginName") or "").strip()
                    app_password = str(credentials.get("appPassword") or "").strip()
                    resolved_server_url = str(credentials.get("server") or base_url).rstrip("/")
                    if not login_name or not app_password:
                        raise RuntimeError(f"Nextcloud вернул неполные учетные данные приложения: {credentials!r}")
                    return NextcloudLoginResult(
                        server_url=resolved_server_url,
                        login_name=login_name,
                        app_password=app_password,
                        login_url=login_url,
                        browser_opened=browser_opened,
                    )
                if response.status not in {202, 404}:
                    text = await response.text()
                    raise RuntimeError(f"Не удалось дождаться подтверждения входа в Nextcloud: HTTP {response.status}: {text}")
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Истекло время ожидания подтверждения входа в Nextcloud.")
            await asyncio.sleep(max(0.2, poll_interval))


async def run_yandex_device_login_flow(
    client_id: str,
    client_secret: str,
    *,
    device_id: str | None = None,
    device_name: str = "CloudBridge Linux",
    scope: str | None = None,
    open_browser: bool = True,
    timeout: float = 600.0,
    on_ready: Callable[[YandexDevicePrompt], None] | None = None,
) -> YandexDeviceLoginResult:
    oauth_base = "https://oauth.yandex.com"
    client_timeout = aiohttp.ClientTimeout(total=max(timeout, 30.0))
    resolved_device_id = device_id or uuid.uuid4().hex
    async with aiohttp.ClientSession(timeout=client_timeout, raise_for_status=False) as session:
        init_payload = {
            "client_id": client_id,
            "device_id": resolved_device_id,
            "device_name": device_name,
        }
        if scope:
            init_payload["scope"] = scope
        async with session.post(f"{oauth_base}/device/code", data=init_payload) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(f"Не удалось запустить вход в Яндекс по коду устройства: HTTP {response.status}: {text}")
            payload = await response.json(content_type=None)

        device_code = str(payload.get("device_code") or "").strip()
        user_code = str(payload.get("user_code") or "").strip()
        verification_url = str(payload.get("verification_url") or "").strip()
        interval = max(1, int(payload.get("interval") or 5))
        expires_in = _coerce_int(payload.get("expires_in"))
        if not device_code or not user_code or not verification_url:
            raise RuntimeError(f"Яндекс вернул неожиданный ответ при запуске входа: {payload!r}")

        browser_opened = False
        if open_browser:
            try:
                browser_opened = bool(await asyncio.to_thread(webbrowser.open, verification_url))
            except Exception:
                browser_opened = False

        ready_state = YandexDevicePrompt(
            verification_url=verification_url,
            user_code=user_code,
            expires_in=expires_in,
            requested_scope=scope,
            browser_opened=browser_opened,
        )
        if on_ready is not None:
            on_ready(ready_state)

        deadline = asyncio.get_running_loop().time() + (expires_in or max(timeout, interval))
        auth = aiohttp.BasicAuth(client_id, client_secret)
        while True:
            async with session.post(
                f"{oauth_base}/token",
                auth=auth,
                data={
                    "grant_type": "device_code",
                    "code": device_code,
                },
            ) as response:
                payload = await response.json(content_type=None)
                if response.status == 200:
                    access_token = str(payload.get("access_token") or "").strip()
                    if not access_token:
                        raise RuntimeError(f"Яндекс вернул неожиданный ответ при получении токена: {payload!r}")
                    refresh_token = str(payload.get("refresh_token") or "").strip() or None
                    scope_value = str(payload.get("scope") or "").strip() or scope
                    return YandexDeviceLoginResult(
                        access_token=access_token,
                        refresh_token=refresh_token,
                        verification_url=verification_url,
                        user_code=user_code,
                        expires_in=_coerce_int(payload.get("expires_in")),
                        requested_scope=scope_value,
                        browser_opened=browser_opened,
                    )

                error_code = str(payload.get("error") or "").strip()
                if error_code == "authorization_pending":
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("Истекло время ожидания подтверждения входа в Яндекс.")
                    await asyncio.sleep(interval)
                    continue
                message = _format_yandex_device_error(payload)
                raise RuntimeError(message)


def _coerce_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _format_yandex_device_error(payload: object) -> str:
    if not isinstance(payload, dict):
        return "Не удалось выполнить вход в Яндекс по коду устройства."
    error_code = str(payload.get("error") or "").strip()
    error_description = str(payload.get("error_description") or "").strip()
    if error_code == "invalid_client" or error_description.lower() == "wrong client secret":
        return (
            "Яндекс отклонил данные OAuth-приложения. Проверьте, что Client ID и Client secret "
            "взяты из одного и того же приложения и что secret не был перевыпущен после копирования."
        )
    return error_description or error_code or "Не удалось выполнить вход в Яндекс по коду устройства."

from __future__ import annotations

from cloudbridge.setup import _format_yandex_device_error


def test_format_yandex_device_error_explains_invalid_client_pair() -> None:
    message = _format_yandex_device_error(
        {
            "error": "invalid_client",
            "error_description": "Wrong client secret",
        }
    )

    assert "Client ID" in message
    assert "Client secret" in message
    assert "одного и того же приложения" in message


def test_format_yandex_device_error_uses_original_description_for_other_cases() -> None:
    message = _format_yandex_device_error(
        {
            "error": "slow_down",
            "error_description": "Too many requests",
        }
    )

    assert message == "Too many requests"

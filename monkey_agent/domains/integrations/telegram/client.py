from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        request_timeout: int = 30,
        api_base_url: str = "https://api.telegram.org",
    ) -> None:
        self.bot_token = bot_token
        self.request_timeout = request_timeout
        self.api_base_url = api_base_url.rstrip("/")

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 25,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = self._post("getUpdates", payload)
        result = data.get("result", [])
        return result if isinstance(result, list) else []

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            return self._post("sendMessage", payload)
        except RuntimeError:
            if not parse_mode:
                raise
            payload.pop("parse_mode", None)
            return self._post("sendMessage", payload)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_base_url}/bot{self.bot_token}/{method}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "MonkeyAgent/0.1",
            },
        )
        with urllib.request.urlopen(
            request,
            timeout=self.request_timeout,
            context=_ssl_context(),
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(data)
        return data


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())

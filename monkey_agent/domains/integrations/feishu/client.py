from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FeishuClient:
    app_id: str
    app_secret: str
    base_url: str = "https://open.feishu.cn/open-apis"
    _token: str = ""
    _token_expire_at: float = 0.0
    sent_messages: list[dict[str, Any]] = field(default_factory=list)

    def send_text(
        self,
        *,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id",
    ) -> dict[str, Any]:
        if not receive_id:
            raise ValueError("receive_id is required")
        if not text:
            raise ValueError("text is required")
        token = self.tenant_access_token()
        query = urllib.parse.urlencode({"receive_id_type": receive_id_type or "chat_id"})
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        response = _post_json(
            f"{self.base_url.rstrip('/')}/im/v1/messages?{query}",
            payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        self.sent_messages.append(
            {
                "receive_id": receive_id,
                "receive_id_type": receive_id_type,
                "text": text,
                "response": response,
            }
        )
        return response

    def tenant_access_token(self) -> str:
        now = time.time()
        if self._token and self._token_expire_at - now > 60:
            return self._token
        if not self.app_id or not self.app_secret:
            raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")
        data = _post_json(
            f"{self.base_url.rstrip('/')}/auth/v3/tenant_access_token/internal",
            {"app_id": self.app_id, "app_secret": self.app_secret},
            headers={},
        )
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"missing tenant_access_token: {data}")
        expire = int(data.get("expire") or 7200)
        self._token = str(token)
        self._token_expire_at = now + expire
        return self._token


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "MonkeyAgent/0.1",
            **headers,
        },
    )
    with urllib.request.urlopen(request, timeout=10, context=_ssl_context()) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("code") not in (None, 0):
        raise RuntimeError(data)
    return data


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())

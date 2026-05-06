from __future__ import annotations

from pathlib import Path
from typing import Any

from monkey_agent.domains.integrations.feishu.events import payload_token


class FeishuSecurityError(ValueError):
    pass


def verify_payload(payload: dict[str, Any], verification_token: str) -> None:
    if not verification_token:
        return
    received = payload_token(payload)
    if received != verification_token:
        raise FeishuSecurityError("invalid_feishu_verification_token")


class EventDeduplicator:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def seen(self, event_key: str) -> bool:
        if not event_key:
            return False
        path = self.root / f"{_safe_key(event_key)}.seen"
        if path.exists():
            return True
        path.write_text(event_key, encoding="utf-8")
        return False


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)[:160]

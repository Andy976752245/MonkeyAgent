from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeishuEvent:
    event_id: str
    event_type: str
    message_id: str
    chat_id: str
    chat_type: str
    sender_id: str
    sender_id_type: str
    text: str
    raw: dict[str, Any]

    @property
    def receive_id_type(self) -> str:
        return "chat_id" if self.chat_id else "open_id"

    @property
    def receive_id(self) -> str:
        return self.chat_id or self.sender_id


def parse_event(payload: dict[str, Any]) -> FeishuEvent | None:
    event_type = _event_type(payload)
    if event_type != "im.message.receive_v1":
        return None
    event = payload.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = _first_non_empty(
        _nested(sender, ["sender_id", "open_id"]),
        _nested(sender, ["sender_id", "user_id"]),
        sender.get("open_id"),
        sender.get("user_id"),
    )
    sender_id_type = "open_id" if _nested(sender, ["sender_id", "open_id"]) else "user_id"
    chat_id = str(message.get("chat_id") or event.get("open_chat_id") or "")
    text = _message_text(message, event)
    message_id = str(
        message.get("message_id")
        or event.get("message_id")
        or _nested(payload, ["header", "event_id"])
        or ""
    )
    return FeishuEvent(
        event_id=str(_nested(payload, ["header", "event_id"]) or message_id),
        event_type=event_type,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=str(message.get("chat_type") or event.get("chat_type") or ""),
        sender_id=str(sender_id or ""),
        sender_id_type=sender_id_type,
        text=text,
        raw=payload,
    )


def is_url_verification(payload: dict[str, Any]) -> bool:
    return payload.get("type") == "url_verification" and bool(payload.get("challenge"))


def verification_response(payload: dict[str, Any]) -> dict[str, str]:
    return {"challenge": str(payload.get("challenge") or "")}


def payload_token(payload: dict[str, Any]) -> str:
    return str(payload.get("token") or _nested(payload, ["header", "token"]) or "")


def is_encrypted_payload(payload: dict[str, Any]) -> bool:
    return bool(payload.get("encrypt"))


def _event_type(payload: dict[str, Any]) -> str:
    return str(
        _nested(payload, ["header", "event_type"])
        or payload.get("type")
        or _nested(payload, ["event", "type"])
        or ""
    )


def _message_text(message: dict[str, Any], event: dict[str, Any]) -> str:
    if event.get("text_without_at_bot"):
        return str(event["text_without_at_bot"]).strip()
    raw = message.get("content") or event.get("content") or ""
    if isinstance(raw, dict):
        text = raw.get("text") or raw.get("content") or ""
    else:
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            text = str(raw)
        else:
            text = str(data.get("text") or data.get("content") or raw)
    return _strip_bot_mentions(text).strip()


def _strip_bot_mentions(text: str) -> str:
    text = re.sub(r"<at\s+[^>]*>.*?</at>", "", text)
    text = re.sub(r"@\S+\s*", "", text)
    return text


def _nested(data: dict[str, Any], keys: list[str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_non_empty(*items: Any) -> Any:
    for item in items:
        if item:
            return item
    return ""

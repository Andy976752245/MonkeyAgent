from __future__ import annotations

from collections.abc import Callable
from typing import Any

from monkey_agent.core.config import Settings
from monkey_agent.domains.integrations.feishu.client import FeishuClient
from monkey_agent.domains.integrations.feishu.events import (
    is_encrypted_payload,
    is_url_verification,
    parse_event,
    verification_response,
)
from monkey_agent.domains.integrations.feishu.security import (
    EventDeduplicator,
    verify_payload,
)


AskCallable = Callable[[str, dict[str, Any]], dict[str, Any]]


class FeishuEventHandler:
    def __init__(
        self,
        settings: Settings,
        ask: AskCallable,
        client: FeishuClient | None = None,
    ) -> None:
        self.settings = settings
        self.ask = ask
        self.client = client or FeishuClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
            base_url=settings.feishu_base_url,
        )
        self.deduplicator = EventDeduplicator(settings.runtime_dir / "feishu_events")

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        if is_encrypted_payload(payload):
            return {
                "status": "unsupported_encrypted_event",
                "message": "FEISHU_ENCRYPT_KEY is configured for future use, but encrypted callbacks are not implemented in this adapter yet.",
            }
        verify_payload(payload, self.settings.feishu_verification_token)
        if is_url_verification(payload):
            return verification_response(payload)

        event = parse_event(payload)
        if event is None:
            return {"status": "ignored", "reason": "unsupported_event_type"}
        if not event.text:
            return {"status": "ignored", "reason": "empty_message", "event_id": event.event_id}
        if not self._allowed(event.sender_id, self.settings.feishu_allowed_users):
            return {"status": "ignored", "reason": "sender_not_allowed", "sender_id": event.sender_id}
        if not self._allowed(event.chat_id, self.settings.feishu_allowed_chats):
            return {"status": "ignored", "reason": "chat_not_allowed", "chat_id": event.chat_id}

        event_key = event.message_id or event.event_id
        if self.deduplicator.seen(event_key):
            return {"status": "duplicate", "event_id": event.event_id, "message_id": event.message_id}

        context = {
            "channel": "feishu",
            "feishu_event_id": event.event_id,
            "feishu_message_id": event.message_id,
            "feishu_chat_id": event.chat_id,
            "feishu_chat_type": event.chat_type,
            "feishu_sender_id": event.sender_id,
            "feishu_sender_id_type": event.sender_id_type,
        }
        result = self.ask(event.text, context)
        answer = str(result.get("answer") or "我暂时没有生成可回复的内容。")
        reply_chunks = _split_reply(answer)
        responses = []
        for chunk in reply_chunks:
            responses.append(
                self.client.send_text(
                    receive_id=event.receive_id,
                    receive_id_type=event.receive_id_type,
                    text=chunk,
                )
            )
        return {
            "status": "replied",
            "event_id": event.event_id,
            "message_id": event.message_id,
            "sender_id": event.sender_id,
            "reply_count": len(reply_chunks),
            "agent_route": result.get("route"),
            "responses": responses,
        }

    def _allowed(self, value: str, allowed: list[str]) -> bool:
        return not allowed or value in allowed


def _split_reply(text: str, limit: int = 1500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks

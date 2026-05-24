from __future__ import annotations

from collections.abc import Callable
from typing import Any

from monkey_agent.core.config import Settings
from monkey_agent.domains.integrations.telegram.client import TelegramClient


AskCallable = Callable[[str, dict[str, Any]], dict[str, Any]]


class TelegramMessageHandler:
    def __init__(
        self,
        settings: Settings,
        ask: AskCallable,
        client: TelegramClient,
        trace_default: bool = False,
    ) -> None:
        self.settings = settings
        self.ask = ask
        self.client = client
        self.trace_default = trace_default
        self.trace_chat_ids: set[str] = set()

    def handle_update(self, update: dict[str, Any]) -> dict[str, Any]:
        message = update.get("message")
        if not isinstance(message, dict):
            return {"status": "ignored", "reason": "unsupported_update"}

        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        chat_id = str(chat.get("id") or "")
        user_id = str(sender.get("id") or "")
        if not chat_id:
            return {"status": "ignored", "reason": "missing_chat_id"}

        text = message.get("text")
        command = _command(str(text or ""))
        if command in {"/start", "/whoami"}:
            self._send_chunks(chat_id, _identity_message(chat_id, user_id, chat, self._authorized(chat_id)))
            return {"status": "replied", "command": command, "chat_id": chat_id}

        if not self._authorized(chat_id):
            if self._setup_mode():
                self._send_chunks(chat_id, _setup_message(chat_id))
                return {"status": "setup_required", "chat_id": chat_id}
            return {"status": "ignored", "reason": "chat_not_allowed", "chat_id": chat_id}

        if not text:
            self._send_chunks(chat_id, "当前仅支持文本消息。")
            return {"status": "replied", "reason": "non_text_message", "chat_id": chat_id}

        if command == "/trace":
            enabled = _trace_enabled(text)
            if enabled is None:
                self._send_chunks(chat_id, "请使用 /trace on 或 /trace off。")
            elif enabled:
                self.trace_chat_ids.add(chat_id)
                self._send_chunks(chat_id, "Trace 已开启。")
            else:
                self.trace_chat_ids.discard(chat_id)
                self._send_chunks(chat_id, "Trace 已关闭。")
            return {"status": "replied", "command": "/trace", "chat_id": chat_id}

        context = {
            "channel": "telegram",
            "telegram_chat_id": chat_id,
            "telegram_chat_type": str(chat.get("type") or ""),
            "telegram_user_id": user_id,
            "telegram_message_id": str(message.get("message_id") or ""),
            "session_id": f"telegram:{chat_id}",
        }
        result = self.ask(str(text), context)
        reply = _format_reply(result, trace=self._trace_enabled_for_chat(chat_id))
        self._send_chunks(chat_id, reply)
        return {
            "status": "replied",
            "chat_id": chat_id,
            "message_id": message.get("message_id"),
            "agent_route": result.get("route"),
            "run_id": result.get("run_id"),
        }

    def _authorized(self, chat_id: str) -> bool:
        allowed = self.settings.telegram_allowed_chat_ids
        return bool(allowed) and chat_id in allowed

    def _setup_mode(self) -> bool:
        return not self.settings.telegram_allowed_chat_ids

    def _trace_enabled_for_chat(self, chat_id: str) -> bool:
        return self.trace_default or chat_id in self.trace_chat_ids

    def _send_chunks(self, chat_id: str, text: str) -> None:
        for chunk in split_telegram_text(text):
            self.client.send_message(chat_id=chat_id, text=chunk)


def split_telegram_text(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def _command(text: str) -> str:
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    return first.split("@", 1)[0].lower()


def _trace_enabled(text: str) -> bool | None:
    parts = text.strip().split()
    if len(parts) < 2:
        return None
    value = parts[1].lower()
    if value in {"on", "开启", "开"}:
        return True
    if value in {"off", "关闭", "关"}:
        return False
    return None


def _identity_message(
    chat_id: str,
    user_id: str,
    chat: dict[str, Any],
    authorized: bool,
) -> str:
    status = "已授权" if authorized else "未授权或 setup mode"
    return (
        "MonkeyAgent Telegram Bot 已连接。\n"
        f"chat_id: {chat_id}\n"
        f"user_id: {user_id or '-'}\n"
        f"chat_type: {chat.get('type') or '-'}\n"
        f"status: {status}\n"
        "如需启用普通问答，请把 chat_id 加入 TELEGRAM_ALLOWED_CHAT_IDS。"
    )


def _setup_message(chat_id: str) -> str:
    return (
        "当前 Telegram Bot 处于 setup mode，普通问答暂未开启。\n"
        f"请在 .env 配置 TELEGRAM_ALLOWED_CHAT_IDS={chat_id} 后重启。"
    )


def _format_reply(result: dict[str, Any], trace: bool) -> str:
    answer = str(result.get("answer") or "我暂时没有生成可回复的内容。").strip()
    adoption_prompt = result.get("adoption_prompt")
    if adoption_prompt:
        answer = f"{answer}\n\n{adoption_prompt}"
    if not trace:
        return answer
    lines = [
        answer,
        "",
        "---",
        f"route: {result.get('route') or 'unknown'}",
        f"confidence: {result.get('confidence', 0.0)}",
    ]
    if result.get("run_id"):
        lines.append(f"run_id: {result['run_id']}")
    evaluation = result.get("evaluation") or {}
    if evaluation:
        lines.append(f"evaluation: {evaluation.get('status') or 'unknown'}")
    rules = result.get("matched_rules") or []
    if rules:
        lines.append("rules: " + ", ".join(str(item.get("name") or item.get("id")) for item in rules))
    skills = result.get("matched_skills") or []
    if skills:
        lines.append("skills: " + ", ".join(str(item.get("name") or item.get("id")) for item in skills))
    exploration = result.get("exploration") or {}
    if exploration.get("tool_id"):
        lines.append(f"tool: {exploration.get('tool_name') or exploration.get('tool_id')}")
    return "\n".join(lines)

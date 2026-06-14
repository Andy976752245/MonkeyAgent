from __future__ import annotations

from collections.abc import Callable
from typing import Any

from monkey_agent.core.config import Settings
from monkey_agent.domains.integrations.telegram.client import TelegramClient
from monkey_agent.domains.runs.diagnostics import diagnose_run


AskCallable = Callable[[str, dict[str, Any]], dict[str, Any]]
StatusProvider = Callable[[], dict[str, Any] | None]
GoalStartCallable = Callable[[str, dict[str, Any]], dict[str, Any]]
GoalStepCallable = Callable[[str, bool], dict[str, Any]]
GoalStatusCallable = Callable[[str], dict[str, Any]]
GoalListCallable = Callable[[], list[dict[str, Any]]]


class TelegramMessageHandler:
    def __init__(
        self,
        settings: Settings,
        ask: AskCallable,
        client: TelegramClient,
        trace_default: bool = False,
        status_provider: StatusProvider | None = None,
        goal_start: GoalStartCallable | None = None,
        goal_step: GoalStepCallable | None = None,
        goal_status: GoalStatusCallable | None = None,
        goal_list: GoalListCallable | None = None,
    ) -> None:
        self.settings = settings
        self.ask = ask
        self.client = client
        self.trace_default = trace_default
        self.status_provider = status_provider
        self.goal_start = goal_start
        self.goal_step = goal_step
        self.goal_status = goal_status
        self.goal_list = goal_list
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
        if command == "/help":
            self._send_chunks(chat_id, _help_message())
            return {"status": "replied", "command": command, "chat_id": chat_id}
        if command == "/settings":
            self._send_chunks(chat_id, _settings_message(chat_id, self.settings, self._trace_enabled_for_chat(chat_id)))
            return {"status": "replied", "command": command, "chat_id": chat_id}
        if command == "/status":
            self._send_chunks(
                chat_id,
                _status_message(
                    chat_id,
                    self.settings,
                    self._authorized(chat_id),
                    self._trace_enabled_for_chat(chat_id),
                    self.status_provider() if self.status_provider else None,
                    self.goal_list() if self.goal_list else None,
                ),
            )
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
        if self.settings.default_location:
            context["default_location"] = self.settings.default_location

        if command in {"/goal", "/goal_start"}:
            goal_text = _command_args(str(text))
            if not goal_text:
                self._send_chunks(chat_id, "请使用 /goal <目标内容> 启动一个目标。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            if not self.goal_start:
                self._send_chunks(chat_id, "Goal 功能暂未接入 Telegram。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            result = self.goal_start(goal_text, context)
            self._send_chunks(
                chat_id,
                _format_goal_reply(result, trace=self._trace_enabled_for_chat(chat_id)),
            )
            return {
                "status": "replied",
                "command": command,
                "chat_id": chat_id,
                "goal_id": result.get("goal_id"),
                "run_id": result.get("run_id"),
            }

        if command in {"/step", "/goal_step"}:
            goal_id = _command_args(str(text)) or self._select_goal_id({"active"})
            if not goal_id:
                self._send_chunks(chat_id, "当前没有 active 目标。请先使用 /goal <目标内容>，或用 /goals 查看目标列表。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            if not self.goal_step:
                self._send_chunks(chat_id, "Goal 功能暂未接入 Telegram。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            result = self.goal_step(goal_id, False)
            self._send_chunks(
                chat_id,
                _format_goal_reply(result, trace=self._trace_enabled_for_chat(chat_id)),
            )
            return {
                "status": "replied",
                "command": command,
                "chat_id": chat_id,
                "goal_id": goal_id,
                "run_id": result.get("run_id"),
            }

        if command in {"/confirm", "/goal_confirm"}:
            goal_id = _command_args(str(text)) or self._select_goal_id({"waiting_human"})
            if not goal_id:
                self._send_chunks(chat_id, "当前没有等待确认的目标。可以用 /goals 查看目标列表。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            if not self.goal_step:
                self._send_chunks(chat_id, "Goal 功能暂未接入 Telegram。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            result = self.goal_step(goal_id, True)
            self._send_chunks(
                chat_id,
                _format_goal_reply(result, trace=self._trace_enabled_for_chat(chat_id)),
            )
            return {
                "status": "replied",
                "command": command,
                "chat_id": chat_id,
                "goal_id": goal_id,
                "run_id": result.get("run_id"),
            }

        if command in {"/goal_status", "/goal_plan", "/goal_events"}:
            goal_id = _command_args(str(text)) or self._select_goal_id(None)
            if not goal_id:
                self._send_chunks(chat_id, "当前没有 Goal。请先使用 /goal <目标内容>。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            if not self.goal_status:
                self._send_chunks(chat_id, "Goal 功能暂未接入 Telegram。")
                return {"status": "replied", "command": command, "chat_id": chat_id}
            result = self.goal_status(goal_id)
            self._send_chunks(
                chat_id,
                _format_goal_reply(result, trace=self._trace_enabled_for_chat(chat_id)),
            )
            return {
                "status": "replied",
                "command": command,
                "chat_id": chat_id,
                "goal_id": goal_id,
                "run_id": result.get("run_id"),
            }

        if command in {"/goals", "/goal_list"}:
            goals = self.goal_list() if self.goal_list else []
            self._send_chunks(chat_id, _format_goal_list(goals))
            return {"status": "replied", "command": command, "chat_id": chat_id}

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

    def _select_goal_id(self, statuses: set[str] | None) -> str:
        goals = self.goal_list() if self.goal_list else []
        selected = _select_goal(goals, statuses)
        return _goal_id(selected) if selected else ""


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


def _command_args(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


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


def _help_message() -> str:
    return (
        "我是 MonkeyAgent，你的本地个人助理。\n\n"
        "我可以帮你：\n"
        "- 日常问答、解释概念、写作草稿\n"
        "- 计算、日期推算、单位换算\n"
        "- 查询天气等只读工具能力\n"
        "- 准备会议、拜访客户、整理周报结构\n"
        "- 执行 Goal 目标拆解与可恢复任务\n"
        "- 使用 YAML Skills / Agent Skills\n"
        "- 根据你的确认沉淀 Rules、Skills、Memory 和反例\n\n"
        "常用命令：/whoami、/status、/settings、/trace on、/trace off\n\n"
        "Goal 简化指令：\n"
        "- /goal 帮我接入飞书机器人发送消息\n"
        "- /step\n"
        "- /confirm\n"
        "- /goal_status\n"
        "- /goals"
    )


def _settings_message(chat_id: str, settings: Settings, trace_enabled: bool) -> str:
    default_location = settings.default_location or "未配置"
    return (
        "MonkeyAgent 设置\n"
        f"chat_id: {chat_id}\n"
        f"默认地点: {default_location}\n"
        f"Trace: {'开启' if trace_enabled else '关闭'}\n\n"
        "修改方式：\n"
        "- 默认地点：python3 -m monkey_agent setup location\n"
        "- Telegram：python3 -m monkey_agent setup telegram\n"
        "- 模型：python3 -m monkey_agent setup model"
    )


def _status_message(
    chat_id: str,
    settings: Settings,
    authorized: bool,
    trace_enabled: bool,
    latest_run: dict[str, Any] | None,
    goals: list[dict[str, Any]] | None = None,
) -> str:
    diagnosis = diagnose_run(latest_run)
    lines = [
        "MonkeyAgent 状态",
        f"授权: {'已授权' if authorized else '未授权或 setup mode'}",
        f"chat_id: {chat_id}",
        f"默认地点: {settings.default_location or '未配置'}",
        f"Trace: {'开启' if trace_enabled else '关闭'}",
    ]
    if latest_run:
        lines.append(f"最近 run_id: {latest_run.get('id') or '-'}")
        if latest_run.get("route"):
            lines.append(f"最近路由: {latest_run.get('route')}")
        if latest_run.get("errors"):
            lines.append("最近错误: " + str(latest_run.get("errors"))[:180])
        suggestions = diagnosis.get("suggestions") or []
        if suggestions:
            lines.append("诊断建议: " + str(suggestions[0]))
    else:
        lines.append("最近 run_id: 暂无")
    latest_goal = _select_goal(goals or [], None)
    if latest_goal:
        lines.append(
            "最近 Goal: "
            f"{_goal_id(latest_goal) or '-'} "
            f"({latest_goal.get('status') or '-'})"
        )
    return "\n".join(lines)


def _setup_message(chat_id: str) -> str:
    return (
        "当前 Telegram Bot 处于 setup mode，普通问答暂未开启。\n"
        f"请在 .env 配置 TELEGRAM_ALLOWED_CHAT_IDS={chat_id} 后重启。\n"
        "也可以运行：python3 -m monkey_agent setup telegram"
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


def _format_goal_reply(result: dict[str, Any], trace: bool) -> str:
    goal_id = str(result.get("goal_id") or result.get("id") or "")
    status = str(result.get("status") or "unknown")
    summary = str(
        result.get("answer")
        or result.get("summary")
        or result.get("confirmation_prompt")
        or "目标已更新。"
    ).strip()
    if len(summary) > 1200:
        summary = summary[:1200].rstrip() + "..."

    lines = ["Goal 已更新", f"goal_id: {goal_id or '-'}", f"status: {status}"]
    if summary:
        lines.extend(["", summary])

    requires_confirmation = bool(
        result.get("requires_confirmation")
        or status == "waiting_human"
        or result.get("resume_required")
    )
    if requires_confirmation:
        prompt = str(result.get("confirmation_prompt") or result.get("interrupt_payload") or "").strip()
        if prompt:
            lines.extend(["", "需要确认：", prompt[:600]])
        lines.append(f"\n继续请发送：/confirm {goal_id}".rstrip())
    elif status == "active":
        lines.append(f"\n继续请发送：/step {goal_id}".rstrip())
    elif status == "completed":
        run_id = result.get("run_id")
        if run_id:
            lines.append(f"\nrun_id: {run_id}")

    if trace:
        lines.extend(["", "---"])
        for key in ("thread_id", "checkpoint_backend", "next_action"):
            value = result.get(key)
            if value:
                lines.append(f"{key}: {value}")
        evaluation = result.get("last_evaluation") or result.get("evaluation") or {}
        if evaluation:
            lines.append(f"evaluation: {evaluation.get('status') or evaluation.get('next_action') or 'unknown'}")
    return "\n".join(lines)


def _format_goal_list(goals: list[dict[str, Any]]) -> str:
    if not goals:
        return "当前没有 Goal。可以发送 /goal <目标内容> 启动一个目标。"
    lines = ["最近 Goal："]
    for goal in _sort_goals(goals)[:5]:
        goal_id = _goal_id(goal) or "-"
        status = goal.get("status") or "-"
        summary = str(goal.get("summary") or goal.get("goal") or goal.get("answer") or "").strip()
        if len(summary) > 60:
            summary = summary[:60].rstrip() + "..."
        lines.append(f"- {goal_id} | {status} | {summary or '-'}")
    return "\n".join(lines)


def _select_goal(goals: list[dict[str, Any]], statuses: set[str] | None) -> dict[str, Any] | None:
    candidates = [goal for goal in goals if _goal_id(goal)]
    if statuses is not None:
        candidates = [goal for goal in candidates if str(goal.get("status") or "") in statuses]
    if not candidates:
        return None
    return _sort_goals(candidates)[0]


def _sort_goals(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(goal: dict[str, Any]) -> tuple[str, str]:
        updated = str(goal.get("updated_at") or goal.get("created_at") or "")
        return (updated, _goal_id(goal))

    return sorted(goals, key=key, reverse=True)


def _goal_id(goal: dict[str, Any] | None) -> str:
    if not goal:
        return ""
    return str(goal.get("goal_id") or goal.get("id") or "")

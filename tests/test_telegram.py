from __future__ import annotations

from test_rules_first import *  # noqa: F401,F403
from test_rules_first import _telegram_update
from monkey_agent.domains.integrations.telegram.polling import (
    _acquire_process_lock,
    _lock_path,
    _release_process_lock,
)

MonkeyAgentRulesFirstTest = None


class TelegramTest(unittest.TestCase):
    def test_telegram_setup_mode_allows_whoami_but_blocks_ask(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            calls = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: calls.append((question, context)) or {"answer": "ok"},
                client,
            )

            whoami = handler.handle_update(_telegram_update("/whoami", chat_id=123))
            self.assertEqual(whoami["status"], "replied")
            self.assertIn("chat_id: 123", client.sent[-1]["text"])

            blocked = handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertEqual(blocked["status"], "setup_required")
            self.assertEqual(calls, [])
            self.assertIn("TELEGRAM_ALLOWED_CHAT_IDS=123", client.sent[-1]["text"])

    def test_telegram_allowed_chat_invokes_agent_and_sends_answer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            calls = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: calls.append((question, context))
                or {"answer": "答案是 2", "route": "rules", "run_id": "run_1"},
                client,
            )

            result = handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertEqual(result["status"], "replied")
            self.assertEqual(calls[0][0], "1+1等于几")
            self.assertEqual(calls[0][1]["channel"], "telegram")
            self.assertEqual(calls[0][1]["telegram_chat_id"], "123")
            self.assertEqual(client.sent[-1]["text"], "答案是 2")

    def test_telegram_context_includes_default_location(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                    "default_location": "上海",
                }
            )
            calls = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: calls.append((question, context))
                or {"answer": "ok"},
                client,
            )

            handler.handle_update(_telegram_update("看下明天的天气", chat_id=123))
            self.assertEqual(calls[0][1]["default_location"], "上海")

    def test_telegram_rejects_non_whitelisted_chat(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            calls = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: calls.append((question, context)) or {"answer": "ok"},
                client,
            )
            result = handler.handle_update(_telegram_update("你好", chat_id=456))
            self.assertEqual(result["status"], "ignored")
            self.assertEqual(calls, [])
            self.assertEqual(client.sent, [])

    def test_telegram_trace_toggle_adds_route_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {
                    "answer": "已计算",
                    "route": "rules",
                    "run_id": "run_1",
                    "confidence": 0.9,
                    "evaluation": {"status": "pass"},
                },
                client,
            )
            handler.handle_update(_telegram_update("/trace on", chat_id=123))
            handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertIn("route: rules", client.sent[-1]["text"])
            self.assertIn("run_id: run_1", client.sent[-1]["text"])

            handler.handle_update(_telegram_update("/trace off", chat_id=123))
            handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertEqual(client.sent[-1]["text"], "已计算")

    def test_telegram_help_status_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                    "default_location": "上海",
                }
            )
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ok"},
                client,
                status_provider=lambda: {
                    "id": "run_1",
                    "type": "ask",
                    "status": "completed",
                    "input": {"question": "1+1等于几"},
                    "route": "rules",
                    "answer_preview": "2",
                    "timings": [{"node": "match_rules", "ms": 3}],
                },
                goal_list=lambda: [
                    {
                        "goal_id": "goal_1",
                        "status": "active",
                        "summary": "准备拜访方案",
                        "updated_at": "2026-06-08T12:00:00",
                    }
                ],
            )

            handler.handle_update(_telegram_update("/help", chat_id=123))
            self.assertIn("日常问答", client.sent[-1]["text"])
            self.assertIn("/goal", client.sent[-1]["text"])
            handler.handle_update(_telegram_update("/settings", chat_id=123))
            self.assertIn("默认地点: 上海", client.sent[-1]["text"])
            handler.handle_update(_telegram_update("/status", chat_id=123))
            self.assertIn("最近 run_id: run_1", client.sent[-1]["text"])
            self.assertIn("最近路由: rules", client.sent[-1]["text"])
            self.assertIn("最近 Goal: goal_1", client.sent[-1]["text"])

    def test_telegram_goal_start_uses_simplified_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            starts = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_start=lambda goal, context: starts.append((goal, context))
                or {
                    "goal_id": "goal_1",
                    "status": "active",
                    "summary": "已创建目标",
                    "run_id": "run_goal_1",
                },
            )

            result = handler.handle_update(_telegram_update("/goal 帮我准备拜访方案", chat_id=123))
            self.assertEqual(result["status"], "replied")
            self.assertEqual(starts[0][0], "帮我准备拜访方案")
            self.assertEqual(starts[0][1]["channel"], "telegram")
            self.assertIn("goal_id: goal_1", client.sent[-1]["text"])
            self.assertIn("/step goal_1", client.sent[-1]["text"])

    def test_telegram_goal_start_requires_goal_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            starts = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_start=lambda goal, context: starts.append(goal) or {},
            )

            handler.handle_update(_telegram_update("/goal", chat_id=123))
            self.assertEqual(starts, [])
            self.assertIn("/goal <目标内容>", client.sent[-1]["text"])

    def test_telegram_step_selects_latest_active_goal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            steps = []
            client = FakeTelegramClient()
            goals = [
                {"goal_id": "goal_old", "status": "active", "updated_at": "2026-06-08T10:00:00"},
                {"goal_id": "goal_new", "status": "active", "updated_at": "2026-06-08T11:00:00"},
                {"goal_id": "goal_wait", "status": "waiting_human", "updated_at": "2026-06-08T12:00:00"},
            ]
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_step=lambda goal_id, confirm: steps.append((goal_id, confirm))
                or {"goal_id": goal_id, "status": "completed", "summary": "完成"},
                goal_list=lambda: goals,
            )

            handler.handle_update(_telegram_update("/step", chat_id=123))
            self.assertEqual(steps, [("goal_new", False)])
            self.assertIn("status: completed", client.sent[-1]["text"])

    def test_telegram_step_can_use_explicit_goal_id(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            steps = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_step=lambda goal_id, confirm: steps.append((goal_id, confirm))
                or {"goal_id": goal_id, "status": "active", "summary": "继续"},
                goal_list=lambda: [],
            )

            handler.handle_update(_telegram_update("/step goal_custom", chat_id=123))
            self.assertEqual(steps, [("goal_custom", False)])

    def test_telegram_confirm_selects_latest_waiting_goal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            steps = []
            client = FakeTelegramClient()
            goals = [
                {"goal_id": "goal_active", "status": "active", "updated_at": "2026-06-08T12:00:00"},
                {"goal_id": "goal_wait", "status": "waiting_human", "updated_at": "2026-06-08T11:00:00"},
            ]
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_step=lambda goal_id, confirm: steps.append((goal_id, confirm))
                or {"goal_id": goal_id, "status": "completed", "summary": "已确认继续"},
                goal_list=lambda: goals,
            )

            handler.handle_update(_telegram_update("/confirm", chat_id=123))
            self.assertEqual(steps, [("goal_wait", True)])
            self.assertIn("goal_id: goal_wait", client.sent[-1]["text"])

    def test_telegram_goal_status_defaults_to_latest_goal(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            inspected = []
            client = FakeTelegramClient()
            goals = [
                {"goal_id": "goal_old", "status": "completed", "updated_at": "2026-06-08T10:00:00"},
                {"goal_id": "goal_new", "status": "active", "updated_at": "2026-06-08T12:00:00"},
            ]
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_status=lambda goal_id: inspected.append(goal_id)
                or {"goal_id": goal_id, "status": "active", "summary": "当前进度"},
                goal_list=lambda: goals,
            )

            handler.handle_update(_telegram_update("/goal_status", chat_id=123))
            self.assertEqual(inspected, ["goal_new"])
            self.assertIn("当前进度", client.sent[-1]["text"])

    def test_telegram_goals_lists_recent_goals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            client = FakeTelegramClient()
            goals = [
                {
                    "goal_id": f"goal_{index}",
                    "status": "active",
                    "summary": f"目标 {index}",
                    "updated_at": f"2026-06-08T12:0{index}:00",
                }
                for index in range(6)
            ]
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_list=lambda: goals,
            )

            handler.handle_update(_telegram_update("/goals", chat_id=123))
            text = client.sent[-1]["text"]
            self.assertIn("goal_5", text)
            self.assertNotIn("goal_0", text)

    def test_telegram_goal_commands_require_authorized_chat(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            starts = []
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_start=lambda goal, context: starts.append(goal) or {},
            )

            result = handler.handle_update(_telegram_update("/goal 帮我准备方案", chat_id=123))
            self.assertEqual(result["status"], "setup_required")
            self.assertEqual(starts, [])
            self.assertIn("TELEGRAM_ALLOWED_CHAT_IDS=123", client.sent[-1]["text"])

    def test_telegram_goal_trace_adds_checkpoint_fields(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "ask"},
                client,
                goal_start=lambda goal, context: {
                    "goal_id": "goal_1",
                    "status": "active",
                    "summary": "已创建",
                    "thread_id": "goal_1",
                    "checkpoint_backend": "sqlite",
                    "next_action": "continue",
                    "last_evaluation": {"status": "pass"},
                },
            )

            handler.handle_update(_telegram_update("/trace on", chat_id=123))
            handler.handle_update(_telegram_update("/goal 测试目标", chat_id=123))
            text = client.sent[-1]["text"]
            self.assertIn("thread_id: goal_1", text)
            self.assertIn("checkpoint_backend: sqlite", text)
            self.assertIn("next_action: continue", text)

    def test_telegram_non_text_message_returns_text_only_notice(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(settings, lambda question, context: {}, client)
            result = handler.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 7,
                        "chat": {"id": 123, "type": "private"},
                        "from": {"id": 99},
                        "photo": [{"file_id": "x"}],
                    },
                }
            )
            self.assertEqual(result["reason"], "non_text_message")
            self.assertEqual(client.sent[-1]["text"], "当前仅支持文本消息。")

    def test_telegram_polling_once_processes_updates_and_advances_offset(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            client = FakeTelegramClient(updates=[_telegram_update("你好", chat_id=123, update_id=41)])
            handler = TelegramMessageHandler(settings, lambda question, context: {"answer": "你好"}, client)
            runner = TelegramPollingRunner(settings, client, handler)
            result = runner.run(once=True)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["processed"], 1)
            self.assertEqual(runner.offset, 42)
            self.assertEqual(client.sent[-1]["text"], "你好")

    def test_telegram_polling_persists_offset_across_runner_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            first_client = FakeTelegramClient(
                updates=[_telegram_update("1加1等于几", chat_id=123, update_id=41)]
            )
            handler = TelegramMessageHandler(settings, lambda question, context: {"answer": "2"}, first_client)
            first_runner = TelegramPollingRunner(settings, first_client, handler)
            first_runner.run(once=True)

            second_client = FakeTelegramClient(updates=[])
            second_handler = TelegramMessageHandler(settings, lambda question, context: {"answer": "ok"}, second_client)
            second_runner = TelegramPollingRunner(settings, second_client, second_handler)
            second_runner.run(once=True)

            self.assertEqual(second_runner.offset, 42)
            self.assertEqual(second_client.get_updates_calls[0]["offset"], 42)

    def test_telegram_polling_rejects_second_running_instance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                }
            )
            lock = _acquire_process_lock(_lock_path(settings))
            self.assertIsNotNone(lock)
            try:
                client = FakeTelegramClient(updates=[_telegram_update("你好", chat_id=123)])
                handler = TelegramMessageHandler(settings, lambda question, context: {"answer": "ok"}, client)
                runner = TelegramPollingRunner(settings, client, handler)
                result = runner.run(once=True)
                self.assertEqual(result["status"], "already_running")
                self.assertEqual(client.sent, [])
            finally:
                _release_process_lock(lock)

    def test_telegram_split_reply_uses_telegram_limit(self) -> None:
        chunks = split_telegram_text("x" * 4100)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 4096)


if __name__ == "__main__":
    unittest.main()

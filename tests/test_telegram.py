from __future__ import annotations

from test_rules_first import *  # noqa: F401,F403
from test_rules_first import _telegram_update

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

    def test_telegram_split_reply_uses_telegram_limit(self) -> None:
        chunks = split_telegram_text("x" * 4100)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 4096)


if __name__ == "__main__":
    unittest.main()

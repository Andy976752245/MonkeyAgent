from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from monkey_agent.app.monkey_agent import MonkeyAgent
from monkey_agent.core.config import Settings
from monkey_agent.domains.integrations.telegram import TelegramMessageHandler
from monkey_agent.domains.models.bailian import LocalHeuristicModel
from monkey_agent.domains.runs.diagnostics import diagnose_run, format_diagnosis
from monkey_agent.domains.tools.capability import CapabilityRegistry, ToolResult
from monkey_agent.interfaces.cli.main import main as cli_main

from test_rules_first import (
    FakeTelegramClient,
    FakeWeatherTool,
    FailingWeatherTool,
    _telegram_update,
    settings_for,
    write_agent_skill,
    write_basic_rules,
)


class ProductRegressionTest(unittest.TestCase):
    def test_ask_routing_golden_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FakeWeatherTool(), FakeWebSearchTool()]),
            )
            cases = [
                ("1+1等于几", "rules", "2"),
                ("5乘以5等于多少", "rules", "25"),
                ("明天是几号", "rules", ""),
                ("水为什么会结冰", "general_reason", "水"),
                ("介绍你自己，说明你的能力", "general_reason", "MonkeyAgent"),
                (
                    "你用到LangGraph、Harness Engineering哪些内容？怎么应用的",
                    "general_reason",
                    "LangGraph",
                ),
            ]
            for question, expected_route, expected_text in cases:
                result = agent.ask(question)
                self.assertEqual(result.get("route"), expected_route, question)
                self.assertTrue(str(result.get("answer") or "").strip(), question)
                if expected_text:
                    self.assertIn(expected_text, str(result.get("answer")), question)
                self.assertIn("run_id", result, question)
                self.assertIsNotNone(agent.get_run(result["run_id"]), question)

            missing = agent.ask("分析一下这个数据")
            self.assertEqual(missing.get("route"), "need_more_info")

    def test_weather_tools_and_error_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(**{**settings_for(Path(raw)).__dict__, "default_location": "上海"})
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([DefaultAwareWeatherTool()]),
            )
            explicit = agent.ask("看下明天上海的天气")
            self.assertIn(explicit["route"], {"capability", "rules"})
            self.assertIn("上海明天", explicit["answer"])

            defaulted = agent.ask("看下明天的天气", context={"default_location": "上海"})
            self.assertIn(defaulted["route"], {"capability", "rules"})
            self.assertIn("上海明天", defaulted["answer"])

            failing = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FailingWeatherTool()]),
            )
            failed = failing.ask("看下明天上海的天气")
            self.assertNotIn("晴朗", str(failed.get("answer")))
            self.assertIn("tool_error_not_hidden", failed["evaluation"]["passed_checks"])

    def test_nba_question_does_not_match_weather_or_date_rule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FakeWeatherTool(), FakeWebSearchTool()]),
            )
            result = agent.ask("明天NBA有哪些比赛？")
            self.assertNotEqual(result.get("route"), "rules")
            self.assertFalse(
                any(item.get("name") == "通用日期推算规则" for item in result.get("matched_rules", []))
            )

    def test_domain_knowledge_question_uses_model_fallback_not_personal_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=DomainKnowledgeModel())
            result = agent.ask("你觉得FTC 料箱酷补货的重点是什么")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("料箱补货", result["answer"])
            self.assertIn("库存准确", result["answer"])
            self.assertNotIn("拜访目标", result["answer"])
            self.assertGreaterEqual(agent.chat_model.generate_calls, 1)

    def test_domain_knowledge_question_has_local_fallback_when_model_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=DomainFailingModel())
            result = agent.ask("你觉得FTC 料箱酷补货的重点是什么")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("补货触发", result["answer"])
            self.assertIn("系统协同", result["answer"])
            self.assertNotIn("拜访目标", result["answer"])

    def test_opinion_question_uses_model_fallback_not_personal_template_or_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=OvertimeOpinionModel())
            result = agent.ask("你怎么看团队长期加班")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("长期加班", result["answer"])
            self.assertIn("管理信号", result["answer"])
            self.assertNotIn("拜访目标", result["answer"])
            self.assertNotIn("会议目标", result["answer"])
            self.assertIn("explore_capabilities_skipped", result["execution_path"])
            self.assertEqual(result["routing_policy"]["tool_exploration_skipped"], True)

    def test_opinion_question_has_local_fallback_when_model_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=OvertimeFailingModel())
            result = agent.ask("你怎么看团队长期加班")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("长期加班", result["answer"])
            self.assertIn("资源配置", result["answer"])
            self.assertNotIn("拜访目标", result["answer"])

    def test_yaml_and_agent_skills_product_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            settings.skills_dir.joinpath("weekly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_weekly",
                        "name": "周报写作 Skill",
                        "description": "写周报结构",
                        "task_types": ["report_writing"],
                        "keywords": ["周报", "报告"],
                        "priority": 80,
                        "status": "active",
                        "prompt": "输出本周进展、风险、下周计划。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            yaml_result = agent.ask("帮我写一个周报结构")
            self.assertIn(yaml_result["route"], {"skills", "rules"})
            self.assertNotEqual(yaml_result["route"], "need_more_info")

            source = write_agent_skill(
                tmp / "source",
                "browser-testing",
                "Use when asked to create browser automation or pytest web tests.",
                "Always create a browser test plan before implementation.",
            )
            agent.import_agent_skill(str(source))
            agent_result = agent.ask("帮我创建 browser automation pytest 测试方案")
            self.assertEqual(agent_result["route"], "skills")
            self.assertEqual(agent_result["matched_skills"][0]["skill_kind"], "agent")

    def test_agent_skill_script_confirmation_execution_and_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "execute-skill",
                "Use when asked to execute script skill tasks.",
            )
            scripts = source / "scripts"
            scripts.mkdir()
            scripts.joinpath("run.py").write_text(
                (
                    "import json, os, sys\n"
                    "from pathlib import Path\n"
                    "payload = json.loads(sys.stdin.read())\n"
                    "Path(os.environ['MONKEY_AGENT_ARTIFACTS_DIR']).joinpath('result.txt').write_text(payload['question'])\n"
                    "print('ran:' + payload['question'])\n"
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))

            pending = agent.ask("请执行 script skill tasks")
            self.assertTrue(pending["requires_confirmation"])

            executed = agent.ask(
                "请执行 script skill tasks",
                context={"confirm_skill_execution": True},
            )
            self.assertTrue(executed["agent_skill_runtime"]["execution"]["success"])

            bad_source = write_agent_skill(
                tmp / "bad-source",
                "unsafe-skill",
                "Use when asked to execute unsafe script skill tasks.",
            )
            bad_scripts = bad_source / "scripts"
            bad_scripts.mkdir()
            bad_scripts.joinpath("bad.py").write_text("import os\nos.remove('x')\n", encoding="utf-8")
            agent.import_agent_skill(str(bad_source))
            rejected = agent.run_agent_skill("unsafe-skill", "scripts/bad.py", confirm=True)
            self.assertFalse(rejected["success"])
            self.assertEqual(rejected["error"], "unsafe_skill_script")

    def test_self_learning_adopt_and_reject_natural_language(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            first = agent.submit_feedback("输出格式", "以后默认用表格输出，这是我的偏好。")
            adopted = agent.ask("记住这个")
            self.assertEqual(adopted.get("adopted_candidate_id"), first)
            self.assertIsNone(agent.inspect_pending(first))

            second = agent.submit_feedback("错误规则", "这个规则不对，应该作为反例。")
            rejected = agent.ask("不要沉淀")
            self.assertEqual(rejected.get("rejected_candidate_id"), second)
            self.assertIsNone(agent.inspect_pending(second))

            regular = agent.ask("水为什么会结冰")
            self.assertFalse(regular.get("learning_candidate_id"))

    def test_goal_engine_trace_and_confirmation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal("我作为销售明天拜访甲方，帮我准备行动方案", max_steps=1)
            self.assertIn("run_id", started)
            self.assertTrue(started["tasks"])
            stepped = agent.step_goal(started["goal_id"])
            self.assertTrue(stepped["events"])
            self.assertTrue(stepped["evaluations"])
            self.assertIsNotNone(agent.get_run(started["run_id"]))

            write_agent = MonkeyAgent(
                settings=settings_for(_prepared_dir(Path(raw) / "write")),
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            write_started = write_agent.start_goal(
                "帮我接入飞书机器人，支持给指定群发送消息，并沉淀成可复用能力。",
                max_steps=5,
            )
            waiting = write_agent.step_goal(write_started["goal_id"])
            self.assertEqual(waiting["status"], "waiting_human")
            self.assertTrue(waiting["requires_confirmation"])
            confirmed = write_agent.step_goal(write_started["goal_id"], confirm=True)
            self.assertEqual(confirmed["status"], "completed")

    def test_run_trace_and_diagnose_product_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("1+1等于几")
            latest = agent.latest_run("ask")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["id"], result["run_id"])
            diagnosis = diagnose_run(latest)
            formatted = format_diagnosis(diagnosis)
            self.assertIn("Run:", formatted)
            self.assertIn("路由:", formatted)

    def test_cli_setup_location_and_ask_modes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            tmp.joinpath(".env").write_text("DASHSCOPE_API_KEY=old\n", encoding="utf-8")
            with patch("pathlib.Path.cwd", return_value=tmp):
                output = StringIO()
                with redirect_stdout(output):
                    cli_main(["setup", "location", "--location", "上海"])
            content = tmp.joinpath(".env").read_text(encoding="utf-8")
            self.assertIn("DASHSCOPE_API_KEY=old", content)
            self.assertIn("MONKEY_AGENT_DEFAULT_LOCATION=上海", content)

            settings = settings_for(_prepared_dir(tmp / "ask"))
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            ask_result = agent.ask("1+1等于几")
            self.assertEqual(ask_result["route"], "rules")

    def test_telegram_product_commands_and_access_control(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            setup_client = FakeTelegramClient()
            setup_handler = TelegramMessageHandler(
                settings,
                lambda question, context: {"answer": "should not call"},
                setup_client,
            )
            whoami = setup_handler.handle_update(_telegram_update("/whoami", chat_id=123))
            self.assertEqual(whoami["status"], "replied")
            blocked = setup_handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertEqual(blocked["status"], "setup_required")

            allowed_settings = Settings(
                **{
                    **settings.__dict__,
                    "telegram_bot_token": "token",
                    "telegram_allowed_chat_ids": ["123"],
                    "default_location": "上海",
                }
            )
            client = FakeTelegramClient()
            handler = TelegramMessageHandler(
                allowed_settings,
                lambda question, context: {
                    "answer": "答案是 2",
                    "route": "rules",
                    "run_id": "run_1",
                    "confidence": 0.95,
                    "evaluation": {"status": "pass"},
                },
                client,
                status_provider=lambda: {
                    "id": "run_1",
                    "type": "ask",
                    "status": "completed",
                    "input": {"question": "1+1等于几"},
                    "route": "rules",
                    "answer_preview": "答案是 2",
                    "timings": [{"node": "execute_rules", "ms": 1}],
                },
            )
            handler.handle_update(_telegram_update("/help", chat_id=123))
            self.assertIn("日常问答", client.sent[-1]["text"])
            handler.handle_update(_telegram_update("/settings", chat_id=123))
            self.assertIn("默认地点: 上海", client.sent[-1]["text"])
            handler.handle_update(_telegram_update("/status", chat_id=123))
            self.assertIn("最近 run_id: run_1", client.sent[-1]["text"])
            handler.handle_update(_telegram_update("/trace on", chat_id=123))
            handler.handle_update(_telegram_update("1+1等于几", chat_id=123))
            self.assertIn("route: rules", client.sent[-1]["text"])
            non_text = handler.handle_update(
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
            self.assertEqual(non_text["reason"], "non_text_message")


class DefaultAwareWeatherTool:
    id = "default_aware_weather"
    name = "Default Aware Weather"
    description = "Fake weather tool that uses default location from context."

    def can_handle(self, question, context):
        return "天气" in question

    def execute(self, question, context):
        location = "上海" if "上海" in question else str(context.get("default_location") or "未知")
        day = "明天" if "明天" in question else "当前"
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=True,
            content=f"{location}{day}天气：晴朗，气温 22°C。",
            data={"location": location, "date_label": day, "temperature": 22},
            handler_name="weather_query",
            handler_code_proposal="def weather_query(rule, question, context): pass",
        )


class DomainKnowledgeModel(LocalHeuristicModel):
    def __init__(self) -> None:
        self.generate_calls = 0

    def classify_question(self, question, context):
        return {
            "deterministic": [],
            "semi_deterministic": ["True"],
            "uncertain": ["True"],
            "intents": ["planning_advice"],
            "required_tools": [],
            "task_type": "advisory",
            "confidence": 0.85,
            "clarification_questions": [],
        }

    def generate(self, question, deterministic_results, skills, context):
        self.generate_calls += 1
        return "FTC 料箱补货的重点是库存准确、触发及时、路径高效、异常闭环。"


class DomainFailingModel(DomainKnowledgeModel):
    def generate(self, question, deterministic_results, skills, context):
        self.generate_calls += 1
        raise RuntimeError("model unavailable")


class OvertimeOpinionModel(DomainKnowledgeModel):
    def classify_question(self, question, context):
        return {
            "deterministic": [],
            "semi_deterministic": ["True"],
            "uncertain": ["True"],
            "intents": ["planning_advice", "personal_advice"],
            "required_tools": [],
            "task_type": "advisory",
            "confidence": 0.85,
            "clarification_questions": [],
        }

    def generate(self, question, deterministic_results, skills, context):
        self.generate_calls += 1
        return "团队长期加班是管理信号，需要看目标、资源配置、排期和健康边界。"


class OvertimeFailingModel(OvertimeOpinionModel):
    def generate(self, question, deterministic_results, skills, context):
        self.generate_calls += 1
        raise RuntimeError("model unavailable")


def _prepared_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class FakeWebSearchTool:
    id = "fake_web_search"
    name = "Fake Web Search"
    description = "Fake product regression search tool."

    def can_handle(self, question, context):
        return "NBA" in question or "比赛" in question or "搜索" in question

    def execute(self, question, context):
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=False,
            candidate_type="skill",
            content="已搜索到公开资料。",
            data={"results": [{"title": "NBA schedule", "url": "https://example.com"}]},
            public_evidence=[{"title": "NBA schedule", "url": "https://example.com"}],
        )


if __name__ == "__main__":
    unittest.main()

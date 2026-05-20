from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
import shutil
from pathlib import Path

import yaml

from monkey_agent.domains.tools.capability import CapabilityRegistry, ToolResult
from monkey_agent.app.monkey_agent import MonkeyAgent
from monkey_agent.domains.integrations.feishu import FeishuEventHandler
from monkey_agent.domains.integrations.feishu.security import FeishuSecurityError
from monkey_agent.domains.tools.builtin.weather import _location_candidates
from monkey_agent.core.config import Settings
from monkey_agent.domains.goals.models import GoalTask
from monkey_agent.domains.models.bailian import BailianChatModel, LocalHeuristicModel
from monkey_agent.domains.evaluation import AskEvaluator
from monkey_agent.workflows.goal.planner import CompositeGoalPlanner


def write_agent_skill(root: Path, name: str, description: str, body: str = "Follow these instructions.") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "license: MIT\n"
            "metadata:\n"
            "  version: \"1.0\"\n"
            "---\n"
            f"# {name}\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )
    return skill_dir


def settings_for(tmp: Path) -> Settings:
    rules = tmp / "rules"
    skills = tmp / "skills"
    memory = tmp / "memory"
    counterexamples = tmp / "counterexamples"
    pending = tmp / "pending"
    generated_tools = tmp / "generated_tools"
    generated_registry = tmp / "generated_tools.yaml"
    runtime = tmp / "runtime"
    rules.mkdir()
    skills.mkdir()
    memory.mkdir()
    counterexamples.mkdir()
    return Settings(
        model_provider="bailian",
        bailian_region="beijing",
        bailian_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dashscope_api_key="",
        chat_model="qwen-plus",
        classifier_model="qwen-plus",
        reasoning_model="qwen-plus",
        tool_builder_model="qwen-plus",
        evaluator_model="qwen-plus",
        model_temperature=0.2,
        classifier_temperature=0.0,
        reasoning_temperature=0.2,
        tool_builder_temperature=0.1,
        evaluator_temperature=0.0,
        rules_dir=rules,
        skills_dir=skills,
        memory_dir=memory,
        counterexamples_dir=counterexamples,
        pending_review_dir=pending,
        generated_tools_dir=generated_tools,
        generated_tools_registry=generated_registry,
        runtime_dir=runtime,
        learning_repeat_threshold=2,
        feishu_app_id="",
        feishu_app_secret="",
        feishu_verification_token="",
        feishu_encrypt_key="",
        feishu_base_url="https://open.feishu.cn/open-apis",
        feishu_allowed_users=[],
        feishu_allowed_chats=[],
        feishu_default_user_prefix="feishu",
    )


def write_basic_rules(rules_dir: Path) -> None:
    for item in [
        {
            "id": "rule_basic_arithmetic",
            "type": "formula",
            "name": "通用四则运算规则",
            "intent": ["calculation"],
            "keywords": ["+", "-", "*", "/", "×", "÷", "等于几", "帮我算", "计算"],
            "priority": 80,
            "status": "active",
            "handler": "arithmetic_formula",
            "rule": "安全四则运算。",
        },
        {
            "id": "rule_basic_date_calculation",
            "type": "date",
            "name": "通用日期推算规则",
            "intent": ["date_calculation"],
            "keywords": ["今天", "明天", "后天", "昨天", "下周", "天后", "相差几天", "多少天"],
            "priority": 80,
            "status": "active",
            "handler": "date_calculation",
            "rule": "常见日期推算。",
        },
        {
            "id": "rule_basic_unit_conversion",
            "type": "unit_conversion",
            "name": "通用单位换算规则",
            "intent": ["unit_conversion"],
            "keywords": ["换算", "转换", "等于多少", "公里", "千米", "米", "千克", "公斤", "克", "摄氏", "华氏"],
            "priority": 80,
            "status": "active",
            "handler": "unit_conversion",
            "rule": "常见单位换算。",
        },
    ]:
        rules_dir.joinpath(f"{item['id']}.yaml").write_text(
            yaml.safe_dump(item, allow_unicode=True),
            encoding="utf-8",
        )


class MonkeyAgentRulesFirstTest(unittest.TestCase):
    def test_rules_take_priority_over_skills(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            (settings.rules_dir / "percentage.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "rule_percentage_formula",
                        "type": "formula",
                        "name": "通用百分比计算规则",
                        "intent": ["calculation"],
                        "keywords": ["百分比", "完成率", "总数"],
                        "priority": 100,
                        "status": "active",
                        "handler": "percentage_formula",
                        "rule": "百分比 = 分子 / 分母 * 100%",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            (settings.skills_dir / "percentage_skill.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_percentage",
                        "name": "百分比解释 Skill",
                        "description": "fallback",
                        "task_types": ["calculation"],
                        "keywords": ["百分比"],
                        "priority": 60,
                        "status": "active",
                        "prompt": "use skill",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask(
                "已完成10，总数200，完成率百分比是多少？",
                context={"numerator": 10, "denominator": 200},
            )
            self.assertEqual(result["route"], "rules")
            self.assertEqual(result["matched_skills"], [])
            self.assertEqual(result["deterministic_results"][0]["value"], "5.00%")

    def test_basic_arithmetic_rule_handles_simple_expression(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("1+1等于几")
            self.assertEqual(result["route"], "rules")
            self.assertEqual(result["deterministic_results"][0]["rule_id"], "rule_basic_arithmetic")
            self.assertEqual(result["deterministic_results"][0]["value"], "2")
            self.assertNotIn("need_more_info", result["execution_path"])

    def test_basic_arithmetic_rule_handles_parentheses_safely(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我算一下 (2+3)*4")
            self.assertEqual(result["route"], "rules")
            self.assertEqual(result["deterministic_results"][0]["value"], "20")

    def test_basic_arithmetic_rejects_unsafe_expression(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我算一下 __import__('os').system('echo bad') + 1")
            self.assertEqual(result.get("route"), "rules")
            self.assertTrue(result["deterministic_results"][0]["requires_more_info"])
            self.assertIn("不支持或不安全", result["deterministic_results"][0]["content"])

    def test_basic_date_rule_handles_relative_and_diff(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            tomorrow = agent.ask("明天是几号", context={"today": "2026-05-19"})
            self.assertEqual(tomorrow["route"], "rules")
            self.assertEqual(tomorrow["deterministic_results"][0]["value"], "2026-05-20")
            diff = agent.ask("2026-05-19到2026-06-01相差几天")
            self.assertEqual(diff["deterministic_results"][0]["value"], "13天")

    def test_basic_unit_conversion_rule_handles_common_units(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            length = agent.ask("1公里等于多少米")
            self.assertEqual(length["route"], "rules")
            self.assertEqual(length["deterministic_results"][0]["value"], "1000米")
            temperature = agent.ask("摄氏30度是多少华氏度")
            self.assertEqual(temperature["deterministic_results"][0]["value"], "86华氏度")

    def test_general_knowledge_uses_reasoning_not_clarification_template(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("水为什么会结冰")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("水结冰", result["answer"])
            self.assertNotIn("字段定义", result["answer"])
            self.assertIsNone(result.get("learning_candidate_id"))

    def test_general_knowledge_difference_question_does_not_create_rule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("Python和Java有什么区别")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("Python", result["answer"])
            self.assertEqual(agent.list_pending(), [])

    def test_general_knowledge_what_is_question_avoids_need_more_info(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("什么是LangGraph")
            self.assertEqual(result["route"], "general_reason")
            self.assertNotIn("need_more_info", result["execution_path"])
            self.assertFalse(result["routing_policy"]["clarification_allowed"])
            self.assertEqual(result["routing_policy"]["category"], "general_knowledge")

    def test_business_missing_context_still_allows_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("分析一下这个数据")
            self.assertEqual(result["route"], "need_more_info")
            self.assertTrue(result["routing_policy"]["clarification_allowed"])
            self.assertEqual(result["routing_policy"]["category"], "business_missing_context")

    def test_route_policy_is_written_to_run_trace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            write_basic_rules(settings.rules_dir)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("1+1等于几")
            record = agent.get_run(result["run_id"])
            self.assertEqual(record["routing_policy"]["category"], "deterministic_basic")
            self.assertEqual(record["routing_policy"]["final_route"], result["routing_policy"]["final_route"])

    def test_skills_run_when_no_rules_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            (settings.skills_dir / "monthly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_monthly",
                        "name": "报告写作 Skill",
                        "description": "monthly",
                        "task_types": ["report_writing"],
                        "keywords": ["月报", "周报", "总结"],
                        "priority": 60,
                        "status": "active",
                        "prompt": "按月报结构分析",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我做一份项目月报")
            self.assertEqual(result["route"], "skills")
            self.assertEqual(result["matched_rules"], [])
            self.assertEqual(result["matched_skills"][0]["id"], "skill_monthly")

    def test_agent_skill_imports_and_matches_question(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "browser-testing",
                "Use when asked to create browser automation or pytest web tests.",
                "Always create a browser test plan before implementation.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            installed = agent.import_agent_skill(str(source))
            self.assertEqual(installed["id"], "browser-testing")
            self.assertTrue(
                (settings.runtime_dir / "personal" / "agent_skills" / "browser-testing" / "SKILL.md").exists()
            )
            self.assertEqual(len(agent.list_skills(skill_type="agent")), 1)

            result = agent.ask("帮我创建 browser automation pytest 测试方案")
            self.assertEqual(result["route"], "skills")
            self.assertEqual(result["matched_skills"][0]["id"], "browser-testing")
            self.assertEqual(result["matched_skills"][0]["skill_kind"], "agent")
            self.assertIn("Always create a browser test plan", result["matched_skills"][0]["prompt"])

    def test_agent_skill_install_from_github_style_source_uses_git_clone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            repo = tmp / "repo"
            write_agent_skill(
                repo / "skills",
                "github-skill",
                "Use when asked about GitHub style installed skills.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())

            def fake_clone(repo_url: str, target: Path) -> None:
                self.assertEqual(repo_url, "https://github.com/owner/repo.git")
                shutil.copytree(repo, target)

            with patch("monkey_agent.domains.agent_skills.installer._git_clone", fake_clone):
                installed = agent.install_agent_skill("owner/repo/github-skill")

            self.assertEqual(installed["id"], "github-skill")
            self.assertEqual(len(agent.list_agent_skills()), 1)
            self.assertIn("github-skill", agent.inspect_agent_skill("github-skill")["body"])

    def test_agent_skill_duplicate_install_updates_registry_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "repeat-skill",
                "Use when asked about repeatable skills.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            source.joinpath("SKILL.md").write_text(
                source.joinpath("SKILL.md")
                .read_text(encoding="utf-8")
                .replace("repeatable skills", "updated repeatable skills"),
                encoding="utf-8",
            )
            agent.import_agent_skill(str(source))
            skills = agent.list_agent_skills()
            self.assertEqual(len(skills), 1)
            self.assertIn("updated", skills[0]["description"])

    def test_agent_skill_disable_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            source = write_agent_skill(
                tmp / "source",
                "toggle-skill",
                "Use when asked about toggle skill matching.",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            agent.import_agent_skill(str(source))
            agent.disable_agent_skill("toggle-skill")
            result = agent.ask("toggle skill matching 怎么处理？")
            self.assertFalse(
                any(item.get("id") == "toggle-skill" for item in result.get("matched_skills", []))
            )
            agent.enable_agent_skill("toggle-skill")
            result = agent.ask("toggle skill matching 怎么处理？")
            self.assertTrue(
                any(item.get("id") == "toggle-skill" for item in result.get("matched_skills", []))
            )
            removed = agent.remove_agent_skill("toggle-skill")
            self.assertEqual(removed["id"], "toggle-skill")
            self.assertFalse((settings.runtime_dir / "personal" / "agent_skills" / "toggle-skill").exists())

    def test_agent_skill_import_rejects_invalid_or_unsafe_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            settings = settings_for(tmp)
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())

            missing = tmp / "missing-skill"
            missing.mkdir()
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(missing))

            bad_name = tmp / "BadName"
            bad_name.mkdir()
            bad_name.joinpath("SKILL.md").write_text(
                "---\nname: BadName\ndescription: bad\n---\nBody\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(bad_name))

            long_desc = tmp / "long-desc"
            long_desc.mkdir()
            long_desc.joinpath("SKILL.md").write_text(
                "---\nname: long-desc\ndescription: " + ("x" * 1025) + "\n---\nBody\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(long_desc))

            linked = write_agent_skill(
                tmp / "source",
                "linked-skill",
                "Use when asked about symlink safety.",
            )
            linked.joinpath("escape").symlink_to(tmp / "outside")
            with self.assertRaises(ValueError):
                agent.import_agent_skill(str(linked))

    def test_need_more_info_when_no_rules_or_skills(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我判断一下这个问题")
            self.assertEqual(result["route"], "need_more_info")
            self.assertTrue(result["clarification_questions"])
            self.assertTrue(result["uncertain_content"])
            self.assertIn("explore_learn", result["execution_path"])
            self.assertIsNone(result["learning_candidate_id"])
            self.assertEqual(result["exploration"]["learning_policy"], "one_off_observation_only")

    def test_personal_assistant_sales_question_answers_directly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("我作为一个乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？")
            self.assertEqual(result["route"], "general_reason")
            self.assertIn("拜访目标", result["answer"])
            self.assertIn("提问清单", result["answer"])
            self.assertIn("general_reason", result["execution_path"])
            self.assertNotIn("need_more_info", result["execution_path"])
            self.assertIsNone(result.get("learning_candidate_id"))
            self.assertEqual(agent.review_store.list_pending(), [])

    def test_personal_assistant_skill_generates_real_advice(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.skills_dir.joinpath("personal_assistant.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_personal_assistant_advice",
                        "name": "通用个人助理建议 Skill",
                        "description": "personal assistant",
                        "task_types": ["sales_support", "meeting_preparation"],
                        "keywords": ["拜访", "销售", "甲方", "会议"],
                        "priority": 70,
                        "status": "active",
                        "prompt": "先给可执行建议，再提出必要澄清。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("我作为销售明天拜访甲方，应该准备什么？")
            self.assertEqual(result["route"], "skills")
            self.assertEqual(result["matched_skills"][0]["id"], "skill_personal_assistant_advice")
            self.assertIn("拜访目标", result["answer"])
            self.assertIn("下一步", result["answer"])

    def test_reasoning_model_failure_falls_back_for_personal_advice(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.skills_dir.joinpath("personal_assistant.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_personal_assistant_advice",
                        "name": "通用个人助理建议 Skill",
                        "description": "personal assistant",
                        "task_types": ["sales_support"],
                        "keywords": ["拜访", "销售", "甲方"],
                        "priority": 70,
                        "status": "active",
                        "prompt": "先给可执行建议，再提出必要澄清。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=FailingReasonModel())
            result = agent.ask("我作为销售明天拜访甲方，应该准备什么？")
            self.assertEqual(result["route"], "skills")
            self.assertIn("拜访目标", result["answer"])
            self.assertTrue(any("model_generate_failed" in item for item in result["errors"]))

    def test_dynamic_clarification_questions_for_sales_support(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.nodes.need_more_info(
                {
                    "question": "销售拜访准备",
                    "task_type": "sales_support",
                    "execution_path": [],
                }
            )
            self.assertIn("甲方", result["clarification_questions"][0])
            self.assertNotIn("字段定义", result["answer"])

    def test_feedback_creates_pending_candidate_and_approve_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            candidate_id = agent.submit_feedback(
                "完成率怎么算？",
                "完成率公式必须使用已完成数量除以总数量。",
            )
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["id"], candidate_id)
            promoted = agent.review_store.approve(candidate_id)
            self.assertTrue(promoted.exists())
            result = agent.ask("完成率公式是什么？")
            self.assertEqual(result["route"], "rules")

    def test_feedback_can_create_memory_and_counterexample_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            memory_id = agent.submit_feedback("输出格式", "以后默认用表格输出，这是我的偏好。")
            counter_id = agent.submit_feedback("错误回答", "这个回答是错误案例，不应该忽略总数量。")
            pending = {item["id"]: item for item in agent.review_store.list_pending()}
            self.assertEqual(pending[memory_id]["candidate_type"], "memory")
            self.assertEqual(pending[counter_id]["candidate_type"], "counterexample")

    def test_unknown_weather_query_deposits_pending_api_rule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("今天上海天气怎么样？")
            self.assertEqual(result["route"], "tool_builder")
            self.assertIn("register_generated_tool", result["execution_path"])
            self.assertEqual(result["exploration"]["candidate_type"], "rule")
            self.assertIsNotNone(result["learning_candidate_id"])
            self.assertTrue(agent.list_generated_tools()[0]["auto_enabled"])
            self.assertEqual(agent.review_store.list_pending()[0]["candidate_type"], "rule")

    def test_generated_tool_is_reused_after_first_build(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            agent.ask("今天上海天气怎么样？")
            result = agent.ask("明天上海天气怎么样？")
            self.assertEqual(result["route"], "capability")
            self.assertNotIn("discover_tool_spec", result["execution_path"])
            self.assertEqual(result["exploration"]["tool_id"], agent.list_generated_tools()[0]["id"])

    def test_weather_generated_tool_uses_generalized_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            first = agent.ask("今天上海天气怎么样？")
            self.assertEqual(first["route"], "tool_builder")
            generated = agent.list_generated_tools()[0]
            self.assertIn("天气", generated["keywords"])
            self.assertNotIn("今天上海天气怎么样", generated["keywords"])

            second = agent.ask("明天合肥天气怎么样？")
            self.assertEqual(second["route"], "capability")
            self.assertEqual(second["exploration"]["tool_id"], generated["id"])
            self.assertNotIn("discover_tool_spec", second["execution_path"])

    def test_personal_advice_does_not_trigger_tool_builder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？")
            self.assertEqual(result["route"], "general_reason")
            self.assertNotIn("draft_tool_code", result["execution_path"])
            self.assertFalse(result.get("tool_builder", {}).get("spec"))

    def test_existing_capability_solves_then_deposits_rule_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FakeWeatherTool()]),
            )
            result = agent.ask("今天上海天气怎么样？")
            self.assertEqual(result["route"], "capability")
            self.assertEqual(result["exploration"]["success"], True)
            self.assertIn("晴朗", result["answer"])
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["stability_decision"], "llm_drafted_rule_candidate")
            self.assertEqual(pending[0]["source_tool"], "fake_weather")
            self.assertIn("llm_draft", pending[0])

    def test_adopted_capability_rule_executes_before_capability_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            registry = CapabilityRegistry([FakeWeatherTool()])
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=registry,
            )
            first = agent.ask("今天上海天气怎么样？")
            candidate_id = first["learning_candidate_id"]
            agent.adopt(str(candidate_id))

            second = agent.ask("今天上海天气怎么样？")
            self.assertEqual(second["route"], "rules")
            self.assertIn("execute_rules", second["execution_path"])
            self.assertNotIn("explore_capabilities", second["execution_path"])
            self.assertEqual(second["matched_rules"][0]["handler"], "capability_tool")
            self.assertIn("晴朗", second["answer"])

    def test_adopted_weather_rule_generalizes_city_and_date(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            registry = CapabilityRegistry([FakeWeatherTool()])
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=registry,
            )
            first = agent.ask("今天上海天气怎么样？")
            agent.adopt(str(first["learning_candidate_id"]))

            rules = [rule.to_dict() for rule in agent.rules.list()]
            weather_rule = [rule for rule in rules if rule["source_tool"] == "fake_weather"][0]
            self.assertNotIn("上海", weather_rule["keywords"])
            self.assertIn("天气", weather_rule["keywords"])

            hefei = agent.ask("今天合肥天气怎么样？")
            tomorrow = agent.ask("明天上海天气怎么样？")
            self.assertEqual(hefei["route"], "rules")
            self.assertEqual(tomorrow["route"], "rules")
            self.assertNotIn("explore_capabilities", hefei["execution_path"])
            self.assertNotIn("explore_capabilities", tomorrow["execution_path"])
            self.assertIn("合肥", hefei["answer"])
            self.assertIn("明天", tomorrow["answer"])

    def test_weather_location_candidates_include_hefei_aliases(self) -> None:
        candidates = _location_candidates("合肥")
        self.assertIn("合肥市", candidates)
        self.assertIn("安徽省合肥市", candidates)
        self.assertIn("Hefei", candidates)

    def test_weather_rule_does_not_match_non_weather_tomorrow_question(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            registry = CapabilityRegistry([FakeWeatherTool(), FakeWebSearchTool()])
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=registry,
            )
            first = agent.ask("今天上海天气怎么样？")
            agent.adopt(str(first["learning_candidate_id"]))

            result = agent.ask("明天NBA有哪些比赛？")
            self.assertNotEqual(result["route"], "rules")
            self.assertEqual(result["matched_rules"], [])
            self.assertIn("explore_capabilities", result["execution_path"])

    def test_sports_schedule_question_uses_web_search_not_weather(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            registry = CapabilityRegistry([FakeWeatherTool(), FakeWebSearchTool()])
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=registry,
            )
            first = agent.ask("今天上海天气怎么样？")
            agent.adopt(str(first["learning_candidate_id"]))

            result = agent.ask("明天NBA有哪些比赛？")
            self.assertEqual(result["route"], "capability")
            self.assertEqual(result["exploration"]["tool_id"], "fake_web_search")
            self.assertEqual(result["matched_rules"], [])

    def test_classification_contains_merged_llm_keyword_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("明天NBA有哪些比赛？")
            self.assertEqual(result["task_type"], "sports_query")
            self.assertIn("sports_query", result["intent_keywords"])
            self.assertIn("classification", result)
            self.assertIn("keyword", result["classification"])
            self.assertIn("llm", result["classification"])
            self.assertIn("merged", result["classification"])
            self.assertIn("public_web_search", result["required_tools"])

    def test_memory_preferences_are_used_in_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.memory_dir.joinpath("memory_table.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "memory_table",
                        "status": "active",
                        "keywords": ["月报"],
                        "preference": "以后默认用表格输出",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            settings.skills_dir.joinpath("monthly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_monthly",
                        "name": "月报 Skill",
                        "description": "monthly",
                        "task_types": ["general"],
                        "keywords": ["月报"],
                        "priority": 50,
                        "status": "active",
                        "prompt": "生成月报",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我写月报")
            self.assertTrue(result["memory_used"])
            self.assertIn("| 项目 | 内容 |", result["answer"])

    def test_counterexamples_lower_confidence_when_bad_pattern_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.counterexamples_dir.joinpath("counter_bad.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "counter_bad",
                        "status": "active",
                        "keywords": ["月报"],
                        "bad_pattern": "已按 Skills 执行",
                        "correction": "不要只说执行了 Skill，要输出实际内容。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            settings.skills_dir.joinpath("monthly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_monthly",
                        "name": "月报 Skill",
                        "description": "monthly",
                        "task_types": ["general"],
                        "keywords": ["月报"],
                        "priority": 50,
                        "status": "active",
                        "prompt": "生成月报",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我写月报")
            self.assertTrue(result["counterexamples_checked"])
            self.assertLessEqual(result["confidence"], 0.5)
            self.assertTrue(any("counterexample_triggered" in item for item in result["errors"]))

    def test_counterexample_hits_are_exposed_in_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.counterexamples_dir.joinpath("counter_bad.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "counter_bad",
                        "status": "active",
                        "keywords": ["月报"],
                        "bad_pattern": "已按 Skills 执行",
                        "correction": "不要只说执行了 Skill，要输出实际内容。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            settings.skills_dir.joinpath("monthly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_monthly",
                        "name": "月报 Skill",
                        "description": "monthly",
                        "task_types": ["general"],
                        "keywords": ["月报"],
                        "priority": 50,
                        "status": "active",
                        "prompt": "生成月报",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我写月报")
            self.assertEqual(result["evaluation"]["status"], "needs_revision")
            self.assertEqual(result["evaluation"]["counterexample_hits"][0]["id"], "counter_bad")
            self.assertIn("counterexample_not_repeated", result["evaluation"]["failed_checks"])

    def test_tool_registry_exposes_schema_permission_and_risk(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            tools = {item["id"]: item for item in agent.list_capabilities()}
            self.assertEqual(tools["open_meteo_weather"]["permission"], "auto")
            self.assertEqual(tools["feishu_send_message"]["permission"], "confirm")
            self.assertEqual(tools["feishu_send_message"]["risk"], "medium")
            self.assertIn("input_schema", tools["public_web_search"])

    def test_affirmative_reply_adopts_latest_pending_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            registry = CapabilityRegistry([FakeWeatherTool()])
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=registry,
            )
            first = agent.ask("今天上海天气怎么样？")
            candidate_id = first["learning_candidate_id"]
            self.assertIn(str(candidate_id), first["adoption_prompt"])

            adopted = agent.ask("同意沉淀")
            self.assertEqual(adopted["adopted_candidate_id"], candidate_id)
            self.assertIn("已沉淀候选", adopted["answer"])
            self.assertEqual(agent.review_store.list_pending(), [])

    def test_learning_request_does_not_accidentally_adopt_latest_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            candidate_id = agent.submit_feedback("旧问题", "以后默认用表格输出")
            result = agent.ask("帮我生成一个查询汇率的只读工具，以后可以复用")
            self.assertNotEqual(result.get("route"), "adopted")
            self.assertIsNone(result.get("adopted_candidate_id"))
            self.assertTrue(any(item["id"] == candidate_id for item in agent.list_pending()))

    def test_tool_builder_falls_back_when_model_returns_no_code(self) -> None:
        class MissingCodeToolBuilderModel(LocalHeuristicModel):
            def draft_tool_builder(self, question, spec, evidence, context):
                return {
                    "tool_id": spec["tool_id"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "kind": spec["kind"],
                    "permission": spec["permission"],
                    "risk": spec["risk"],
                    "read_only": spec["read_only"],
                    "learn_policy": "rule",
                    "keywords": spec["keywords"],
                    "class_name": "GeneratedTool",
                }

        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=MissingCodeToolBuilderModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询汇率的只读工具，以后可以复用")
            self.assertEqual(result["route"], "tool_builder")
            self.assertTrue(result["tool_builder"]["success"])
            self.assertEqual(
                result["tool_builder"]["draft"]["draft_fallback_reason"],
                "model_missing_code",
            )
            self.assertTrue(agent.list_generated_tools())

    def test_tool_builder_falls_back_when_model_call_fails(self) -> None:
        class RaisingToolBuilderModel(LocalHeuristicModel):
            def draft_tool_builder(self, question, spec, evidence, context):
                raise RuntimeError("model offline")

        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=RaisingToolBuilderModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询汇率的只读工具，以后可以复用")
            self.assertEqual(result["route"], "tool_builder")
            self.assertTrue(result["tool_builder"]["success"])
            self.assertIn(
                "model_error",
                result["tool_builder"]["draft"]["draft_fallback_reason"],
            )

    def test_existing_capability_failure_is_not_overwritten_by_generic_exploration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FailingWeatherTool()]),
            )
            result = agent.ask("今天上海天气怎么样？")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["exploration"]["tool_id"], "failing_weather")
            self.assertEqual(result["exploration"]["success"], False)
            self.assertIn("explore_capabilities", result["execution_path"])
            self.assertNotIn("explore_learn", result["execution_path"])
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["source_tool"], "failing_weather")
            self.assertEqual(pending[0]["sample_error"], "network unavailable")

    def test_feishu_integration_request_explores_public_capability_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("给飞书做一个消息对接，增加给飞书发一条消息功能")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["exploration"]["tool_id"], "feishu_send_message")
            self.assertEqual(result["exploration"]["success"], False)
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["source_tool"], "feishu_send_message")
            self.assertEqual(pending[0]["public_support"], True)
            self.assertIn("/im/v1/messages", pending[0]["endpoint"])
            self.assertIn("def feishu_send_message", pending[0]["handler_code_proposal"])

    def test_public_web_search_can_answer_and_deposit_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FakeWebSearchTool()]),
            )
            result = agent.ask("搜索 LangGraph 是什么")
            self.assertEqual(result["route"], "capability")
            self.assertEqual(result["exploration"]["tool_id"], "fake_web_search")
            self.assertIsNone(result["exploration"]["candidate_type"])
            self.assertIsNone(result["learning_candidate_id"])
            self.assertIn("LangGraph", result["answer"])
            self.assertEqual(agent.review_store.list_pending(), [])

            result = agent.ask("搜索 LangGraph 怎么用")
            self.assertEqual(result["exploration"]["candidate_type"], "skill")
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "skill")
            self.assertEqual(pending[0]["source_tool"], "fake_web_search")
            self.assertTrue(pending[0]["public_evidence"])
            self.assertIn("llm_draft", pending[0])

    def test_public_search_evidence_can_feed_tool_builder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FakeWebSearchTool()]),
            )
            result = agent.ask("如何接入库存API工具")
            self.assertEqual(result["route"], "tool_builder")
            self.assertIn("register_generated_tool", result["execution_path"])
            self.assertEqual(
                result["deterministic_results"][0]["data"]["evidence_count"],
                1,
            )

    def test_unstable_exploration_falls_back_to_skill(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("帮我提升这个方案的表达质量")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["exploration"]["candidate_type"], "skill")
            self.assertIsNone(result["learning_candidate_id"])
            self.assertEqual(agent.review_store.list_pending(), [])

            result = agent.ask("帮我优化这个方案的表达质量")
            self.assertEqual(result["exploration"]["learning_policy"], "repeated_similar_question")
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "skill")
            self.assertFalse(pending[0]["can_generate_rule_code"])
            self.assertEqual(pending[0]["stability_decision"], "llm_drafted_skill_candidate")

    def test_preference_exploration_falls_back_to_memory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("以后默认用表格输出，这是我的偏好")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["exploration"]["candidate_type"], "memory")
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "memory")

    def test_tool_builder_rejects_dangerous_generated_code(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=UnsafeToolBuilderModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询工具")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["tool_builder"]["stage"], "validate_tool_code")
            self.assertEqual(result["tool_builder"]["error"], "unsafe_code")
            self.assertEqual(agent.list_generated_tools(), [])
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "counterexample")

    def test_write_generated_tool_requires_confirmation_after_registration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("给飞书机器人增加发送一条消息的能力")
            self.assertEqual(result["route"], "tool_builder")
            generated = agent.list_generated_tools()[0]
            self.assertEqual(generated["permission"], "confirm")
            self.assertFalse(generated["auto_enabled"])
            self.assertEqual(result["tool_builder"]["evaluation"]["status"], "waiting_human")
            self.assertTrue(result["tool_builder"]["evaluation"]["requires_confirmation"])
            self.assertIn(
                "tool_builder_permission_policy",
                result["tool_builder"]["evaluation"]["passed_checks"],
            )

            follow_up = agent.ask("给飞书机器人发送一条消息")
            self.assertEqual(follow_up["route"], "need_more_info")
            self.assertEqual(
                follow_up["exploration"]["error"],
                "permission_confirmation_required",
            )

    def test_learning_uses_single_personal_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            candidate_id = agent.submit_feedback(
                "晨会摘要格式",
                "晨会摘要必须使用个人专属格式。",
            )
            agent.approve(candidate_id)

            result = agent.ask("晨会摘要格式是什么？", context={"session_id": "session-a"})
            self.assertEqual(result["route"], "rules")
            self.assertIn("个人专属格式", result["answer"])
            pending = agent.list_pending()
            self.assertNotIn(candidate_id, {item["id"] for item in pending})
            self.assertFalse((settings.runtime_dir / "users").exists())

    def test_memory_and_counterexample_use_single_personal_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.skills_dir.joinpath("monthly.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "skill_monthly",
                        "name": "月报 Skill",
                        "description": "monthly",
                        "task_types": ["general"],
                        "keywords": ["月报"],
                        "priority": 50,
                        "status": "active",
                        "prompt": "生成月报",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            memory_id = agent.submit_feedback(
                "月报",
                "以后默认用表格输出，这是我的偏好。",
            )
            agent.approve(memory_id)
            result = agent.ask("帮我写月报", context={"session_id": "session-a"})
            self.assertIn("| 项目 | 内容 |", result["answer"])

            personal_counter = settings.runtime_dir / "personal" / "counterexamples"
            personal_counter.mkdir(parents=True, exist_ok=True)
            personal_counter.joinpath("counter_bad.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "counter_bad",
                        "status": "active",
                        "keywords": ["月报"],
                        "bad_pattern": "已按 Skills 执行",
                        "correction": "不要只说执行了 Skill，要输出实际内容。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            result = agent.ask("帮我写月报", context={"session_id": "session-b"})
            self.assertLessEqual(result["confidence"], 0.5)

    def test_personal_rule_takes_priority_over_global_rule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings.rules_dir.joinpath("global_summary.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "global_summary",
                        "type": "business_definition",
                        "name": "全局摘要格式规则",
                        "intent": ["report_writing"],
                        "keywords": ["摘要格式"],
                        "priority": 500,
                        "status": "active",
                        "handler": "pass_through",
                        "rule": "全局摘要格式。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            personal_rules = settings.runtime_dir / "personal" / "rules"
            personal_rules.mkdir(parents=True, exist_ok=True)
            personal_rules.joinpath("personal_summary.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "personal_summary",
                        "type": "business_definition",
                        "name": "个人摘要格式规则",
                        "intent": ["report_writing"],
                        "keywords": ["摘要格式"],
                        "priority": 1,
                        "status": "active",
                        "handler": "pass_through",
                        "rule": "个人摘要格式。",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask("摘要格式是什么？")
            self.assertEqual(result["matched_rules"][0]["id"], "personal_summary")

    def test_generated_tool_uses_single_personal_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询工具")
            self.assertEqual(result["route"], "tool_builder")
            self.assertTrue(agent.list_generated_tools())
            tools = {item["id"] for item in agent.list_capabilities()}
            tool_id = agent.list_generated_tools()[0]["id"]
            self.assertIn(tool_id, tools)
            self.assertTrue(
                (settings.runtime_dir / "personal" / "generated_tools" / f"{tool_id}.py").exists()
            )
            self.assertFalse((settings.runtime_dir / "users").exists())

    def test_ask_writes_run_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            (settings.rules_dir / "percentage.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "rule_percentage_formula",
                        "type": "formula",
                        "name": "通用百分比计算规则",
                        "intent": ["calculation"],
                        "keywords": ["百分比", "完成率", "总数"],
                        "priority": 100,
                        "status": "active",
                        "handler": "percentage_formula",
                        "rule": "百分比 = 分子 / 分母 * 100%",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask(
                "已完成10，总数200，完成率百分比是多少？",
                context={"numerator": 10, "denominator": 200},
            )
            self.assertIn("run_id", result)
            record = agent.get_run(result["run_id"])
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["type"], "ask")
            self.assertEqual(record["route"], "rules")
            self.assertEqual(record["matched_rules"][0]["id"], "rule_percentage_formula")
            self.assertIn("execute_rules", record["execution_path"])
            self.assertIn("5.00%", record["answer_preview"])
            self.assertTrue(
                (
                    settings.runtime_dir
                    / "personal"
                    / "runs"
                    / "ask"
                    / f"{result['run_id']}.json"
                ).exists()
            )
            self.assertFalse((settings.runtime_dir / "users").exists())

    def test_ask_run_records_evaluation_for_rules(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            (settings.rules_dir / "percentage.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "rule_percentage_formula",
                        "type": "formula",
                        "name": "通用百分比计算规则",
                        "intent": ["calculation"],
                        "keywords": ["百分比", "完成率", "总数"],
                        "priority": 100,
                        "status": "active",
                        "handler": "percentage_formula",
                        "rule": "百分比 = 分子 / 分母 * 100%",
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.ask(
                "已完成10，总数200，完成率百分比是多少？",
                context={"numerator": 10, "denominator": 200},
            )
            self.assertEqual(result["evaluation"]["status"], "pass")
            passed = set(result["evaluation"]["passed_checks"])
            self.assertIn("rule_value_consistency", passed)
            self.assertIn("deterministic_result_used", passed)

            record = agent.get_run(result["run_id"])
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["evaluation"]["status"], "pass")

    def test_ask_evaluator_detects_missing_rule_value(self) -> None:
        result = AskEvaluator().evaluate(
            {
                "answer": "计算完成。",
                "route": "rules",
                "matched_rules": [{"id": "rule_percentage_formula"}],
                "deterministic_results": [{"rule_id": "rule_percentage_formula", "value": "5.00%"}],
                "counterexamples_checked": [],
            }
        )
        self.assertEqual(result.status, "needs_revision")
        failed = set(result.failed_checks)
        self.assertIn("rule_value_consistency", failed)

    def test_tool_failure_is_evaluated_without_fabricating_answer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([FailingWeatherTool()]),
            )
            result = agent.ask("今天上海天气怎么样？")
            self.assertEqual(result["route"], "need_more_info")
            self.assertEqual(result["evaluation"]["status"], "waiting_human")
            self.assertTrue(result["evaluation"]["requires_confirmation"])
            passed = set(result["evaluation"]["passed_checks"])
            self.assertIn("tool_error_not_hidden", passed)
            self.assertIn("network unavailable", result["answer"])

    def test_personal_assistant_generic_clarification_is_rejected(self) -> None:
        result = AskEvaluator().evaluate(
            {
                "question": "我作为乙方软件公司的销售，明天要去拜访甲方，我应该准备什么？",
                "task_type": "sales_support",
                "route": "need_more_info",
                "answer": "请补充字段定义、计算口径、数据源/API 和输出字段。",
                "counterexamples_checked": [],
            }
        )
        self.assertIn(result.status, {"needs_revision", "waiting_human"})
        failed = set(result.failed_checks)
        self.assertIn("clarification_specificity", failed)

    def test_tool_builder_writes_tool_run_without_generated_code_body(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=UnsafeToolBuilderModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询工具")
            self.assertIn("run_id", result)
            self.assertIn("tool_run_id", result)
            tool_run = agent.get_run(result["tool_run_id"])
            self.assertIsNotNone(tool_run)
            assert tool_run is not None
            self.assertEqual(tool_run["type"], "tool")
            self.assertEqual(tool_run["status"], "failed")
            self.assertEqual(tool_run["tool_builder"]["error"], "unsafe_code")
            self.assertEqual(tool_run["evaluation"]["status"], "failed")
            failed = set(tool_run["evaluation"]["failed_checks"])
            self.assertIn("tool_builder_safety", failed)
            self.assertNotIn("data", tool_run["tool_builder"]["evaluation"]["checks"][1])
            serialized = json.dumps(tool_run, ensure_ascii=False)
            self.assertNotIn("os.remove", serialized)
            self.assertFalse((settings.runtime_dir / "users").exists())

    def test_tool_builder_pending_counterexample_contains_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=UnsafeToolBuilderModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询工具")
            self.assertEqual(result["evaluation"]["status"], "waiting_human")
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "counterexample")
            self.assertEqual(pending[0]["evaluation"]["status"], "failed")
            failed = set(pending[0]["evaluation"]["failed_checks"])
            self.assertIn("tool_builder_safety", failed)

    def test_generated_tool_rule_candidate_contains_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            result = agent.ask("帮我生成一个查询汇率的只读工具，以后可以复用")
            self.assertEqual(result["route"], "tool_builder")
            pending = agent.review_store.list_pending()
            self.assertEqual(pending[0]["candidate_type"], "rule")
            self.assertEqual(pending[0]["evaluation"]["status"], "pass")
            passed = set(pending[0]["evaluation"]["passed_checks"])
            self.assertIn("tool_builder_safety", passed)
            self.assertIn("tool_builder_dry_run", passed)

    def test_goal_start_creates_personal_goal_and_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            result = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
            )
            goal_id = result["goal_id"]
            self.assertEqual(result["status"], "active")
            self.assertTrue(result["tasks"])
            self.assertTrue((settings.runtime_dir / "personal" / "goals" / goal_id).exists())
            self.assertTrue(agent.list_goals())
            self.assertFalse((settings.runtime_dir / "users").exists())

            stepped = agent.step_goal(goal_id)
            self.assertEqual(stepped["status"], "completed")
            self.assertIn("拜访目标", stepped["answer"])
            self.assertEqual(stepped["learning_candidate_ids"], [])

    def test_goal_start_and_step_update_goal_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
                max_steps=1,
            )
            self.assertIn("run_id", started)
            goal_run = agent.get_run(started["run_id"])
            self.assertIsNotNone(goal_run)
            assert goal_run is not None
            self.assertEqual(goal_run["type"], "goal")
            self.assertEqual(goal_run["input"]["goal_id"], started["goal_id"])

            stepped = agent.step_goal(started["goal_id"])
            self.assertEqual(stepped["run_id"], started["run_id"])
            updated = agent.get_run(started["run_id"])
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated["status"], stepped["status"])
            self.assertEqual(updated["input"]["goal"], "我作为销售明天拜访甲方，帮我准备一个行动方案")
            self.assertEqual(updated["input"]["goal_id"], started["goal_id"])
            self.assertIn("evaluate_progress", updated["execution_path"])
            self.assertTrue(updated["evaluation"])
            self.assertIn("status", updated["evaluation"])
            self.assertTrue(
                (
                    settings.runtime_dir
                    / "personal"
                    / "runs"
                    / "goals"
                    / f"{started['run_id']}.json"
                ).exists()
            )

    def test_goal_step_returns_unified_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
                max_steps=1,
            )
            stepped = agent.step_goal(started["goal_id"])
            self.assertTrue(stepped["evaluations"])
            latest = stepped["evaluations"][-1]
            self.assertIn("passed_checks", latest)
            self.assertIn("failed_checks", latest)
            self.assertIn("risk_flags", latest)
            self.assertEqual(stepped["last_evaluation"]["status"], latest["status"])

    def test_run_store_latest_list_and_preview_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            run = agent.run_store.record_ask(
                "长答案",
                {},
                {"answer": "x" * 1200, "route": "general_reason", "execution_path": ["reason"]},
            )
            latest = agent.latest_run("ask")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest["id"], run.id)
            self.assertEqual(len(latest["answer_preview"]), 1000)
            listed = agent.list_runs("ask")
            self.assertEqual(listed[0]["id"], run.id)

    def test_run_store_persists_ask_evaluation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            run = agent.run_store.record_ask(
                "测试评估记录",
                {},
                {
                    "answer": "ok",
                    "route": "general_reason",
                    "execution_path": ["reason", "evaluate"],
                    "evaluation": {
                        "status": "pass",
                        "score": 1.0,
                        "passed_checks": ["answer_not_empty"],
                        "failed_checks": [],
                    },
                },
            )
            record = agent.get_run(run.id)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["evaluation"]["status"], "pass")
            self.assertEqual(record["evaluation"]["passed_checks"], ["answer_not_empty"])

    def test_goal_task_reads_old_yaml_with_dag_defaults(self) -> None:
        task = GoalTask.from_dict(
            {
                "task_id": "task_001",
                "title": "旧任务",
                "type": "reasoning",
                "status": "pending",
            }
        )
        self.assertEqual(task.depends_on, [])
        self.assertEqual(task.executor, "reasoning")
        self.assertEqual(task.attempts, 0)
        self.assertEqual(task.max_attempts, 2)
        self.assertEqual(task.acceptance_criteria, [])

    def test_llm_goal_planner_outputs_dag_and_fallback_works(self) -> None:
        class JsonPlannerModel(LocalHeuristicModel):
            def generate(self, question, deterministic_results, skills, context):
                return """
                {
                  "goal_type": "research",
                  "success_criteria": ["完成公开资料查询"],
                  "tasks": [
                    {"task_id": "task_001", "title": "查资料", "type": "research", "executor": "research", "risk": "low"},
                    {"task_id": "task_002", "title": "回答", "type": "reasoning", "executor": "ask", "depends_on": ["task_001"], "risk": "low"}
                  ]
                }
                """

        criteria, tasks = CompositeGoalPlanner(JsonPlannerModel()).plan("查询公开资料")
        self.assertEqual(criteria, ["完成公开资料查询"])
        self.assertEqual(tasks[1].depends_on, ["task_001"])
        self.assertEqual(tasks[1].executor, "ask")

        fallback_criteria, fallback_tasks = CompositeGoalPlanner(LocalHeuristicModel()).plan(
            "帮我搜索公开资料"
        )
        self.assertTrue(fallback_criteria)
        self.assertEqual(fallback_tasks[1].depends_on, ["task_001"])

    def test_goal_dag_step_respects_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
                max_steps=1,
            )
            stepped = agent.step_goal(started["goal_id"])
            statuses = {task["task_id"]: task["status"] for task in stepped["tasks"]}
            self.assertEqual(statuses["task_001"], "done")
            self.assertEqual(statuses["task_002"], "pending")
            self.assertEqual(stepped["status"], "active")
            self.assertEqual(stepped["next_action"], "continue")
            self.assertEqual(stepped["revision_count"], 0)
            self.assertFalse(any(task["task_id"] == "task_004" for task in stepped["tasks"]))

    def test_goal_plan_events_pause_resume_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal("帮我搜索公开资料")
            goal_id = started["goal_id"]

            plan = agent.get_goal_plan(goal_id)
            self.assertEqual(plan["goal_id"], goal_id)
            self.assertTrue(plan["tasks"])
            self.assertEqual(plan["plan_version"], 1)

            paused = agent.pause_goal(goal_id)
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["next_action"], "paused")
            resumed = agent.resume_goal(goal_id)
            self.assertEqual(resumed["status"], "active")

            events = agent.get_goal_events(goal_id)
            event_names = [item["event"] for item in events["events"]]
            self.assertIn("goal_created", event_names)
            self.assertIn("goal_paused", event_names)
            self.assertIn("goal_resumed", event_names)

    def test_goal_start_uses_langgraph_thread_checkpoint_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal("帮我搜索公开资料")
            self.assertEqual(started["thread_id"], started["goal_id"])
            self.assertTrue(started["checkpointed"])
            self.assertIn(started["checkpoint_backend"], {"sqlite", "memory"})
            self.assertFalse(started["resume_required"])

            events = agent.get_goal_events(started["goal_id"])
            self.assertEqual(events["thread_id"], started["goal_id"])
            self.assertTrue(events["checkpointed"])
            self.assertIn("checkpoint_summary", events)

    def test_goal_step_recovers_from_checkpoint_when_projection_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
                max_steps=1,
            )
            projection_tasks = (
                settings.runtime_dir
                / "personal"
                / "goals"
                / started["goal_id"]
                / "tasks.yaml"
            )
            projection_tasks.unlink()

            stepped = agent.step_goal(started["goal_id"])
            self.assertTrue(stepped["tasks"])
            self.assertEqual(stepped["tasks"][0]["status"], "done")
            self.assertTrue(projection_tasks.exists())

    def test_goal_status_rebuilds_projection_from_checkpoint_when_goal_yaml_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(settings=settings, chat_model=LocalHeuristicModel())
            started = agent.start_goal(
                "我作为销售明天拜访甲方，帮我准备一个行动方案",
                max_steps=1,
            )
            goal_yaml = (
                settings.runtime_dir
                / "personal"
                / "goals"
                / started["goal_id"]
                / "goal.yaml"
            )
            goal_yaml.unlink()

            status = agent.get_goal(started["goal_id"])
            self.assertEqual(status["goal_id"], started["goal_id"])
            self.assertTrue(status["tasks"])
            self.assertTrue(goal_yaml.exists())

    def test_goal_interrupt_payload_and_resume_use_same_thread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            started = agent.start_goal(
                "帮我接入飞书机器人，支持给指定群发送消息，并沉淀成可复用能力。",
                max_steps=5,
            )
            stepped = agent.step_goal(started["goal_id"])
            self.assertTrue(stepped["interrupted"])
            self.assertTrue(stepped["resume_required"])
            self.assertEqual(stepped["thread_id"], started["goal_id"])
            self.assertEqual(stepped["interrupt_payload"]["goal_id"], started["goal_id"])

            confirmed = agent.step_goal(started["goal_id"], confirm=True)
            self.assertEqual(confirmed["thread_id"], started["goal_id"])
            self.assertFalse(confirmed["resume_required"])
            self.assertEqual(confirmed["status"], "completed")

    def test_feishu_url_verification_returns_challenge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "feishu_verification_token": "verify-token",
                }
            )
            handler = FeishuEventHandler(settings, lambda question, context: {})
            result = handler.handle(
                {
                    "type": "url_verification",
                    "token": "verify-token",
                    "challenge": "abc123",
                }
            )
            self.assertEqual(result, {"challenge": "abc123"})

    def test_feishu_message_event_calls_agent_and_replies(self) -> None:
        class FakeFeishuClient:
            def __init__(self) -> None:
                self.sent = []

            def send_text(self, *, receive_id, text, receive_id_type="chat_id"):
                self.sent.append(
                    {
                        "receive_id": receive_id,
                        "receive_id_type": receive_id_type,
                        "text": text,
                    }
                )
                return {"code": 0}

        calls = []

        def ask(question, context):
            calls.append({"question": question, "context": context})
            return {"answer": f"收到：{question}", "route": "reason"}

        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "feishu_verification_token": "verify-token",
                }
            )
            client = FakeFeishuClient()
            handler = FeishuEventHandler(settings, ask, client=client)
            payload = {
                "schema": "2.0",
                "header": {
                    "event_id": "evt_1",
                    "event_type": "im.message.receive_v1",
                    "token": "verify-token",
                },
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_1"}},
                    "message": {
                        "message_id": "msg_1",
                        "chat_id": "oc_1",
                        "chat_type": "group",
                        "content": "{\"text\":\"@MonkeyAgent 你好\"}",
                    },
                },
            }
            result = handler.handle(payload)
            self.assertEqual(result["status"], "replied")
            self.assertEqual(calls[0]["question"], "你好")
            self.assertEqual(calls[0]["context"]["feishu_chat_id"], "oc_1")
            self.assertEqual(calls[0]["context"]["feishu_sender_id"], "ou_1")
            self.assertEqual(result["sender_id"], "ou_1")
            self.assertEqual(client.sent[0]["receive_id"], "oc_1")
            self.assertEqual(client.sent[0]["receive_id_type"], "chat_id")
            self.assertIn("收到：你好", client.sent[0]["text"])

            duplicate = handler.handle(payload)
            self.assertEqual(duplicate["status"], "duplicate")
            self.assertEqual(len(client.sent), 1)

    def test_feishu_rejects_invalid_verification_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = Settings(
                **{
                    **settings_for(Path(raw)).__dict__,
                    "feishu_verification_token": "verify-token",
                }
            )
            handler = FeishuEventHandler(settings, lambda question, context: {})
            with self.assertRaises(FeishuSecurityError):
                handler.handle({"type": "url_verification", "token": "bad", "challenge": "x"})

    def test_goal_integration_builds_tool_and_waits_for_write_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            agent = MonkeyAgent(
                settings=settings,
                chat_model=LocalHeuristicModel(),
                capability_registry=CapabilityRegistry([]),
            )
            started = agent.start_goal(
                "帮我接入飞书机器人，支持给指定群发送消息，并沉淀成可复用能力。",
                max_steps=5,
            )
            stepped = agent.step_goal(started["goal_id"])
            self.assertEqual(stepped["status"], "waiting_human")
            self.assertTrue(stepped["requires_confirmation"])
            self.assertTrue(agent.list_generated_tools())
            self.assertTrue(stepped["learning_candidate_ids"])
            self.assertIn("ask_human", stepped["execution_path"])
            self.assertEqual(stepped["last_evaluation"]["status"], "waiting_human")
            self.assertTrue(stepped["last_evaluation"]["requires_confirmation"])

            confirmed = agent.step_goal(
                started["goal_id"],
                confirm=True,
            )
            self.assertEqual(confirmed["status"], "completed")

    def test_bailian_role_models_are_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            settings = settings_for(Path(raw))
            settings = Settings(
                **{
                    **settings.__dict__,
                    "dashscope_api_key": "test-key",
                    "chat_model": "qwen-plus",
                    "classifier_model": "qwen-classifier",
                    "reasoning_model": "qwen-reasoning",
                    "tool_builder_model": "qwen-coder",
                    "evaluator_model": "qwen-evaluator",
                }
            )
            try:
                model = BailianChatModel(settings)
            except RuntimeError as exc:
                self.skipTest(str(exc))
            self.assertEqual(model.model_for_role("classifier"), "qwen-classifier")
            self.assertEqual(model.model_for_role("reasoning"), "qwen-reasoning")
            self.assertEqual(model.model_for_role("tool_builder"), "qwen-coder")
            self.assertEqual(model.model_for_role("evaluator"), "qwen-evaluator")
            self.assertEqual(model.model_for_role("unknown"), "qwen-plus")


if __name__ == "__main__":
    unittest.main()


class FakeWeatherTool:
    id = "fake_weather"
    name = "Fake Weather"
    description = "Fake deterministic weather tool for tests."

    def can_handle(self, question, context):
        return "天气" in question

    def execute(self, question, context):
        location = "合肥" if "合肥" in question else "上海"
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


class FailingWeatherTool:
    id = "failing_weather"
    name = "Failing Weather"
    description = "Failing weather tool for tests."

    def can_handle(self, question, context):
        return "天气" in question

    def execute(self, question, context):
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=False,
            stable_rule_candidate=True,
            content="天气工具调用失败。",
            error="network unavailable",
            handler_name="weather_query",
            handler_code_proposal="def weather_query(rule, question, context): pass",
        )


class FakeWebSearchTool:
    id = "fake_web_search"
    name = "Fake Web Search"
    description = "Fake public search tool for tests."

    def can_handle(self, question, context):
        return (
            "搜索" in question
            or "NBA" in question
            or "比赛" in question
            or "API" in question
            or "接入" in question
        )

    def execute(self, question, context):
        evidence = [
            {
                "title": "LangGraph",
                "url": "https://langchain-ai.github.io/langgraph/",
                "snippet": "LangGraph is a framework for building agent workflows.",
            }
        ]
        return ToolResult(
            tool_id=self.id,
            tool_name=self.name,
            success=True,
            stable_rule_candidate=False,
            candidate_type="skill",
            content="已搜索到 LangGraph 公开资料。",
            data={"results": evidence, "public_support": True},
            public_evidence=evidence,
        )


class UnsafeToolBuilderModel(LocalHeuristicModel):
    def draft_tool_builder(self, question, spec, evidence, context):
        return {
            "tool_id": spec["tool_id"],
            "name": "危险工具",
            "description": "unsafe",
            "kind": "python_function",
            "permission": "auto",
            "risk": "low",
            "read_only": True,
            "learn_policy": "rule",
            "keywords": ["查询"],
            "class_name": "GeneratedTool",
            "code": (
                "import os\n"
                "class GeneratedTool:\n"
                "    id = 'unsafe_tool'\n"
                "    name = 'unsafe'\n"
                "    description = 'unsafe'\n"
                "    def can_handle(self, question, context): return True\n"
                "    def execute(self, question, context): os.remove('x')\n"
                "TOOL_CLASS = GeneratedTool\n"
            ),
            "test_context": {},
        }


class FailingReasonModel(LocalHeuristicModel):
    def generate(self, question, deterministic_results, skills, context):
        raise RuntimeError("network unavailable")

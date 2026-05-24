from __future__ import annotations

from test_rules_first import *  # noqa: F401,F403

MonkeyAgentRulesFirstTest = None


class RunsTest(unittest.TestCase):
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
            self.assertTrue(record["timings"])
            self.assertTrue(any(item["node"] == "execute_rules" for item in record["timings"]))
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


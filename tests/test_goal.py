from __future__ import annotations

from test_rules_first import *  # noqa: F401,F403

MonkeyAgentRulesFirstTest = None


class GoalTest(unittest.TestCase):
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


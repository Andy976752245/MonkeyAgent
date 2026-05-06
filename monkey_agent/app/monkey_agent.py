from __future__ import annotations

from typing import Any
from pathlib import Path

from monkey_agent.domains.tools.capability import CapabilityRegistry
from monkey_agent.domains.agent_skills import AgentSkillInstaller, AgentSkillRepository
from monkey_agent.domains.classifier import QuestionClassifier
from monkey_agent.core.config import Settings, load_settings
from monkey_agent.domains.tools.generated import GeneratedToolStore
from monkey_agent.workflows.goal.evaluator import GoalEvaluator
from monkey_agent.workflows.goal.executor import GoalExecutor
from monkey_agent.workflows.goal.planner import CompositeGoalPlanner
from monkey_agent.domains.goals.store import GoalStore
from monkey_agent.workflows.goal.workflow import build_goal_workflow
from monkey_agent.workflows.ask.nodes import GraphNodes
from monkey_agent.workflows.ask.workflow import build_workflow
from monkey_agent.domains.learning.usage_memory import UsageMemory
from monkey_agent.domains.learning.review_store import ReviewStore
from monkey_agent.domains.memory import PersonalMemoryStore
from monkey_agent.domains.models.bailian import ChatModel, build_chat_model
from monkey_agent.domains.rules.repository import RuleRepository
from monkey_agent.domains.runs import RunStore
from monkey_agent.domains.skills.repository import SkillRepository
from monkey_agent.core.state import AgentState
from monkey_agent.domains.tool_builder import ToolBuilderService
from monkey_agent.domains.tools import ToolRegistry, build_default_tool_registry
from monkey_agent.core.users import PersonalWorkspace


class MonkeyAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        chat_model: ChatModel | None = None,
        capability_registry: CapabilityRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.chat_model = chat_model or build_chat_model(self.settings)
        self.global_generated_tool_store = GeneratedToolStore(
            self.settings.generated_tools_dir,
            self.settings.generated_tools_registry,
        )
        if tool_registry is not None:
            self._base_tools = list(tool_registry.tools)
        elif capability_registry is not None:
            self._base_tools = list(capability_registry.tools)
        else:
            self._base_tools = list(build_default_tool_registry().tools)
        self._configure_workspace()

    def _configure_workspace(self) -> None:
        self.personal_workspace = PersonalWorkspace.from_runtime(self.settings.runtime_dir)
        self.personal_workspace.ensure()
        self.rules = RuleRepository(
            self.personal_workspace.rules_dir,
            fallback_dirs=[self.settings.rules_dir],
        )
        self.skills = SkillRepository(
            self.personal_workspace.skills_dir,
            fallback_dirs=[self.settings.skills_dir],
        )
        self.agent_skills = AgentSkillRepository(
            self.personal_workspace.agent_skills_dir,
            self.personal_workspace.agent_skills_registry,
        )
        self.agent_skill_installer = AgentSkillInstaller(
            self.personal_workspace.agent_skills_dir,
            self.agent_skills,
        )
        self.review_store = ReviewStore(
            self.personal_workspace.pending_review_dir,
            self.personal_workspace.rules_dir,
            self.personal_workspace.skills_dir,
            self.personal_workspace.memory_dir,
            self.personal_workspace.counterexamples_dir,
        )
        self.usage_memory = UsageMemory(
            self.personal_workspace.memory_dir,
            repeat_threshold=self.settings.learning_repeat_threshold,
        )
        self.personal_memory = PersonalMemoryStore(
            self.personal_workspace.memory_dir,
            self.personal_workspace.counterexamples_dir,
            fallback_memory_dirs=[self.settings.memory_dir],
            fallback_counterexamples_dirs=[self.settings.counterexamples_dir],
        )
        self.generated_tool_store = GeneratedToolStore(
            self.personal_workspace.generated_tools_dir,
            self.personal_workspace.generated_tools_registry,
        )
        self.tool_registry = ToolRegistry(list(self._base_tools))
        for tool in self.global_generated_tool_store.enabled_tools():
            self.tool_registry.add(tool)
        for tool in self.generated_tool_store.enabled_tools():
            self.tool_registry.add(tool)
        self.capability_registry = CapabilityRegistry(self.tool_registry.tools)
        self.classifier = QuestionClassifier(self.chat_model)
        self.tool_builder = ToolBuilderService(
            self.chat_model,
            self.generated_tool_store,
            self.personal_workspace.root,
        )
        self.goal_store = GoalStore(self.personal_workspace.goals_dir)
        self.run_store = RunStore(self.personal_workspace.runs_dir)
        self.nodes = GraphNodes(
            self.rules,
            self.skills,
            self.agent_skills,
            self.chat_model,
            self.review_store,
            self.capability_registry,
            self.usage_memory,
            self.classifier,
            self.personal_memory,
            self.tool_builder,
            self.tool_registry,
        )
        self.workflow = build_workflow(self.nodes)
        self.goal_workflow = build_goal_workflow(
            self.goal_store,
            CompositeGoalPlanner(self.chat_model),
            GoalExecutor(self._ask_for_goal, self.review_store),
            GoalEvaluator(),
        )

    def _ask_for_goal(self, question: str, context: dict[str, Any]) -> AgentState:
        return self.ask(question, context=context)

    def ask(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        feedback: str | None = None,
    ) -> AgentState:
        context = dict(context or {})
        state: AgentState = {
            "question": question,
            "context": context,
            "feedback": feedback,
            "errors": [],
        }
        try:
            result = self.workflow.invoke(state)
        except Exception as exc:
            self._record_failed_ask_run(question, context, exc)
            raise
        self._attach_ask_run(question, context, result)
        return result

    def submit_feedback(
        self,
        question: str,
        feedback: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        context = dict(context or {})
        return self.review_store.create_candidate(question, feedback, context)

    def adopt(self, candidate_id: str) -> str:
        return str(self.review_store.approve(candidate_id))

    def list_rules(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.rules.list()]

    def list_skills(
        self,
        skill_type: str = "all",
    ) -> list[dict[str, Any]]:
        yaml_skills = [
            {**item.to_dict(), "skill_kind": "yaml"}
            for item in self.skills.list()
        ]
        agent_skills = [item.to_dict() for item in self.agent_skills.list()]
        if skill_type == "yaml":
            return yaml_skills
        if skill_type == "agent":
            return agent_skills
        return yaml_skills + agent_skills

    def list_agent_skills(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.agent_skills.list()]

    def inspect_agent_skill(self, skill_name: str) -> dict[str, Any] | None:
        return self.agent_skills.inspect(skill_name)

    def install_agent_skill(self, source: str, skill_name: str | None = None) -> dict[str, Any]:
        return self.agent_skill_installer.install(source, skill_name)

    def import_agent_skill(self, path: str) -> dict[str, Any]:
        return self.agent_skill_installer.import_local(Path(path))

    def enable_agent_skill(self, skill_name: str) -> dict[str, Any]:
        return self.agent_skill_installer.enable(skill_name)

    def disable_agent_skill(self, skill_name: str) -> dict[str, Any]:
        return self.agent_skill_installer.disable(skill_name)

    def remove_agent_skill(self, skill_name: str) -> dict[str, Any]:
        return self.agent_skill_installer.remove(skill_name)

    def list_memory(self) -> list[dict[str, Any]]:
        return _list_yaml_dicts_many(
            [self.personal_workspace.memory_dir, self.settings.memory_dir]
        )

    def list_counterexamples(self) -> list[dict[str, Any]]:
        return _list_yaml_dicts_many(
            [self.personal_workspace.counterexamples_dir, self.settings.counterexamples_dir]
        )

    def list_capabilities(self) -> list[dict[str, str]]:
        return self.tool_registry.list()

    def list_generated_tools(self) -> list[dict[str, Any]]:
        return self.generated_tool_store.list()

    def get_generated_tool(self, tool_id: str) -> dict[str, Any] | None:
        return self.generated_tool_store.get(tool_id)

    def enable_generated_tool(self, tool_id: str) -> dict[str, Any]:
        item = self.generated_tool_store.set_enabled(tool_id, True)
        loaded = self.generated_tool_store.load(tool_id)
        if loaded.tool is not None:
            self.tool_registry.add(loaded.tool)
            self.capability_registry.add(loaded.tool)
        return item

    def disable_generated_tool(self, tool_id: str) -> dict[str, Any]:
        item = self.generated_tool_store.set_enabled(tool_id, False)
        self.tool_registry.tools = [tool for tool in self.tool_registry.tools if tool.id != tool_id]
        self.capability_registry.tools = [
            tool for tool in self.capability_registry.tools if tool.id != tool_id
        ]
        return item

    def test_generated_tool(self, tool_id: str) -> dict[str, Any]:
        return self.generated_tool_store.test(tool_id)

    def list_pending(self) -> list[dict[str, Any]]:
        return self.review_store.list_pending()

    def approve(self, candidate_id: str) -> str:
        return str(self.review_store.approve(candidate_id))

    def reject(self, candidate_id: str) -> str:
        return str(self.review_store.reject(candidate_id))

    def start_goal(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
        autonomy_policy: str = "read_only_auto_write_confirm",
        success_criteria: list[str] | None = None,
        force_learning: bool = False,
    ) -> dict[str, Any]:
        context = dict(context or {})
        result = self.goal_workflow.start(
            goal,
            context=context,
            max_steps=max_steps,
            autonomy_policy=autonomy_policy,
            success_criteria=success_criteria,
            force_learning=force_learning,
        )
        self._attach_goal_run(
            result,
            {
                "goal_id": result.get("goal_id"),
                "goal": goal,
                "context": context,
                "max_steps": max_steps,
                "autonomy_policy": autonomy_policy,
                "success_criteria": success_criteria or [],
                "force_learning": force_learning,
                "_raw_result_path": str(
                    self.personal_workspace.goals_dir / str(result.get("goal_id"))
                ),
            },
        )
        return result

    def step_goal(
        self,
        goal_id: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        result = self.goal_workflow.step(goal_id, confirm=confirm)
        run_id = self.run_store.latest_goal_run_id(goal_id)
        self._attach_goal_run(
            result,
            {
                "goal_id": goal_id,
                "confirm": confirm,
                "_raw_result_path": str(self.personal_workspace.goals_dir / goal_id),
            },
            run_id=run_id,
        )
        return result

    def get_goal(self, goal_id: str) -> dict[str, Any]:
        try:
            return self.goal_workflow.status(goal_id)
        except FileNotFoundError:
            raise
        except Exception:
            pass
        data = self.goal_store.get(goal_id)
        tasks = data.get("tasks", [])
        return {
            "goal_id": data.get("id"),
            "status": data.get("status"),
            "summary": data.get("summary"),
            "current_task": next(
                (
                    task
                    for task in tasks
                    if task.get("status") in {"pending", "running", "blocked"}
                ),
                {},
            ),
            "tasks": tasks,
            "events": data.get("events", []),
            "answer": data.get("summary", ""),
            "requires_confirmation": data.get("status") == "waiting_human",
            "confirmation_prompt": None,
            "learning_candidate_ids": _goal_learning_ids(tasks),
            "artifacts": data.get("artifacts", []),
            "execution_path": ["goal_status"],
            "evidence": data.get("evidence", []),
            "evaluations": data.get("evaluations", []),
            "last_evaluation": data.get("last_evaluation", {}),
            "plan_version": data.get("plan_version", 1),
            "revision_count": data.get("revision_count", 0),
            "next_action": data.get("last_evaluation", {}).get("next_action", ""),
        }

    def list_goals(self) -> list[dict[str, Any]]:
        return self.goal_store.list()

    def get_goal_plan(self, goal_id: str) -> dict[str, Any]:
        return self.goal_workflow.plan(goal_id)

    def get_goal_events(self, goal_id: str) -> dict[str, Any]:
        return self.goal_workflow.events(goal_id)

    def pause_goal(self, goal_id: str) -> dict[str, Any]:
        return self.goal_workflow.pause(goal_id)

    def resume_goal(self, goal_id: str) -> dict[str, Any]:
        return self.goal_workflow.resume(goal_id)

    def list_runs(
        self,
        run_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.run_store.list(run_type=run_type, limit=limit)

    def latest_run(self, run_type: str | None = None) -> dict[str, Any] | None:
        return self.run_store.latest(run_type=run_type)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.run_store.get_dict(run_id)

    def _attach_ask_run(
        self,
        question: str,
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        try:
            run = self.run_store.record_ask(question, context, result)
            result["run_id"] = run.id
            if result.get("tool_builder"):
                tool_run = self.run_store.record_tool(question, context, result)
                result["tool_run_id"] = tool_run.id
        except Exception as exc:
            result.setdefault("errors", []).append(f"run_store_failed:{exc}")

    def _record_failed_ask_run(
        self,
        question: str,
        context: dict[str, Any],
        exc: Exception,
    ) -> None:
        try:
            self.run_store.record_ask(
                question,
                context,
                {"answer": "", "errors": [str(exc)]},
                status="failed",
                errors=[str(exc)],
            )
        except Exception:
            return

    def _attach_goal_run(
        self,
        result: dict[str, Any],
        input_data: dict[str, Any],
        run_id: str | None = None,
    ) -> None:
        try:
            run = self.run_store.record_goal(result, input_data=input_data, run_id=run_id)
            result["run_id"] = run.id
        except Exception as exc:
            result.setdefault("errors", []).append(f"run_store_failed:{exc}")


def _list_yaml_dicts(path) -> list[dict[str, Any]]:
    import yaml

    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    for item in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(item.read_text(encoding="utf-8")) or {}
        data["_path"] = str(item)
        items.append(data)
    return items


def _list_yaml_dicts_many(paths) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for item in _list_yaml_dicts(path):
            item_id = str(item.get("id") or item.get("_path"))
            if item_id in seen:
                continue
            seen.add(item_id)
            items.append(item)
    return items


def _goal_learning_ids(tasks: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for task in tasks:
        output = task.get("output") or {}
        candidate_id = output.get("learning_candidate_id")
        if candidate_id:
            ids.append(str(candidate_id))
        ids.extend(str(item) for item in output.get("learning_candidate_ids", []) if item)
    return list(dict.fromkeys(ids))

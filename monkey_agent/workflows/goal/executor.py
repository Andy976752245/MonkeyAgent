from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from monkey_agent.domains.goals.models import Goal, GoalTask
from monkey_agent.domains.learning.review_store import ReviewStore


AskCallable = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class TaskExecutionResult:
    success: bool
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    learning_candidate_ids: list[str] = field(default_factory=list)

    def to_output(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "answer": self.content,
            "data": self.data,
            "evidence": self.evidence,
            "artifacts": self.artifacts,
            "errors": self.errors,
            "requires_confirmation": self.requires_confirmation,
            "learning_candidate_ids": self.learning_candidate_ids,
            **self.data,
        }


class TaskExecutor(Protocol):
    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        ...


class AskTaskExecutor:
    def __init__(self, ask: AskCallable) -> None:
        self.ask = ask

    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        result = _run_ask_task(
            self.ask,
            goal,
            task,
            {"disable_tool_builder": True},
        )
        errors = [str(item) for item in result.get("errors", []) if item]
        return TaskExecutionResult(
            success=_ask_result_succeeded(result),
            content=str(result.get("answer") or ""),
            data=result,
            evidence=_collect_task_evidence(result),
            errors=errors,
            learning_candidate_ids=_collect_learning_candidate_ids_from_output(result),
        )


class ResearchTaskExecutor:
    def __init__(self, ask: AskCallable) -> None:
        self.ask = ask

    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        result = _run_ask_task(
            self.ask,
            goal,
            task,
            {
                "disable_tool_builder": True,
                "preferred_tool_id": str(task.input.get("capability") or "public_web_search"),
            },
        )
        evidence = _collect_task_evidence(result)
        errors = [str(item) for item in result.get("errors", []) if item]
        return TaskExecutionResult(
            success=_research_result_succeeded(result),
            content=str(result.get("answer") or ""),
            data=result,
            evidence=evidence,
            errors=errors,
            learning_candidate_ids=_collect_learning_candidate_ids_from_output(result),
        )


class ToolBuildTaskExecutor:
    def __init__(self, ask: AskCallable) -> None:
        self.ask = ask

    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        result = _run_ask_task(
            self.ask,
            goal,
            task,
            {
                "force_tool_builder": True,
                "public_evidence": _collect_public_evidence(previous_tasks),
            },
        )
        evidence = _collect_task_evidence(result)
        errors = [str(item) for item in result.get("errors", []) if item]
        requires_confirmation = _requires_tool_confirmation(result)
        return TaskExecutionResult(
            success=_tool_builder_result_succeeded(result),
            content=str(result.get("answer") or ""),
            data=result,
            evidence=evidence,
            errors=errors,
            requires_confirmation=requires_confirmation,
            learning_candidate_ids=_collect_learning_candidate_ids_from_output(result),
        )


class ValidationTaskExecutor:
    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        blocked = [item.task_id for item in previous_tasks if item.status == "blocked"]
        failed = [item.task_id for item in previous_tasks if item.status == "failed"]
        criteria = task.acceptance_criteria or task.input.get("checks", [])
        candidate_ids = _collect_learning_candidate_ids(previous_tasks)
        success = not failed
        message = (
            "目标执行结果已完成基础检查。"
            if success
            else "存在失败任务，需要修正或人工确认。"
        )
        data = {
            "blocked_tasks": blocked,
            "failed_tasks": failed,
            "learning_candidate_ids": candidate_ids,
            "passed_criteria": list(criteria),
            "failed_criteria": ["failed_tasks"] if failed else [],
            "passed": success,
            "message": message,
        }
        return TaskExecutionResult(
            success=success,
            content=message,
            data=data,
            learning_candidate_ids=candidate_ids,
            errors=[f"failed_tasks={failed}"] if failed else [],
        )


class LearningTaskExecutor:
    def __init__(self, review_store: ReviewStore) -> None:
        self.review_store = review_store

    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        existing = _collect_learning_candidate_ids(previous_tasks)
        if existing:
            return TaskExecutionResult(
                success=True,
                content="已复用执行过程中产生的 pending review 候选。",
                data={"learning_candidate_ids": existing},
                learning_candidate_ids=existing,
            )
        if not (goal.force_learning or _explicit_learning_goal(goal.goal)):
            return TaskExecutionResult(
                success=True,
                content="该目标暂按一次性目标处理，仅保留执行观察。",
                data={"learning_candidate_ids": []},
            )
        preferred = str(task.input.get("preferred_kind") or "skill")
        feedback = _feedback_for_kind(goal.goal, preferred)
        candidate_id = self.review_store.create_candidate(
            goal.goal,
            feedback,
            {"goal_id": goal.id, "source": "goal_engine"},
        )
        return TaskExecutionResult(
            success=True,
            content="已生成待审核学习候选。",
            data={"learning_candidate_ids": [candidate_id]},
            learning_candidate_ids=[candidate_id],
        )


class HumanConfirmExecutor:
    def run(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> TaskExecutionResult:
        if not confirm:
            return TaskExecutionResult(
                success=False,
                content="等待用户确认。",
                data={
                    "confirmed": False,
                    "confirmation_prompt": f"任务 {task.task_id} 需要用户确认：{task.title}",
                },
                requires_confirmation=True,
            )
        return TaskExecutionResult(
            success=True,
            content="用户已确认继续执行受控动作。",
            data={"confirmed": True},
        )


class GoalExecutor:
    def __init__(self, ask: AskCallable, review_store: ReviewStore) -> None:
        self.executors: dict[str, TaskExecutor] = {
            "ask": AskTaskExecutor(ask),
            "reasoning": AskTaskExecutor(ask),
            "research": ResearchTaskExecutor(ask),
            "tool_builder": ToolBuildTaskExecutor(ask),
            "tool_build": ToolBuildTaskExecutor(ask),
            "validation": ValidationTaskExecutor(),
            "learning": LearningTaskExecutor(review_store),
            "human_confirm": HumanConfirmExecutor(),
        }

    def execute(
        self,
        goal: Goal,
        task: GoalTask,
        previous_tasks: list[GoalTask],
        confirm: bool = False,
    ) -> GoalTask:
        if task.requires_confirmation and not confirm:
            task.status = "blocked"
            task.output = {
                "success": False,
                "requires_confirmation": True,
                "confirmation_prompt": f"任务 {task.task_id} 需要用户确认：{task.title}",
            }
            task.failure_reason = "requires_confirmation"
            return task

        if task.attempts >= task.max_attempts:
            task.status = "failed"
            task.failure_reason = "max_attempts_exceeded"
            task.output = {"success": False, "errors": ["max_attempts_exceeded"]}
            return task

        task.status = "running"
        task.attempts += 1
        executor = self.executors.get(task.executor or task.type) or self.executors["ask"]
        try:
            result = executor.run(goal, task, previous_tasks, confirm=confirm)
        except Exception as exc:  # noqa: BLE001 - task execution boundary
            task.status = "failed"
            task.failure_reason = str(exc)
            task.output = {"success": False, "errors": [str(exc)]}
            task.result_score = 0.0
            return task

        task.output = result.to_output()
        task.evidence = result.evidence
        task.result_score = 1.0 if result.success else 0.0
        if result.requires_confirmation:
            task.status = "blocked"
            task.requires_confirmation = True
            task.failure_reason = "requires_confirmation"
            task.output.setdefault(
                "confirmation_prompt",
                f"任务 {task.task_id} 需要用户确认：{task.title}",
            )
            return task
        if result.success:
            task.status = "done"
            task.failure_reason = None
        else:
            task.status = "failed"
            task.failure_reason = "; ".join(result.errors) or "task_failed"
        return task


def _run_ask_task(
    ask: AskCallable,
    goal: Goal,
    task: GoalTask,
    extra_context: dict[str, Any],
) -> dict[str, Any]:
    question = str(task.input.get("question") or goal.goal)
    context = {
        "goal_id": goal.id,
        "goal": goal.goal,
        "disable_adoption": True,
        **{key: value for key, value in task.input.items() if key != "question"},
        **extra_context,
    }
    result = ask(question, context)
    return {
        "answer": result.get("answer", ""),
        "route": result.get("route"),
        "task_type": result.get("task_type"),
        "confidence": result.get("confidence"),
        "learning_candidate_id": result.get("learning_candidate_id"),
        "adoption_prompt": result.get("adoption_prompt"),
        "exploration": result.get("exploration", {}),
        "tool_builder": result.get("tool_builder", {}),
        "deterministic_results": result.get("deterministic_results", []),
        "errors": result.get("errors", []),
    }


def _ask_result_succeeded(result: dict[str, Any]) -> bool:
    if result.get("route") == "need_more_info":
        return False
    if result.get("clarification_questions"):
        return False
    if str(result.get("answer") or "").strip():
        return True
    return bool(result.get("deterministic_results"))


def _research_result_succeeded(result: dict[str, Any]) -> bool:
    if _collect_task_evidence(result):
        return True
    if isinstance(result.get("exploration"), dict) and result["exploration"]:
        return True
    return bool(str(result.get("answer") or "").strip())


def _tool_builder_result_succeeded(result: dict[str, Any]) -> bool:
    tool_builder = result.get("tool_builder")
    if isinstance(tool_builder, dict) and tool_builder:
        return bool(tool_builder.get("success"))
    return _ask_result_succeeded(result)


def _collect_public_evidence(tasks: list[GoalTask]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for task in tasks:
        for item in task.evidence:
            if isinstance(item, dict):
                evidence.append(item)
    return evidence


def _collect_task_evidence(output: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    exploration = output.get("exploration", {}) if isinstance(output, dict) else {}
    data = exploration.get("data", {}) if isinstance(exploration, dict) else {}
    if isinstance(data, dict):
        results.extend(item for item in data.get("results", []) if isinstance(item, dict))
    for item in output.get("deterministic_results", []) if isinstance(output, dict) else []:
        if isinstance(item, dict):
            results.append(item)
    tool_builder = output.get("tool_builder", {}) if isinstance(output, dict) else {}
    if isinstance(tool_builder, dict) and tool_builder:
        results.append(
            {
                "source": "tool_builder",
                "summary": str(tool_builder.get("stage") or tool_builder),
                "success": tool_builder.get("success"),
                "tool_id": tool_builder.get("tool_id"),
            }
        )
    return results


def _collect_learning_candidate_ids(tasks: list[GoalTask]) -> list[str]:
    ids: list[str] = []
    for task in tasks:
        ids.extend(_collect_learning_candidate_ids_from_output(task.output or {}))
    return list(dict.fromkeys(ids))


def _collect_learning_candidate_ids_from_output(output: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    candidate_id = output.get("learning_candidate_id")
    if candidate_id:
        ids.append(str(candidate_id))
    ids.extend(str(item) for item in output.get("learning_candidate_ids", []) if item)
    return list(dict.fromkeys(ids))


def _requires_tool_confirmation(output: dict[str, Any]) -> bool:
    exploration = output.get("exploration", {})
    if isinstance(exploration, dict) and exploration.get("error") == "permission_confirmation_required":
        return True
    tool_builder = output.get("tool_builder", {})
    if isinstance(tool_builder, dict) and tool_builder:
        if tool_builder.get("permission") == "confirm":
            return True
        if tool_builder.get("read_only") is False:
            return True
    for item in output.get("deterministic_results", []) if isinstance(output, dict) else []:
        if isinstance(item, dict) and item.get("permission") == "confirm":
            return True
    return False


def _explicit_learning_goal(goal: str) -> bool:
    return any(hint in goal for hint in ["沉淀", "以后", "记住", "复用", "规则", "Skill", "skill"])


def _feedback_for_kind(goal: str, preferred: str) -> str:
    if preferred == "memory":
        return f"以后遇到类似目标时，按本次目标经验处理：{goal}"
    if preferred == "rule":
        return f"将该目标中已验证的稳定工具调用或固定口径沉淀为规则：{goal}"
    return f"将该目标的可复用流程沉淀为 Skill：{goal}"

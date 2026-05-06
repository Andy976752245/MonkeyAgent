from __future__ import annotations

from typing import Any

from monkey_agent.domains.evaluation.llm_judge import LLMJudge
from monkey_agent.domains.evaluation.local_checks import (
    check_answer_not_empty,
    check_clarification_specificity,
    check_counterexamples,
    check_deterministic_result_used,
    check_evidence_available,
    check_rule_value_consistency,
    check_tool_builder_safety,
    check_tool_error_not_hidden,
)
from monkey_agent.domains.evaluation.models import EvaluationCheck, EvaluationResult


class AskEvaluator:
    def __init__(self, chat_model: Any | None = None) -> None:
        self.llm_judge = LLMJudge(chat_model) if chat_model is not None else None

    def evaluate(self, state: dict[str, Any]) -> EvaluationResult:
        checks = [
            check_answer_not_empty(state),
            check_rule_value_consistency(state),
            check_deterministic_result_used(state),
            check_tool_error_not_hidden(state),
            check_evidence_available(state),
            check_clarification_specificity(state),
        ]
        counter_check, hits = check_counterexamples(state)
        checks.append(counter_check)
        if self.llm_judge is not None:
            checks.extend(self.llm_judge.judge_answer(state))
        requires_confirmation = bool(state.get("requires_confirmation"))
        if str(state.get("route") or "") == "need_more_info":
            requires_confirmation = True
        return EvaluationResult.from_checks(
            checks,
            requires_confirmation=requires_confirmation,
            counterexample_hits=hits,
        )


class ToolBuilderEvaluator:
    def evaluate(self, tool_builder: dict[str, Any]) -> EvaluationResult:
        checks = check_tool_builder_safety(tool_builder)
        requires_confirmation = False
        metadata = tool_builder.get("metadata") if isinstance(tool_builder, dict) else None
        if isinstance(metadata, dict):
            requires_confirmation = (
                str(metadata.get("permission") or "") == "confirm"
                or metadata.get("read_only") is False
            )
        result = EvaluationResult.from_checks(
            checks,
            requires_confirmation=requires_confirmation,
            summary="Tool Builder 评估完成。",
        )
        if any(not check.passed and check.severity == "error" for check in checks):
            result.status = "failed"
            result.requires_confirmation = False
            result.summary = "Tool Builder 评估失败。"
        return result


class GoalEvaluatorService:
    def evaluate(self, goal: Any, tasks: list[Any]) -> EvaluationResult:
        checks: list[EvaluationCheck] = []
        blocked = [task for task in tasks if task.status == "blocked"]
        failed = [task for task in tasks if task.status == "failed"]
        done = [task for task in tasks if task.status == "done"]
        pending = [task for task in tasks if task.status == "pending"]
        for task in done:
            checks.append(
                EvaluationCheck(
                    f"task_done:{task.task_id}",
                    True,
                    f"任务已完成：{task.title}",
                    data={"result_score": task.result_score},
                )
            )
            if (task.output or {}).get("errors"):
                checks.append(
                    EvaluationCheck(
                        f"task_warning:{task.task_id}",
                        False,
                        f"任务有可用输出但存在告警：{'; '.join(str(item) for item in task.output.get('errors', []))}",
                        "warning",
                    )
                )
        for task in failed:
            has_usable_output = bool((task.output or {}).get("answer") or (task.output or {}).get("content"))
            checks.append(
                EvaluationCheck(
                    f"task_failed:{task.task_id}",
                    has_usable_output,
                    f"任务失败：{task.failure_reason or 'task_failed'}",
                    "warning" if has_usable_output else "error",
                )
            )
        for task in blocked:
            checks.append(
                EvaluationCheck(
                    f"task_waiting_confirmation:{task.task_id}",
                    False,
                    "任务涉及受控动作，需要人工确认。",
                    "warning",
                )
            )
        if not tasks:
            checks.append(EvaluationCheck("goal_has_tasks", False, "目标没有任务。", "error"))
        elif not pending and not failed and not blocked and len(done) == len(tasks):
            checks.append(EvaluationCheck("goal_all_tasks_done", True, "所有任务已完成。"))
        elif pending:
            checks.append(
                EvaluationCheck(
                    "goal_has_pending_tasks",
                    True,
                    "目标仍有待执行任务。",
                    data={"pending_count": len(pending)},
                )
            )
        result = EvaluationResult.from_checks(
            checks,
            requires_confirmation=bool(blocked),
            summary="Goal 评估完成。",
        )
        result.score = _goal_score(done, tasks, failed, blocked)
        if blocked:
            result.status = "waiting_human"
        elif any(check.name.startswith("task_failed:") and check.severity == "error" for check in checks):
            result.status = "needs_revision"
        elif not pending and len(done) == len(tasks) and tasks:
            result.status = "pass"
            result.score = 1.0
        else:
            result.status = "pass"
        return result


def _goal_score(done: list[Any], tasks: list[Any], failed: list[Any], blocked: list[Any]) -> float:
    if not tasks:
        return 0.0
    score = len(done) / len(tasks)
    if failed:
        score -= 0.2
    if blocked:
        score = min(score, 0.8)
    return round(max(0.0, min(1.0, score)), 3)

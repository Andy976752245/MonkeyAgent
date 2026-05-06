from __future__ import annotations

from typing import Any

from monkey_agent.domains.evaluation import GoalEvaluatorService
from monkey_agent.domains.goals.models import Goal, GoalTask


class GoalEvaluator:
    def __init__(self) -> None:
        self.service = GoalEvaluatorService()

    def evaluate(self, goal: Goal, tasks: list[GoalTask]) -> dict[str, Any]:
        blocked = [task for task in tasks if task.status == "blocked"]
        failed = [task for task in tasks if task.status == "failed"]
        done = [task for task in tasks if task.status == "done"]
        pending = [task for task in tasks if task.status == "pending"]
        passed_criteria = _passed_criteria(done)
        failed_criteria = _failed_criteria(failed)
        evaluation = self.service.evaluate(goal, tasks).to_dict()

        if blocked:
            return {
                **evaluation,
                "status": "waiting_human",
                "score": _score(done, tasks),
                "summary": "目标执行已暂停，等待用户确认受控动作。",
                "requires_confirmation": True,
                "confirmation_prompt": _confirmation_prompt(blocked),
                "passed_criteria": passed_criteria,
                "failed_criteria": failed_criteria,
                "next_action": "need_human",
                "revision_instruction": "",
            }

        if failed:
            can_revise = goal.revision_count < goal.max_revisions
            return {
                **evaluation,
                "status": "active" if can_revise else "failed",
                "score": _score(done, tasks),
                "summary": (
                    "目标执行存在失败任务，准备修正计划。"
                    if can_revise
                    else "目标执行失败，已达到最大修正次数。"
                ),
                "requires_confirmation": False,
                "confirmation_prompt": None,
                "passed_criteria": passed_criteria,
                "failed_criteria": failed_criteria,
                "next_action": "revise_plan" if can_revise else "failed",
                "revision_instruction": _revision_instruction(failed),
            }

        if pending:
            return {
                **evaluation,
                "status": "active",
                "score": _score(done, tasks),
                "summary": "目标正在分步执行。",
                "requires_confirmation": False,
                "confirmation_prompt": None,
                "passed_criteria": passed_criteria,
                "failed_criteria": failed_criteria,
                "next_action": "continue",
                "revision_instruction": "",
            }

        if all(task.status == "done" for task in tasks):
            return {
                **evaluation,
                "status": "completed",
                "score": 1.0,
                "summary": "目标执行完成，已输出结果并记录可沉淀候选。",
                "requires_confirmation": False,
                "confirmation_prompt": None,
                "passed_criteria": passed_criteria or goal.success_criteria,
                "failed_criteria": [],
                "next_action": "finish",
                "revision_instruction": "",
            }

        return {
            **evaluation,
            "status": "active",
            "score": _score(done, tasks),
            "summary": "目标正在分步执行。",
            "requires_confirmation": False,
            "confirmation_prompt": None,
            "passed_criteria": passed_criteria,
            "failed_criteria": failed_criteria,
            "next_action": "continue",
            "revision_instruction": "",
        }


def _confirmation_prompt(blocked: list[GoalTask]) -> str | None:
    task = blocked[0] if blocked else None
    if task is None:
        return None
    return str(
        task.output.get("confirmation_prompt")
        or f"任务 {task.task_id} 需要确认后才能继续。"
    )


def _passed_criteria(tasks: list[GoalTask]) -> list[str]:
    criteria: list[str] = []
    for task in tasks:
        criteria.extend(task.acceptance_criteria)
    return list(dict.fromkeys(criteria))


def _failed_criteria(tasks: list[GoalTask]) -> list[str]:
    criteria: list[str] = []
    for task in tasks:
        if task.failure_reason:
            criteria.append(f"{task.task_id}: {task.failure_reason}")
        criteria.extend(task.acceptance_criteria)
    return list(dict.fromkeys(criteria))


def _revision_instruction(tasks: list[GoalTask]) -> str:
    failures = ", ".join(
        f"{task.task_id}({task.failure_reason or 'failed'})" for task in tasks
    )
    return f"请针对失败任务生成补充验证或替代执行步骤：{failures}"


def _score(done: list[GoalTask], tasks: list[GoalTask]) -> float:
    if not tasks:
        return 0.0
    return round(len(done) / len(tasks), 3)

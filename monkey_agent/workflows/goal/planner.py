from __future__ import annotations

import json
import re
from typing import Any, Protocol

from monkey_agent.domains.goals.models import Goal, GoalTask
from monkey_agent.domains.models.bailian import ChatModel


INTEGRATION_HINTS = ("接入", "对接", "API", "接口", "机器人", "webhook", "Webhook", "飞书", "发送")
WRITE_HINTS = ("发送", "写入", "创建", "删除", "更新", "同步", "通知", "推送", "发一条")
SEARCH_HINTS = ("搜索", "查询", "查一下", "公开", "文档", "资料", "最新", "赛程", "天气")
PERSONAL_HINTS = ("准备", "拜访", "会议", "计划", "沟通", "建议", "应该", "怎么办")
LEARNING_HINTS = ("沉淀", "以后", "记住", "复用", "规则", "Skill", "skill")
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


class GoalPlannerProtocol(Protocol):
    def plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
    ) -> tuple[list[str], list[GoalTask]]:
        ...

    def revise(
        self,
        goal: Goal,
        tasks: list[GoalTask],
        evaluation: dict[str, Any],
    ) -> list[GoalTask]:
        ...


class LLMGoalPlanner:
    def __init__(self, chat_model: ChatModel) -> None:
        self.chat_model = chat_model

    def plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
    ) -> tuple[list[str], list[GoalTask]]:
        prompt_context = {
            **(context or {}),
            "max_steps": max_steps,
            "required_json": {
                "goal_type": "integration | research | personal_assistant | general",
                "success_criteria": ["criterion"],
                "tasks": [
                    {
                        "task_id": "task_001",
                        "title": "任务标题",
                        "type": "research | tool_build | reasoning | validation | learning | human_confirm",
                        "executor": "research | tool_builder | ask | validation | learning | human_confirm",
                        "depends_on": [],
                        "risk": "low | medium | high",
                        "requires_confirmation": False,
                        "acceptance_criteria": ["验收标准"],
                        "input": {},
                    }
                ],
                "dependencies": [{"task_id": "task_002", "depends_on": ["task_001"]}],
                "risk_assessment": "summary",
                "required_tools": ["tool id"],
                "expected_artifacts": ["artifact"],
                "learning_opportunities": ["rule | skill | memory"],
            },
        }
        text = self.chat_model.generate(
            "请把下面目标拆成 MonkeyAgent 可执行 DAG 计划，只输出严格 JSON，不要 Markdown。\n"
            f"目标：{goal}",
            [],
            [],
            prompt_context,
        )
        data = _parse_json_object(text)
        tasks_raw = data.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            raise ValueError("llm planner returned no tasks")
        criteria = [str(item) for item in data.get("success_criteria", []) if item]
        tasks = [_task_from_plan_item(item, index) for index, item in enumerate(tasks_raw, start=1)]
        _apply_dependencies_from_plan(tasks, data.get("dependencies"))
        _enforce_write_confirmation(goal, tasks)
        return criteria or ["完成目标并输出可验证结果。"], tasks

    def revise(
        self,
        goal: Goal,
        tasks: list[GoalTask],
        evaluation: dict[str, Any],
    ) -> list[GoalTask]:
        text = self.chat_model.generate(
            "请基于当前目标执行失败/不足，生成增量修正任务 JSON，字段 tasks。只输出 JSON。\n"
            f"目标：{goal.goal}",
            [],
            [],
            {
                "tasks": [task.to_dict() for task in tasks],
                "evaluation": evaluation,
                "plan_version": goal.plan_version,
            },
        )
        data = _parse_json_object(text)
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list):
            return []
        existing = {task.task_id for task in tasks}
        additions: list[GoalTask] = []
        for index, item in enumerate(raw_tasks, start=1):
            task = _task_from_plan_item(item, len(tasks) + index)
            if task.task_id in existing:
                task.task_id = _next_task_id(tasks + additions)
            additions.append(task)
        _enforce_write_confirmation(goal.goal, additions)
        return additions


class HeuristicGoalPlanner:
    def plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
    ) -> tuple[list[str], list[GoalTask]]:
        context = context or {}
        if _has(goal, INTEGRATION_HINTS):
            return _integration_plan(goal)
        if _has(goal, SEARCH_HINTS):
            return _research_plan(goal)
        if _has(goal, PERSONAL_HINTS):
            return _personal_plan(goal)
        return _general_plan(goal, bool(context.get("force_learning")))

    def revise(
        self,
        goal: Goal,
        tasks: list[GoalTask],
        evaluation: dict[str, Any],
    ) -> list[GoalTask]:
        failed = [task.task_id for task in tasks if task.status == "failed"]
        blocked = [task.task_id for task in tasks if task.status == "blocked"]
        if failed:
            return [
                GoalTask(
                    task_id=_next_task_id(tasks),
                    title="修正失败任务并重新验证",
                    type="validation",
                    executor="validation",
                    input={"checks": ["failed_tasks", "revision"], "failed_tasks": failed},
                    depends_on=[],
                    acceptance_criteria=["失败原因已明确，给出下一步处理方式。"],
                    risk="low",
                    priority=30,
                )
            ]
        if blocked:
            return [
                GoalTask(
                    task_id=_next_task_id(tasks),
                    title="等待用户确认后继续",
                    type="human_confirm",
                    executor="human_confirm",
                    input={"reason": "计划修正检测到受控动作。"},
                    requires_confirmation=True,
                    risk="medium",
                    priority=20,
                )
            ]
        return []


class CompositeGoalPlanner:
    def __init__(
        self,
        chat_model: ChatModel | None = None,
        heuristic: HeuristicGoalPlanner | None = None,
    ) -> None:
        self.llm = LLMGoalPlanner(chat_model) if chat_model is not None else None
        self.heuristic = heuristic or HeuristicGoalPlanner()

    def plan(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
    ) -> tuple[list[str], list[GoalTask]]:
        if self.llm is not None:
            try:
                return self.llm.plan(goal, context, max_steps)
            except Exception:
                pass
        return self.heuristic.plan(goal, context, max_steps)

    def revise(
        self,
        goal: Goal,
        tasks: list[GoalTask],
        evaluation: dict[str, Any],
    ) -> list[GoalTask]:
        if self.llm is not None:
            try:
                additions = self.llm.revise(goal, tasks, evaluation)
                if additions:
                    return additions
            except Exception:
                pass
        return self.heuristic.revise(goal, tasks, evaluation)

def _integration_plan(goal: str) -> tuple[list[str], list[GoalTask]]:
    is_write = _has(goal, WRITE_HINTS)
    tasks = [
        GoalTask(
            task_id="task_001",
            title="搜索公开资料和接口线索",
            type="research",
            executor="research",
            input={"question": f"搜索公开资料：{goal}", "capability": "public_web_search"},
            risk="low",
            acceptance_criteria=["获得接口、鉴权、输入输出或公开文档线索。"],
            priority=10,
        ),
        GoalTask(
            task_id="task_002",
            title="生成或复用可执行工具",
            type="tool_build",
            executor="tool_builder",
            input={"question": goal, "force_tool_builder": True},
            risk="medium" if is_write else "low",
            depends_on=["task_001"],
            acceptance_criteria=["生成工具候选并通过静态检查或 dry-run。"],
            priority=20,
        ),
        GoalTask(
            task_id="task_003",
            title="验证工具 dry-run 结果和权限",
            type="validation",
            executor="validation",
            input={"checks": ["tool_registered", "dry_run", "permission_policy"]},
            depends_on=["task_002"],
            risk="low",
            acceptance_criteria=["工具状态、权限和失败兜底已检查。"],
            priority=30,
        ),
        GoalTask(
            task_id="task_004",
            title="沉淀可复用能力候选",
            type="learning",
            executor="learning",
            input={"preferred_kind": "rule"},
            depends_on=["task_003"],
            risk="low",
            acceptance_criteria=["已生成或复用用户级 pending 候选。"],
            priority=40,
        ),
    ]
    if is_write:
        tasks.append(
            GoalTask(
                task_id="task_005",
                title="等待用户确认外部写操作",
                type="human_confirm",
                executor="human_confirm",
                input={"reason": "该目标涉及外部写操作或消息发送。"},
                depends_on=["task_004"],
                requires_confirmation=True,
                risk="medium",
                acceptance_criteria=["用户明确确认后才允许继续副作用动作。"],
                priority=50,
            )
        )
    return ["工具可 dry-run 验证。", "写操作执行前必须得到用户确认。"], tasks


def _research_plan(goal: str) -> tuple[list[str], list[GoalTask]]:
    tasks = [
        GoalTask(
            task_id="task_001",
            title="搜索公开资料",
            type="research",
            executor="research",
            input={"question": f"搜索公开资料：{goal}", "capability": "public_web_search"},
            risk="low",
            acceptance_criteria=["得到至少一条可引用的公开资料或明确说明无结果。"],
            priority=10,
        ),
        GoalTask(
            task_id="task_002",
            title="基于证据生成回答",
            type="reasoning",
            executor="ask",
            input={"question": goal},
            depends_on=["task_001"],
            risk="low",
            acceptance_criteria=["回答区分事实、推断和不确定项。"],
            priority=20,
        ),
        GoalTask(
            task_id="task_003",
            title="判断是否需要沉淀 Skill",
            type="learning",
            executor="learning",
            input={"preferred_kind": "skill"},
            depends_on=["task_002"],
            risk="low",
            acceptance_criteria=["一次性问题只记录观察，复用价值明确才生成候选。"],
            priority=30,
        ),
    ]
    return ["给出答案并标注公开资料来源。"], tasks


def _personal_plan(goal: str) -> tuple[list[str], list[GoalTask]]:
    tasks = [
        GoalTask(
            task_id="task_001",
            title="生成个人助理建议",
            type="reasoning",
            executor="ask",
            input={"question": goal},
            risk="low",
            acceptance_criteria=["输出可直接执行的准备清单或行动建议。"],
            priority=10,
        ),
        GoalTask(
            task_id="task_002",
            title="检查建议是否需要更多背景",
            type="validation",
            executor="validation",
            input={"checks": ["actionable", "clarification_questions"]},
            depends_on=["task_001"],
            risk="low",
            acceptance_criteria=["识别缺失背景，但不阻塞基础建议输出。"],
            priority=20,
        ),
        GoalTask(
            task_id="task_003",
            title="判断是否沉淀为偏好或 Skill",
            type="learning",
            executor="learning",
            input={"preferred_kind": "memory" if _has(goal, LEARNING_HINTS) else "skill"},
            depends_on=["task_002"],
            risk="low",
            acceptance_criteria=["只有用户明确要求或重复出现时才沉淀。"],
            priority=30,
        ),
    ]
    return ["输出可执行建议。", "只有用户明确要求或重复出现时才沉淀。"], tasks


def _general_plan(goal: str, force_learning: bool) -> tuple[list[str], list[GoalTask]]:
    tasks = [
        GoalTask(
            task_id="task_001",
            title="理解目标并尝试回答",
            type="reasoning",
            executor="ask",
            input={"question": goal},
            risk="low",
            acceptance_criteria=["给出可执行结果或明确下一步。"],
            priority=10,
        ),
        GoalTask(
            task_id="task_002",
            title="评估完成度",
            type="validation",
            executor="validation",
            input={"checks": ["answer", "confidence", "next_step"]},
            depends_on=["task_001"],
            risk="low",
            acceptance_criteria=["回答经过基础完成度检查。"],
            priority=20,
        ),
    ]
    if force_learning or _has(goal, LEARNING_HINTS):
        tasks.append(
            GoalTask(
                task_id="task_003",
                title="沉淀可复用经验候选",
                type="learning",
                executor="learning",
                input={"preferred_kind": "skill"},
                depends_on=["task_002"],
                risk="low",
                acceptance_criteria=["生成用户级 pending 候选。"],
                priority=30,
            )
        )
    return ["给出可执行结果或明确下一步。"], tasks


def _task_from_plan_item(item: Any, index: int) -> GoalTask:
    if not isinstance(item, dict):
        item = {}
    task_type = str(item.get("type") or item.get("executor") or "reasoning")
    executor = str(item.get("executor") or _executor_for_type(task_type))
    return GoalTask(
        task_id=str(item.get("task_id") or f"task_{index:03d}"),
        title=str(item.get("title") or f"任务 {index}"),
        type=task_type,
        executor=executor,
        input=dict(item.get("input") or {}),
        depends_on=[str(dep) for dep in item.get("depends_on", []) or []],
        requires_confirmation=bool(item.get("requires_confirmation", False)),
        risk=str(item.get("risk") or "low"),
        acceptance_criteria=[
            str(criterion) for criterion in item.get("acceptance_criteria", []) or []
        ],
        max_attempts=int(item.get("max_attempts") or 2),
        priority=int(item.get("priority") or index * 10),
    )


def _apply_dependencies_from_plan(tasks: list[GoalTask], dependencies: Any) -> None:
    by_id = {task.task_id: task for task in tasks}
    if not isinstance(dependencies, list):
        return
    for item in dependencies:
        if not isinstance(item, dict):
            continue
        task = by_id.get(str(item.get("task_id")))
        if task is None:
            continue
        task.depends_on = [str(dep) for dep in item.get("depends_on", []) or []]


def _enforce_write_confirmation(goal: str | Goal, tasks: list[GoalTask]) -> None:
    text = goal.goal if isinstance(goal, Goal) else goal
    is_write = _has(text, WRITE_HINTS)
    for task in tasks:
        if task.risk in {"medium", "high"} and is_write:
            if task.executor in {"human_confirm", "validation", "learning", "research"}:
                continue
            task.requires_confirmation = True


def _executor_for_type(task_type: str) -> str:
    mapping = {
        "research": "research",
        "tool_build": "tool_builder",
        "reasoning": "ask",
        "validation": "validation",
        "learning": "learning",
        "human_confirm": "human_confirm",
    }
    return mapping.get(task_type, "ask")


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _next_task_id(tasks: list[GoalTask]) -> str:
    existing = {task.task_id for task in tasks}
    index = len(existing) + 1
    while f"task_{index:03d}" in existing:
        index += 1
    return f"task_{index:03d}"


def _has(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)

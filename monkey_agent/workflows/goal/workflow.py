from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from monkey_agent.domains.goals.models import Goal, GoalEvent, GoalRunResult, GoalTask
from monkey_agent.domains.goals.store import GoalStore
from monkey_agent.workflows.goal.evaluator import GoalEvaluator
from monkey_agent.workflows.goal.executor import GoalExecutor
from monkey_agent.workflows.goal.planner import GoalPlannerProtocol


class GoalGraphState(TypedDict, total=False):
    goal_id: str
    thread_id: str
    mode: str
    goal: str
    context: dict[str, Any]
    goal_record: dict[str, Any]
    tasks: list[dict[str, Any]]
    events: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    status: str
    summary: str
    current_task: dict[str, Any]
    next_action: str
    execution_path: list[str]
    max_steps: int
    step_budget: int
    step_budget_exhausted: bool
    run_steps: int
    autonomy_policy: str
    success_criteria: list[str]
    force_learning: bool
    confirm: bool
    interrupt_payload: dict[str, Any] | None
    interrupted: bool
    resume_required: bool
    checkpointed: bool
    checkpoint_backend: str
    last_checkpoint: str
    errors: list[str]


class LangGraphGoalWorkflow:
    def __init__(
        self,
        store: GoalStore,
        planner: GoalPlannerProtocol,
        executor: GoalExecutor,
        evaluator: GoalEvaluator,
    ) -> None:
        self.store = store
        self.planner = planner
        self.executor = executor
        self.evaluator = evaluator
        self.checkpointer, self.checkpoint_backend, self._checkpointer_context = _build_checkpointer(
            store.checkpoint_path
        )
        self.graph = self._build_graph().compile(checkpointer=self.checkpointer)

    def start(
        self,
        goal_text: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 5,
        autonomy_policy: str = "read_only_auto_write_confirm",
        success_criteria: list[str] | None = None,
        force_learning: bool = False,
    ) -> dict[str, Any]:
        goal_id = self.store.new_goal_id()
        state: GoalGraphState = {
            "goal_id": goal_id,
            "thread_id": goal_id,
            "mode": "start",
            "goal": goal_text,
            "context": {**(context or {}), "force_learning": force_learning},
            "tasks": [],
            "events": [],
            "evidence": [],
            "evaluations": [],
            "status": "active",
            "summary": "",
            "execution_path": [],
            "max_steps": max_steps,
            "step_budget": 0,
            "run_steps": 0,
            "autonomy_policy": autonomy_policy,
            "success_criteria": success_criteria or [],
            "force_learning": force_learning,
            "confirm": False,
            "checkpointed": True,
            "checkpoint_backend": self.checkpoint_backend,
        }
        config = _config(goal_id)
        result = self.graph.invoke(state, config=config)
        snapshot = self.graph.get_state(config)
        values = dict(snapshot.values or result or {})
        return self._result_from_state(
            values,
            answer="目标已创建，已完成任务拆解。请执行 goal step 推进。",
            last_checkpoint=_checkpoint_id(snapshot),
        )

    def step(self, goal_id: str, confirm: bool = False) -> dict[str, Any]:
        config = _config(goal_id)
        snapshot = self.graph.get_state(config)
        values = dict(snapshot.values or {})
        if not values:
            values = self._state_from_projection(goal_id)
        if not values:
            raise FileNotFoundError(f"goal not found: {goal_id}")
        if values.get("status") == "paused":
            return self._result_from_state(
                values,
                answer="目标已暂停。",
                last_checkpoint=_checkpoint_id(snapshot),
            )

        if confirm and snapshot.next:
            result = self.graph.invoke(Command(resume={"approved": True}), config=config)
        else:
            goal_record = dict(values.get("goal_record") or {})
            result = self.graph.invoke(
                {
                    **values,
                    "mode": "step",
                    "confirm": confirm,
                    "step_budget": max(1, min(int(goal_record.get("max_steps") or values.get("max_steps") or 5), 5)),
                    "run_steps": 0,
                    "interrupted": False,
                    "resume_required": False,
                    "interrupt_payload": None,
                    "checkpointed": True,
                    "checkpoint_backend": self.checkpoint_backend,
                },
                config=config,
            )

        snapshot = self.graph.get_state(config)
        interrupted, payload = _interrupt_payload(result, snapshot)
        latest = dict(snapshot.values or result or values)
        if interrupted:
            path = list(latest.get("execution_path", []))
            if "ask_human" not in path:
                path.append("ask_human")
            latest.update(
                {
                    "interrupted": True,
                    "resume_required": True,
                    "interrupt_payload": payload,
                    "status": "waiting_human",
                    "execution_path": path,
                }
            )
            self._project(latest)
        return self._result_from_state(
            latest,
            answer=_answer(_goal_from_state(latest), _tasks_from_state(latest)),
            interrupted=interrupted,
            interrupt_payload=payload,
            last_checkpoint=_checkpoint_id(snapshot),
        )

    def plan(self, goal_id: str) -> dict[str, Any]:
        state = self._state_for_read(goal_id)
        data = self.store.get(goal_id)
        return {
            "goal_id": goal_id,
            "thread_id": goal_id,
            "checkpointed": True,
            "checkpoint_backend": self.checkpoint_backend,
            "plan_version": data.get("plan_version", 1),
            "revision_count": data.get("revision_count", 0),
            "success_criteria": data.get("success_criteria", []),
            "tasks": data.get("tasks", []) or list(state.get("tasks", [])),
        }

    def events(self, goal_id: str) -> dict[str, Any]:
        config = _config(goal_id)
        snapshot = self.graph.get_state(config)
        state = self._state_for_read(goal_id)
        return {
            "goal_id": goal_id,
            "thread_id": goal_id,
            "checkpointed": True,
            "checkpoint_backend": self.checkpoint_backend,
            "last_checkpoint": _checkpoint_id(snapshot),
            "checkpoint_summary": _checkpoint_summary(snapshot),
            "events": self.store.load_events(goal_id) or list(state.get("events", [])),
            "evidence": self.store.load_evidence(goal_id) or list(state.get("evidence", [])),
            "evaluations": self.store.load_evaluations(goal_id) or list(state.get("evaluations", [])),
        }

    def status(self, goal_id: str) -> dict[str, Any]:
        state = self._state_for_read(goal_id)
        config = _config(goal_id)
        snapshot = self.graph.get_state(config)
        return self._result_from_state(
            state,
            answer=_answer(_goal_from_state(state), _tasks_from_state(state)),
            last_checkpoint=_checkpoint_id(snapshot),
        )

    def pause(self, goal_id: str) -> dict[str, Any]:
        config = _config(goal_id)
        values = dict(self.graph.get_state(config).values or self._state_from_projection(goal_id))
        if not values:
            raise FileNotFoundError(f"goal not found: {goal_id}")
        goal = _goal_from_state(values)
        goal.status = "paused"
        goal.summary = "目标已暂停。"
        values.update(
            {
                "goal_record": goal.to_dict(),
                "status": goal.status,
                "summary": goal.summary,
                "events": _append_event(values, "goal_paused"),
                "next_action": "paused",
                "execution_path": list(values.get("execution_path", [])) + ["goal_pause"],
            }
        )
        self.graph.update_state(config, values)
        self._project(values)
        return self._result_from_state(values, answer="目标已暂停。")

    def resume(self, goal_id: str) -> dict[str, Any]:
        config = _config(goal_id)
        values = dict(self.graph.get_state(config).values or self._state_from_projection(goal_id))
        if not values:
            raise FileNotFoundError(f"goal not found: {goal_id}")
        goal = _goal_from_state(values)
        if goal.status == "paused":
            goal.status = "active"
            goal.summary = "目标已恢复。"
            values.update(
                {
                    "goal_record": goal.to_dict(),
                    "status": goal.status,
                    "summary": goal.summary,
                    "events": _append_event(values, "goal_resumed"),
                    "next_action": "continue",
                    "execution_path": list(values.get("execution_path", [])) + ["goal_resume"],
                }
            )
            self.graph.update_state(config, values)
            self._project(values)
        return self._result_from_state(values, answer="目标已恢复。")

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(GoalGraphState)
        graph.add_node("goal_intake", self._goal_intake)
        graph.add_node("decompose_goal", self._decompose_goal)
        graph.add_node("plan_tasks", self._plan_tasks)
        graph.add_node("select_next_task", self._select_next_task)
        graph.add_node("execute_task", self._execute_task)
        graph.add_node("observe_result", self._observe_result)
        graph.add_node("evaluate_progress", self._evaluate_progress)
        graph.add_node("human_interrupt", self._human_interrupt)
        graph.add_node("revise_plan", self._revise_plan)
        graph.add_node("learn_from_goal", self._learn_from_goal)

        graph.add_edge(START, "goal_intake")
        graph.add_edge("goal_intake", "decompose_goal")
        graph.add_edge("decompose_goal", "plan_tasks")
        graph.add_conditional_edges(
            "plan_tasks",
            _after_plan,
            {"start_done": END, "step": "select_next_task"},
        )
        graph.add_conditional_edges(
            "select_next_task",
            _after_select,
            {"execute": "execute_task", "evaluate": "evaluate_progress"},
        )
        graph.add_edge("execute_task", "observe_result")
        graph.add_edge("observe_result", "evaluate_progress")
        graph.add_conditional_edges(
            "evaluate_progress",
            _after_evaluation,
            {
                "continue": "select_next_task",
                "need_human": "human_interrupt",
                "revise_plan": "revise_plan",
                "learn": "learn_from_goal",
                "done": END,
                "failed": END,
            },
        )
        graph.add_edge("human_interrupt", "select_next_task")
        graph.add_edge("revise_plan", "select_next_task")
        graph.add_edge("learn_from_goal", END)
        return graph

    def _goal_intake(self, state: GoalGraphState) -> dict[str, Any]:
        if state.get("goal_record"):
            return {"execution_path": list(state.get("execution_path", [])) + ["goal_intake"]}
        goal = Goal(
            id=str(state["goal_id"]),
            goal=str(state["goal"]),
            max_steps=int(state.get("max_steps") or 5),
            autonomy_policy=str(state.get("autonomy_policy") or "read_only_auto_write_confirm"),
            success_criteria=list(state.get("success_criteria") or ["完成目标并输出可验证结果。"]),
            summary="目标已创建，等待分步执行。",
            force_learning=bool(state.get("force_learning", False)),
        )
        result = {
            "thread_id": goal.id,
            "goal_record": goal.to_dict(),
            "status": goal.status,
            "summary": goal.summary,
            "events": _append_event(
                state,
                "goal_created",
                data={
                    "goal": goal.goal,
                    "context": state.get("context", {}),
                    "task_count": 0,
                },
            ),
            "execution_path": list(state.get("execution_path", [])) + ["goal_intake"],
            "checkpointed": True,
            "checkpoint_backend": self.checkpoint_backend,
        }
        self._project({**state, **result})
        return result

    def _decompose_goal(self, state: GoalGraphState) -> dict[str, Any]:
        return {"execution_path": list(state.get("execution_path", [])) + ["decompose_goal"]}

    def _plan_tasks(self, state: GoalGraphState) -> dict[str, Any]:
        if state.get("tasks"):
            return {"execution_path": list(state.get("execution_path", [])) + ["plan_tasks"]}
        criteria, tasks = self.planner.plan(
            str(state.get("goal") or ""),
            state.get("context", {}),
            int(state.get("max_steps") or 5),
        )
        goal = _goal_from_state(state)
        goal.success_criteria = list(state.get("success_criteria") or criteria)
        events = _replace_goal_created_count(state.get("events", []), len(tasks))
        result = {
            "goal_record": goal.to_dict(),
            "tasks": [task.to_dict() for task in tasks],
            "events": events,
            "execution_path": list(state.get("execution_path", [])) + ["plan_tasks"],
        }
        self._project({**state, **result})
        return result

    def _select_next_task(self, state: GoalGraphState) -> dict[str, Any]:
        tasks = _tasks_from_state(state)
        if state.get("confirm"):
            for task in tasks:
                if task.status == "blocked":
                    task.status = "pending"
                    task.requires_confirmation = False
                    break
        task = _select_ready_task(tasks)
        result = {
            "tasks": [item.to_dict() for item in tasks],
            "current_task": task.to_dict() if task else {},
            "execution_path": list(state.get("execution_path", [])) + ["select_next_task"],
        }
        self._project({**state, **result})
        return result

    def _execute_task(self, state: GoalGraphState) -> dict[str, Any]:
        current = state.get("current_task") or {}
        if not current:
            return {"execution_path": list(state.get("execution_path", [])) + ["execute_task"]}
        goal = _goal_from_state(state)
        tasks = _tasks_from_state(state)
        current_task = GoalTask.from_dict(current)
        previous_tasks = [task for task in tasks if task.task_id != current_task.task_id]
        updated = self.executor.execute(
            goal,
            current_task,
            previous_tasks,
            confirm=bool(state.get("confirm")),
        )
        tasks = [updated if task.task_id == updated.task_id else task for task in tasks]
        events = _append_event(
            state,
            "task_executed",
            task_id=updated.task_id,
            data={
                "status": updated.status,
                "type": updated.type,
                "executor": updated.executor,
                "attempts": updated.attempts,
                "output": updated.output,
            },
        )
        evidence = list(state.get("evidence", []))
        for item in updated.evidence:
            if isinstance(item, dict):
                evidence.append(
                    {
                        "goal_id": goal.id,
                        "task_id": updated.task_id,
                        "created_at": _now(),
                        **item,
                    }
                )
        goal.current_step += 1
        result = {
            "goal_record": goal.to_dict(),
            "tasks": [task.to_dict() for task in tasks],
            "current_task": updated.to_dict(),
            "events": events,
            "evidence": evidence,
            "run_steps": int(state.get("run_steps") or 0) + 1,
            "execution_path": list(state.get("execution_path", []))
            + ["execute_next_task", updated.executor or updated.type],
        }
        self._project({**state, **result})
        return result

    def _observe_result(self, state: GoalGraphState) -> dict[str, Any]:
        result = {"execution_path": list(state.get("execution_path", [])) + ["observe_result"]}
        self._project({**state, **result})
        return result

    def _evaluate_progress(self, state: GoalGraphState) -> dict[str, Any]:
        goal = _goal_from_state(state)
        tasks = _tasks_from_state(state)
        evaluation = self.evaluator.evaluate(goal, tasks)
        evaluations = list(state.get("evaluations", []))
        evaluations.append({"goal_id": goal.id, "created_at": _now(), **evaluation})
        goal.status = str(evaluation["status"])
        goal.summary = str(evaluation["summary"])
        goal.last_evaluation = dict(evaluation)
        goal.waiting_reason = str(evaluation.get("revision_instruction") or "") or None
        next_action = str(evaluation.get("next_action") or "")
        step_budget_exhausted = False
        if next_action == "continue" and int(state.get("run_steps") or 0) >= int(state.get("step_budget") or 1):
            step_budget_exhausted = True
        result = {
            "goal_record": goal.to_dict(),
            "status": goal.status,
            "summary": goal.summary,
            "evaluations": evaluations,
            "next_action": next_action,
            "step_budget_exhausted": step_budget_exhausted,
            "interrupt_payload": _confirmation_payload(goal, tasks, evaluation),
            "resume_required": bool(evaluation.get("requires_confirmation")),
            "execution_path": list(state.get("execution_path", [])) + ["evaluate_progress"],
        }
        self._project({**state, **result})
        return result

    def _human_interrupt(self, state: GoalGraphState) -> dict[str, Any]:
        payload = state.get("interrupt_payload") or {
            "goal_id": state.get("goal_id"),
            "message": "目标需要用户确认后继续。",
        }
        resume = interrupt(payload)
        approved = bool(resume is True or (isinstance(resume, dict) and resume.get("approved")))
        if not approved:
            return {
                "status": "waiting_human",
                "resume_required": True,
                "interrupted": True,
                "execution_path": list(state.get("execution_path", [])) + ["ask_human"],
            }
        tasks = _tasks_from_state(state)
        for task in tasks:
            if task.status == "blocked":
                task.status = "pending"
                task.requires_confirmation = False
                break
        goal = _goal_from_state(state)
        goal.status = "active"
        goal.waiting_reason = None
        result = {
            "goal_record": goal.to_dict(),
            "tasks": [task.to_dict() for task in tasks],
            "status": "active",
            "confirm": True,
            "resume_required": False,
            "interrupted": False,
            "interrupt_payload": None,
            "execution_path": list(state.get("execution_path", [])) + ["ask_human", "resume_confirmed"],
        }
        self._project({**state, **result})
        return result

    def _revise_plan(self, state: GoalGraphState) -> dict[str, Any]:
        goal = _goal_from_state(state)
        tasks = _tasks_from_state(state)
        additions = self.planner.revise(goal, tasks, goal.last_evaluation)
        if additions:
            for task in tasks:
                if task.status == "failed":
                    task.status = "done"
                    task.result_score = max(task.result_score, 0.1)
            tasks.extend(additions)
            goal.plan_version += 1
            goal.revision_count += 1
            goal.status = "active"
        result = {
            "goal_record": goal.to_dict(),
            "tasks": [task.to_dict() for task in tasks],
            "status": goal.status,
            "next_action": "continue",
            "execution_path": list(state.get("execution_path", [])) + ["revise_plan", "plan_tasks"],
        }
        self._project({**state, **result})
        return result

    def _learn_from_goal(self, state: GoalGraphState) -> dict[str, Any]:
        result = {"execution_path": list(state.get("execution_path", [])) + ["learn_from_goal", "finish_goal"]}
        self._project({**state, **result})
        return result

    def _state_from_projection(self, goal_id: str) -> GoalGraphState:
        data = self.store.get(goal_id)
        return {
            "goal_id": goal_id,
            "thread_id": goal_id,
            "mode": "step",
            "goal": str(data.get("goal") or ""),
            "context": {},
            "goal_record": {key: value for key, value in data.items() if key not in {"tasks", "events", "evidence", "evaluations", "artifacts"}},
            "tasks": list(data.get("tasks") or []),
            "events": list(data.get("events") or []),
            "evidence": list(data.get("evidence") or []),
            "evaluations": list(data.get("evaluations") or []),
            "status": str(data.get("status") or "active"),
            "summary": str(data.get("summary") or ""),
            "execution_path": [],
            "checkpointed": False,
            "checkpoint_backend": self.checkpoint_backend,
        }

    def _state_for_read(self, goal_id: str) -> GoalGraphState:
        config = _config(goal_id)
        snapshot = self.graph.get_state(config)
        values = dict(snapshot.values or {})
        if values:
            self._project(values)
            return values
        return self._state_from_projection(goal_id)

    def _project(self, state: dict[str, Any]) -> None:
        goal = _goal_from_state(state)
        tasks = _tasks_from_state(state)
        self.store.write_projection(
            goal,
            tasks,
            list(state.get("events", [])),
            list(state.get("evidence", [])),
            list(state.get("evaluations", [])),
        )

    def _result_from_state(
        self,
        state: dict[str, Any],
        *,
        answer: str,
        interrupted: bool | None = None,
        interrupt_payload: dict[str, Any] | None = None,
        last_checkpoint: str = "",
    ) -> dict[str, Any]:
        goal = _goal_from_state(state)
        tasks = _tasks_from_state(state)
        evaluations = list(state.get("evaluations", []))
        interrupted = bool(state.get("interrupted")) if interrupted is None else interrupted
        payload = interrupt_payload if interrupt_payload is not None else state.get("interrupt_payload")
        return GoalRunResult(
            goal_id=goal.id,
            status=str(state.get("status") or goal.status),
            summary=str(state.get("summary") or goal.summary),
            current_task=state.get("current_task") or _current_task(tasks),
            tasks=[task.to_dict() for task in tasks],
            events=list(state.get("events", [])),
            answer=answer,
            requires_confirmation=bool(state.get("resume_required") or goal.status == "waiting_human"),
            confirmation_prompt=_payload_prompt(payload),
            learning_candidate_ids=_learning_ids(tasks),
            artifacts=[],
            execution_path=list(state.get("execution_path", [])),
            evidence=list(state.get("evidence", [])),
            evaluations=evaluations,
            last_evaluation=goal.last_evaluation or (evaluations[-1] if evaluations else {}),
            plan_version=goal.plan_version,
            revision_count=goal.revision_count,
            next_action=_public_next_action(state, goal),
        ).to_dict() | {
            "thread_id": goal.id,
            "checkpointed": True,
            "checkpoint_backend": self.checkpoint_backend,
            "interrupted": interrupted,
            "interrupt_payload": payload,
            "resume_required": bool(state.get("resume_required") or interrupted),
            "last_checkpoint": last_checkpoint,
        }


def build_goal_workflow(
    store: GoalStore,
    planner: GoalPlannerProtocol,
    executor: GoalExecutor,
    evaluator: GoalEvaluator,
) -> LangGraphGoalWorkflow:
    return LangGraphGoalWorkflow(store, planner, executor, evaluator)


def _build_checkpointer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except Exception:
        return InMemorySaver(), "memory", None
    try:
        factory = getattr(SqliteSaver, "from_conn_string", None)
        if factory is not None:
            context = factory(str(path))
            if hasattr(context, "__enter__"):
                return context.__enter__(), "sqlite", context
            return context, "sqlite", None
        return SqliteSaver(str(path)), "sqlite", None
    except Exception:
        return InMemorySaver(), "memory", None


def _config(goal_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": goal_id}}


def _after_plan(state: GoalGraphState) -> str:
    return "start_done" if state.get("mode") == "start" else "step"


def _after_select(state: GoalGraphState) -> str:
    return "execute" if state.get("current_task") else "evaluate"


def _after_evaluation(state: GoalGraphState) -> str:
    action = str(state.get("next_action") or "")
    if state.get("step_budget_exhausted"):
        return "done"
    if action == "need_human" or state.get("resume_required"):
        return "need_human"
    if action == "revise_plan":
        return "revise_plan"
    if action == "finish":
        return "learn"
    if action == "failed":
        return "failed"
    if action == "continue":
        return "continue"
    return "done"


def _public_next_action(state: dict[str, Any], goal: Goal) -> str:
    action = str(state.get("next_action") or goal.last_evaluation.get("next_action", ""))
    if goal.status == "completed":
        return "completed"
    if goal.status == "failed":
        return "failed"
    if goal.status == "paused":
        return "paused"
    if goal.status == "waiting_human" or state.get("resume_required"):
        return "waiting_human"
    if action in {"finish", "done"}:
        return "completed" if goal.status == "completed" else "continue"
    return action or "continue"


def _goal_from_state(state: dict[str, Any]) -> Goal:
    record = dict(state.get("goal_record") or {})
    if not record:
        record = {
            "id": state.get("goal_id"),
            "goal": state.get("goal", ""),
            "status": state.get("status", "active"),
            "summary": state.get("summary", ""),
            "max_steps": state.get("max_steps", 5),
            "autonomy_policy": state.get("autonomy_policy", "read_only_auto_write_confirm"),
            "success_criteria": state.get("success_criteria", []),
            "force_learning": state.get("force_learning", False),
        }
    goal = Goal.from_dict(record)
    if state.get("status"):
        goal.status = str(state["status"])
    if state.get("summary"):
        goal.summary = str(state["summary"])
    return goal


def _tasks_from_state(state: dict[str, Any]) -> list[GoalTask]:
    return [GoalTask.from_dict(item) for item in state.get("tasks", []) if isinstance(item, dict)]


def _select_ready_task(tasks: list[GoalTask]) -> GoalTask | None:
    done = {task.task_id for task in tasks if task.status == "done"}
    ready = [
        task
        for task in tasks
        if task.status == "pending" and all(dep in done for dep in task.depends_on)
    ]
    if not ready:
        return None
    risk_order = {"low": 0, "medium": 1, "high": 2}
    return sorted(
        ready,
        key=lambda task: (
            risk_order.get(task.risk, 9),
            task.priority,
            task.task_id,
        ),
    )[0]


def _append_event(
    state: dict[str, Any],
    event: str,
    task_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events = list(state.get("events", []))
    events.append(GoalEvent(event=event, goal_id=str(state.get("goal_id")), task_id=task_id, data=data or {}).to_dict())
    return events


def _replace_goal_created_count(events: list[dict[str, Any]], task_count: int) -> list[dict[str, Any]]:
    result = []
    for event in events:
        item = dict(event)
        if item.get("event") == "goal_created":
            data = dict(item.get("data") or {})
            data["task_count"] = task_count
            item["data"] = data
        result.append(item)
    return result


def _current_task(tasks: list[GoalTask]) -> dict[str, Any]:
    task = next((item for item in tasks if item.status in {"pending", "running", "blocked"}), None)
    return task.to_dict() if task else {}


def _learning_ids(tasks: list[GoalTask]) -> list[str]:
    ids: list[str] = []
    for task in tasks:
        output = task.output or {}
        if output.get("learning_candidate_id"):
            ids.append(str(output["learning_candidate_id"]))
        ids.extend(str(item) for item in output.get("learning_candidate_ids", []) if item)
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        if data.get("learning_candidate_id"):
            ids.append(str(data["learning_candidate_id"]))
        ids.extend(str(item) for item in data.get("learning_candidate_ids", []) if item)
    return list(dict.fromkeys(ids))


def _answer(goal: Goal, tasks: list[GoalTask]) -> str:
    done = [task for task in tasks if task.status == "done"]
    blocked = [task for task in tasks if task.status == "blocked"]
    failed = [task for task in tasks if task.status == "failed"]
    if blocked:
        return str(blocked[0].output.get("confirmation_prompt") or "目标等待用户确认。")
    if failed:
        return "目标执行遇到问题：" + "; ".join(task.failure_reason or task.task_id for task in failed)
    contents = [
        str(task.output.get("content") or task.output.get("answer") or "")
        for task in done
        if str(task.output.get("content") or task.output.get("answer") or "").strip()
    ]
    if contents:
        return "\n".join(contents[-3:])
    if goal.status == "completed":
        return "目标执行完成。"
    return goal.summary or "目标正在执行。"


def _confirmation_payload(
    goal: Goal,
    tasks: list[GoalTask],
    evaluation: dict[str, Any],
) -> dict[str, Any] | None:
    if not evaluation.get("requires_confirmation"):
        return None
    blocked = next((task for task in tasks if task.status == "blocked"), None)
    return {
        "goal_id": goal.id,
        "task_id": blocked.task_id if blocked else None,
        "task_title": blocked.title if blocked else None,
        "message": evaluation.get("confirmation_prompt") or "目标需要用户确认后继续。",
        "risk": blocked.risk if blocked else "medium",
        "next_action": "confirm_or_reject",
    }


def _payload_prompt(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    return str(payload.get("message") or payload.get("confirmation_prompt") or "") or None


def _interrupt_payload(result: Any, snapshot: Any) -> tuple[bool, dict[str, Any] | None]:
    interrupts = []
    if isinstance(result, dict):
        interrupts = list(result.get("__interrupt__", []) or [])
    if not interrupts:
        interrupts = list(getattr(snapshot, "interrupts", ()) or [])
    if not interrupts:
        return False, None
    first = interrupts[0]
    value = getattr(first, "value", None)
    return True, value if isinstance(value, dict) else {"message": str(value)}


def _checkpoint_id(snapshot: Any) -> str:
    config = getattr(snapshot, "config", None)
    if isinstance(config, dict):
        return str((config.get("configurable") or {}).get("checkpoint_id") or "")
    return ""


def _checkpoint_summary(snapshot: Any) -> dict[str, Any]:
    return {
        "next": list(getattr(snapshot, "next", ()) or ()),
        "checkpoint_id": _checkpoint_id(snapshot),
        "created_at": str(getattr(snapshot, "created_at", "") or ""),
        "interrupt_count": len(getattr(snapshot, "interrupts", ()) or ()),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

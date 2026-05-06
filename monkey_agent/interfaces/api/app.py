from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from monkey_agent.app import MonkeyAgent
from monkey_agent.domains.integrations.feishu import FeishuEventHandler
from monkey_agent.domains.integrations.feishu.security import FeishuSecurityError


app = FastAPI(title="MonkeyAgent", version="0.1.0")
agent = MonkeyAgent()


class AskRequest(BaseModel):
    question: str
    context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    question: str
    feedback: str
    context: dict[str, Any] = Field(default_factory=dict)


class GoalRequest(BaseModel):
    goal: str
    context: dict[str, Any] = Field(default_factory=dict)
    max_steps: int = 5
    autonomy_policy: str = "read_only_auto_write_confirm"
    success_criteria: list[str] = Field(default_factory=list)
    force_learning: bool = False


class GoalStepRequest(BaseModel):
    confirm: bool = False


class AgentSkillInstallRequest(BaseModel):
    source: str
    skill: str | None = None


class AgentSkillImportRequest(BaseModel):
    path: str


@app.post("/v1/ask")
def ask(request: AskRequest) -> dict[str, Any]:
    result = agent.ask(
        request.question,
        context=request.context,
    )
    return {
        "answer": result.get("answer", ""),
        "task_type": result.get("task_type"),
        "route": result.get("route"),
        "deterministic_results": result.get("deterministic_results", []),
        "skills_used": result.get("matched_skills", []),
        "rules_used": result.get("matched_rules", []),
        "clarification_questions": result.get("clarification_questions", []),
        "execution_path": result.get("execution_path", []),
        "deterministic_content": result.get("deterministic_content", []),
        "semi_deterministic_content": result.get("semi_deterministic_content", []),
        "uncertain_content": result.get("uncertain_content", []),
        "classification": result.get("classification", {}),
        "required_tools": result.get("required_tools", []),
        "memory_used": result.get("memory_used", []),
        "counterexamples_checked": result.get("counterexamples_checked", []),
        "confidence": result.get("confidence", 0.0),
        "evaluation": result.get("evaluation", {}),
        "requires_confirmation": result.get("requires_confirmation", False),
        "learning_candidate_id": result.get("learning_candidate_id"),
        "adoption_prompt": result.get("adoption_prompt"),
        "adopted_candidate_id": result.get("adopted_candidate_id"),
        "adopted_path": result.get("adopted_path"),
        "exploration": result.get("exploration", {}),
        "tool_builder": result.get("tool_builder", {}),
        "session_id": request.session_id,
        "run_id": result.get("run_id"),
        "tool_run_id": result.get("tool_run_id"),
    }


@app.post("/v1/feedback")
def feedback(request: FeedbackRequest) -> dict[str, Any]:
    candidate_id = agent.submit_feedback(
        request.question,
        request.feedback,
        request.context,
    )
    return {"candidate_id": candidate_id, "status": "pending_review"}


@app.post("/v1/integrations/feishu/events")
async def feishu_events(request: Request) -> dict[str, Any]:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_feishu_payload")
    handler = FeishuEventHandler(agent.settings, _feishu_ask)
    try:
        return handler.handle(payload)
    except FeishuSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _feishu_ask(question: str, context: dict[str, Any]) -> dict[str, Any]:
    return agent.ask(question, context=context)


@app.post("/v1/goals")
def start_goal(request: GoalRequest) -> dict[str, Any]:
    return agent.start_goal(
        request.goal,
        context=request.context,
        max_steps=request.max_steps,
        autonomy_policy=request.autonomy_policy,
        success_criteria=request.success_criteria or None,
        force_learning=request.force_learning,
    )


@app.post("/v1/goals/{goal_id}/step")
def step_goal(goal_id: str, request: GoalStepRequest) -> dict[str, Any]:
    return agent.step_goal(goal_id, confirm=request.confirm)


@app.get("/v1/goals/{goal_id}")
def get_goal(goal_id: str) -> dict[str, Any]:
    return agent.get_goal(goal_id)


@app.get("/v1/goals/{goal_id}/plan")
def get_goal_plan(goal_id: str) -> dict[str, Any]:
    return agent.get_goal_plan(goal_id)


@app.get("/v1/goals/{goal_id}/events")
def get_goal_events(goal_id: str) -> dict[str, Any]:
    return agent.get_goal_events(goal_id)


@app.post("/v1/goals/{goal_id}/pause")
def pause_goal(goal_id: str, request: GoalStepRequest) -> dict[str, Any]:
    return agent.pause_goal(goal_id)


@app.post("/v1/goals/{goal_id}/resume")
def resume_goal(goal_id: str, request: GoalStepRequest) -> dict[str, Any]:
    return agent.resume_goal(goal_id)


@app.get("/v1/runs")
def list_runs(type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if type is not None and type not in {"ask", "goal", "tool"}:
        raise HTTPException(status_code=400, detail="type must be ask, goal, or tool")
    return agent.list_runs(run_type=type, limit=limit)


@app.get("/v1/runs/latest")
def latest_run(type: str | None = None) -> dict[str, Any] | None:
    if type is not None and type not in {"ask", "goal", "tool"}:
        raise HTTPException(status_code=400, detail="type must be ask, goal, or tool")
    return agent.latest_run(run_type=type)


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    item = agent.get_run(run_id)
    if item is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return item


@app.get("/v1/rules")
def list_rules() -> list[dict[str, Any]]:
    return agent.list_rules()


@app.get("/v1/skills")
def list_skills(type: str = "all") -> list[dict[str, Any]]:
    if type not in {"all", "yaml", "agent"}:
        raise HTTPException(status_code=400, detail="type must be all, yaml, or agent")
    return agent.list_skills(skill_type=type)


@app.get("/v1/agent-skills")
def list_agent_skills() -> list[dict[str, Any]]:
    return agent.list_agent_skills()


@app.get("/v1/agent-skills/{skill_name}")
def inspect_agent_skill(skill_name: str) -> dict[str, Any]:
    item = agent.inspect_agent_skill(skill_name)
    if item is None:
        raise HTTPException(status_code=404, detail="agent_skill_not_found")
    return item


@app.post("/v1/agent-skills/install")
def install_agent_skill(request: AgentSkillInstallRequest) -> dict[str, Any]:
    try:
        return agent.install_agent_skill(request.source, request.skill)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/agent-skills/import")
def import_agent_skill(request: AgentSkillImportRequest) -> dict[str, Any]:
    try:
        return agent.import_agent_skill(request.path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/agent-skills/{skill_name}/enable")
def enable_agent_skill(skill_name: str) -> dict[str, Any]:
    try:
        return agent.enable_agent_skill(skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v1/agent-skills/{skill_name}/disable")
def disable_agent_skill(skill_name: str) -> dict[str, Any]:
    try:
        return agent.disable_agent_skill(skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/v1/agent-skills/{skill_name}")
def remove_agent_skill(skill_name: str) -> dict[str, Any]:
    try:
        return agent.remove_agent_skill(skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/memory")
def list_memory() -> list[dict[str, Any]]:
    return agent.list_memory()


@app.get("/v1/counterexamples")
def list_counterexamples() -> list[dict[str, Any]]:
    return agent.list_counterexamples()


@app.get("/v1/capabilities")
def list_capabilities() -> list[dict[str, str]]:
    return agent.list_capabilities()


@app.get("/v1/tools")
def list_tools() -> list[dict[str, Any]]:
    return agent.list_capabilities()


@app.get("/v1/tools/generated")
def list_generated_tools() -> list[dict[str, Any]]:
    return agent.list_generated_tools()


@app.get("/v1/tools/generated/{tool_id}")
def inspect_generated_tool(tool_id: str) -> dict[str, Any] | None:
    return agent.get_generated_tool(tool_id)


@app.post("/v1/tools/generated/{tool_id}/enable")
def enable_generated_tool(tool_id: str) -> dict[str, Any]:
    return agent.enable_generated_tool(tool_id)


@app.post("/v1/tools/generated/{tool_id}/disable")
def disable_generated_tool(tool_id: str) -> dict[str, Any]:
    return agent.disable_generated_tool(tool_id)


@app.post("/v1/tools/generated/{tool_id}/test")
def test_generated_tool(tool_id: str) -> dict[str, Any]:
    return agent.test_generated_tool(tool_id)


@app.get("/v1/review/pending")
def list_pending() -> list[dict[str, Any]]:
    return agent.list_pending()


@app.post("/v1/review/{candidate_id}/approve")
def approve(candidate_id: str) -> dict[str, str]:
    path = agent.approve(candidate_id)
    return {"candidate_id": candidate_id, "status": "approved", "path": str(path)}


@app.post("/v1/adopt/{candidate_id}")
def adopt(candidate_id: str) -> dict[str, str]:
    path = agent.adopt(candidate_id)
    return {"candidate_id": candidate_id, "status": "approved", "path": path}


@app.post("/v1/review/{candidate_id}/reject")
def reject(candidate_id: str) -> dict[str, str]:
    path = agent.reject(candidate_id)
    return {"candidate_id": candidate_id, "status": "rejected", "path": str(path)}

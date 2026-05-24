from __future__ import annotations

import json
from typing import Any

from monkey_agent.domains.agent_skills.models import AgentSkill
from monkey_agent.domains.agent_skills.runtime_models import AgentSkillExecutionPlan


class AgentSkillScriptSelector:
    def __init__(self, chat_model: Any | None = None) -> None:
        self.chat_model = chat_model

    def select(
        self,
        question: str,
        skill: AgentSkill,
        context: dict[str, Any],
    ) -> AgentSkillExecutionPlan | None:
        scripts = _script_files(skill)
        if not scripts:
            return None
        explicit = context.get("agent_skill_script") or context.get("script")
        if explicit and any(item["path"] == explicit for item in scripts):
            return AgentSkillExecutionPlan(
                skill_id=skill.id,
                script_path=str(explicit),
                input_data=_input_data(question, context),
                reason="explicit_context_script",
            )
        selected = self._select_with_llm(question, skill, scripts, context)
        if selected is not None:
            return selected
        if _question_requests_execution(question):
            return AgentSkillExecutionPlan(
                skill_id=skill.id,
                script_path=str(scripts[0]["path"]),
                input_data=_input_data(question, context),
                reason="heuristic_first_script",
            )
        return None

    def _select_with_llm(
        self,
        question: str,
        skill: AgentSkill,
        scripts: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> AgentSkillExecutionPlan | None:
        if self.chat_model is None:
            return None
        selector = getattr(self.chat_model, "select_agent_skill_script", None)
        if selector is None:
            return None
        try:
            data = selector(
                question=question,
                skill=skill.to_dict(include_body=True),
                scripts=scripts,
                context=context,
            )
        except Exception:
            return None
        if not isinstance(data, dict) or not data.get("script_path"):
            return None
        script_path = str(data.get("script_path"))
        if not any(item["path"] == script_path for item in scripts):
            return None
        input_data = data.get("input")
        if not isinstance(input_data, dict):
            input_data = _input_data(question, context)
        return AgentSkillExecutionPlan(
            skill_id=skill.id,
            script_path=script_path,
            input_data=input_data,
            reason=str(data.get("reason") or "llm_selected"),
        )


def _script_files(skill: AgentSkill) -> list[dict[str, Any]]:
    return [item for item in skill.files if item.get("kind") == "scripts"]


def _input_data(question: str, context: dict[str, Any]) -> dict[str, Any]:
    explicit = context.get("agent_skill_input")
    if isinstance(explicit, dict):
        return explicit
    return {"question": question, "context": context}


def _question_requests_execution(question: str) -> bool:
    return any(
        hint in question
        for hint in [
            "执行",
            "运行",
            "处理",
            "生成",
            "转换",
            "解析",
            "跑一下",
            "run",
            "execute",
        ]
    )

from __future__ import annotations

import re
from dataclasses import dataclass

from monkey_agent.domains.agent_skills.models import AgentSkill


@dataclass(frozen=True)
class AgentSkillMatch:
    skill: AgentSkill
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        data = self.skill.to_dict(include_body=True)
        data["match_score"] = self.score
        data["match_reasons"] = self.reasons
        data["skill_kind"] = "agent"
        return data


class AgentSkillMatcher:
    def match(self, question: str, task_type: str, skills: list[AgentSkill]) -> list[AgentSkillMatch]:
        lower_question = question.lower()
        question_terms = set(_terms(lower_question))
        matches: list[AgentSkillMatch] = []
        for skill in skills:
            score = 900
            reasons: list[str] = []
            if skill.id in lower_question or skill.name in lower_question:
                score += 80
                reasons.append(f"name:{skill.name}")
            skill_terms = set(_terms(skill.match_text()))
            overlap = sorted(question_terms & skill_terms)
            if overlap:
                score += min(len(overlap), 8) * 12
                reasons.append("description_terms:" + ",".join(overlap[:8]))
            task_hints = skill.metadata.get("task_types") or skill.metadata.get("intents") or []
            if isinstance(task_hints, str):
                task_hints = [task_hints]
            if task_type in {str(item) for item in task_hints}:
                score += 20
                reasons.append("task_type:" + task_type)
            if reasons:
                matches.append(AgentSkillMatch(skill=skill, score=score, reasons=reasons))
        return sorted(matches, key=lambda item: item.score, reverse=True)


def _terms(text: str) -> list[str]:
    ascii_terms = re.findall(r"[a-z0-9][a-z0-9-]{1,}", text.lower())
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return ascii_terms + cjk_terms

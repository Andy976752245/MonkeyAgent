from __future__ import annotations

from dataclasses import dataclass

from .models import Skill


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        data = self.skill.to_dict()
        data["skill_kind"] = "yaml"
        data["match_score"] = self.score
        data["match_reasons"] = self.reasons
        return data


class SkillMatcher:
    def match(
        self,
        question: str,
        task_type: str,
        skills: list[Skill],
    ) -> list[SkillMatch]:
        matches: list[SkillMatch] = []
        lower_question = question.lower()
        for skill in skills:
            score = skill.priority
            if skill.metadata.get("_source_layer") == "personal":
                score += 1000
            reasons: list[str] = []
            keyword_hits = [
                keyword for keyword in skill.keywords if keyword.lower() in lower_question
            ]
            if keyword_hits:
                score += 20 * len(keyword_hits)
                reasons.append("keyword:" + ",".join(keyword_hits))
            if task_type in skill.task_types:
                score += 15
                reasons.append("task_type:" + task_type)
            if reasons:
                matches.append(SkillMatch(skill=skill, score=score, reasons=reasons))
        return sorted(matches, key=lambda item: item.score, reverse=True)

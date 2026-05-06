from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    context: dict[str, Any]
    feedback: str | None
    task_type: str
    intent_keywords: list[str]
    classification: dict[str, Any]
    keyword_classification: dict[str, Any]
    llm_classification: dict[str, Any]
    classification_adopted: bool
    required_tools: list[str]
    classification_confidence: float
    deterministic_parts: list[str]
    deterministic_content: list[str]
    semi_deterministic_content: list[str]
    uncertain_content: list[str]
    uncertain_parts: list[str]
    matched_rules: list[dict[str, Any]]
    deterministic_results: list[dict[str, Any]]
    matched_skills: list[dict[str, Any]]
    execution_path: list[str]
    exploration: dict[str, Any]
    tool_builder: dict[str, Any]
    route: str
    answer: str
    clarification_questions: list[str]
    confidence: float
    evaluation: dict[str, Any]
    requires_confirmation: bool
    learning_candidate_id: str | None
    adoption_prompt: str | None
    adopted_candidate_id: str | None
    adopted_path: str | None
    memory_used: list[dict[str, Any]]
    counterexamples_checked: list[dict[str, Any]]
    errors: list[str]

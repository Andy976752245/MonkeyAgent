from __future__ import annotations

from typing import Any

from monkey_agent.domains.evaluation.models import EvaluationCheck


class LLMJudge:
    """Optional evaluator-model helper.

    The deterministic local checks remain authoritative. This helper is intentionally
    conservative and returns no checks when the model does not expose a safe judge
    method or when the call fails.
    """

    def __init__(self, chat_model: Any) -> None:
        self.chat_model = chat_model

    def judge_answer(self, state: dict[str, Any]) -> list[EvaluationCheck]:
        judge = getattr(self.chat_model, "evaluate_answer", None)
        if not callable(judge):
            return []
        try:
            result = judge(state)
        except Exception:
            return []
        if not isinstance(result, dict):
            return []
        passed = bool(result.get("passed", True))
        return [
            EvaluationCheck(
                "llm_evaluator_judgement",
                passed,
                str(result.get("summary") or "LLM evaluator completed."),
                "warning" if not passed else "info",
                {"raw": result},
            )
        ]

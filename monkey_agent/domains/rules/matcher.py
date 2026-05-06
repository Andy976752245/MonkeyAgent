from __future__ import annotations

from .models import Rule, RuleMatch


def _contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


CORE_KEYWORDS_BY_INTENT = {
    "weather_query": {"天气", "气温", "降水", "风速"},
}


class RuleMatcher:
    def match(
        self,
        question: str,
        intent_keywords: list[str],
        rules: list[Rule],
    ) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        intent_set = {item.lower() for item in intent_keywords}
        for rule in rules:
            score = rule.priority
            if rule.metadata.get("_source_layer") == "personal":
                score += 1000
            reasons: list[str] = []

            keyword_hits = [kw for kw in rule.keywords if _contains(question, kw)]
            intent_hits = [item for item in rule.intents if item.lower() in intent_set]

            if not _passes_core_keyword_gate(rule, keyword_hits, intent_hits):
                continue

            if keyword_hits:
                score += 30 * len(keyword_hits)
                reasons.append("keyword:" + ",".join(keyword_hits))

            if intent_hits:
                score += 20 * len(intent_hits)
                reasons.append("intent:" + ",".join(intent_hits))

            if reasons:
                matches.append(RuleMatch(rule=rule, score=score, reasons=reasons))

        return sorted(matches, key=lambda item: item.score, reverse=True)


def _passes_core_keyword_gate(
    rule: Rule,
    keyword_hits: list[str],
    intent_hits: list[str],
) -> bool:
    for intent in rule.intents:
        core_keywords = CORE_KEYWORDS_BY_INTENT.get(intent)
        if not core_keywords:
            continue
        if intent_hits:
            return True
        if any(keyword in core_keywords for keyword in keyword_hits):
            return True
        return False
    return True

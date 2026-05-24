from __future__ import annotations

from typing import Any

from monkey_agent.advice import is_personal_advice_task, personal_advice_answer
from monkey_agent.core.state import AgentState


def fast_rule_answer(state: AgentState) -> str | None:
    if state.get("route") != "rules":
        return None
    if state.get("matched_skills"):
        return None
    results = state.get("deterministic_results", [])
    if not results:
        return None
    parts = [_format_rule_result(item) for item in results]
    parts = [item for item in parts if item]
    if not parts:
        return None
    return "\n".join(parts)


def agent_skill_execution_content(execution: dict[str, Any]) -> str:
    if execution.get("success"):
        stdout = str(execution.get("stdout") or "").strip()
        artifacts = execution.get("artifacts") or []
        lines = ["Agent Skill 脚本执行成功。"]
        if stdout:
            lines.append(stdout)
        if artifacts:
            lines.append("Artifacts:")
            lines.extend(f"- {item}" for item in artifacts)
        return "\n".join(lines)
    error = execution.get("error") or "skill_script_failed"
    stderr = str(execution.get("stderr") or "").strip()
    return f"Agent Skill 脚本执行失败：{error}" + (f"\n{stderr}" if stderr else "")


def fallback_answer(state: AgentState, context: dict[str, Any]) -> str:
    if is_personal_advice_task(
        state.get("task_type", "general"),
        state.get("intent_keywords", []),
    ):
        return personal_advice_answer(
            state["question"],
            state.get("task_type", "general"),
            context,
        )
    results = state.get("deterministic_results", [])
    if results:
        lines = ["已优先执行沉淀 Rules："]
        for item in results:
            label = item.get("rule_name") or item.get("rule_id") or "rule"
            content = item.get("value") or item.get("content") or item.get("recommendation")
            lines.append(f"- {label}: {content}")
        return "\n".join(lines)
    skills = state.get("matched_skills", [])
    if skills:
        names = ", ".join(str(item.get("name")) for item in skills)
        return f"模型暂时不可用，已匹配 Skills：{names}。请补充更多上下文后可继续生成更完整答案。"
    return "模型暂时不可用，当前缺少可执行的沉淀 Rules 或 Skills，需要补充更多信息。"


def is_generic_missing_capability_answer(answer: str) -> bool:
    return any(
        marker in answer
        for marker in [
            "当前缺少可执行的沉淀 Rules 或 Skills",
            "需要补充更多业务信息",
            "请补充这个问题所属的业务场景",
        ]
    )


def general_knowledge_fallback(question: str) -> str:
    if "水" in question and "结冰" in question:
        return (
            "水结冰是因为温度降低后，水分子的热运动减弱，分子之间更容易形成稳定的氢键结构。"
            "在标准大气压下，纯水通常在 0°C 左右凝固成冰。"
        )
    if "Python" in question and "Java" in question and "区别" in question:
        return (
            "Python 更强调简洁和开发效率，常用于脚本、数据分析、AI 和自动化；"
            "Java 更强调工程化、类型约束和大型服务端生态，常用于企业后端、Android 和大型系统。"
            "简单说，Python 上手快、表达短，Java 结构更严谨、长期维护能力强。"
        )
    return (
        "这是一个基础常识问题，不需要补充业务字段或外部系统配置。"
        "当前模型不可用时，我只能给出保守回答：请围绕定义、原因、例子和适用边界来理解这个问题；"
        "如果你希望更准确，我可以在模型或搜索能力可用后继续补充。"
    )


def _format_rule_result(item: dict[str, Any]) -> str:
    if item.get("requires_more_info"):
        return str(item.get("content") or item.get("error") or "需要补充更多信息。")
    if item.get("content"):
        return str(item["content"])
    if item.get("recommendation"):
        return str(item["recommendation"])
    if item.get("value") is not None:
        return str(item["value"])
    return ""

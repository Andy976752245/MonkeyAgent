from __future__ import annotations

from typing import Any


def diagnose_run(run: dict[str, Any] | None) -> dict[str, Any]:
    if not run:
        return {
            "status": "empty",
            "summary": "当前没有可诊断的 Run 记录。",
            "suggestions": ["先执行一次 monkey ask 或在 Telegram 中发送一条消息。"],
        }
    failed_tools = [
        item
        for item in run.get("tools", []) or []
        if isinstance(item, dict) and item.get("success") is False
    ]
    timings = [
        item
        for item in run.get("timings", []) or []
        if isinstance(item, dict) and isinstance(item.get("ms"), int | float)
    ]
    slowest = max(timings, key=lambda item: item.get("ms", 0), default={})
    evaluation = run.get("evaluation") or {}
    routing = run.get("routing_policy") or {}
    suggestions = _suggestions(run, failed_tools, slowest, evaluation, routing)
    return {
        "status": "ok",
        "run_id": run.get("id"),
        "type": run.get("type"),
        "question": (run.get("input") or {}).get("question") or (run.get("input") or {}).get("goal"),
        "route": run.get("route"),
        "run_status": run.get("status"),
        "matched_rules": [item.get("name") or item.get("id") for item in run.get("matched_rules", [])],
        "matched_skills": [item.get("name") or item.get("id") for item in run.get("matched_skills", [])],
        "failed_tools": failed_tools,
        "slowest_node": slowest,
        "evaluation_status": evaluation.get("status"),
        "failed_checks": evaluation.get("failed_checks", []),
        "clarification_reason": routing.get("clarification_reason"),
        "answer_preview": run.get("answer_preview", ""),
        "suggestions": suggestions,
    }


def format_diagnosis(diagnosis: dict[str, Any]) -> str:
    if diagnosis.get("status") == "empty":
        return diagnosis["summary"] + "\n" + "\n".join(f"- {item}" for item in diagnosis.get("suggestions", []))
    lines = [
        "MonkeyAgent 诊断",
        f"Run: {diagnosis.get('run_id')}",
        f"问题: {diagnosis.get('question') or '-'}",
        f"路由: {diagnosis.get('route') or '-'} / 状态: {diagnosis.get('run_status') or '-'}",
    ]
    if diagnosis.get("matched_rules"):
        lines.append("命中规则: " + ", ".join(str(item) for item in diagnosis["matched_rules"] if item))
    if diagnosis.get("matched_skills"):
        lines.append("命中技能: " + ", ".join(str(item) for item in diagnosis["matched_skills"] if item))
    failed_tools = diagnosis.get("failed_tools") or []
    if failed_tools:
        lines.append("失败工具: " + ", ".join(str(item.get("tool_id")) for item in failed_tools))
    slowest = diagnosis.get("slowest_node") or {}
    if slowest:
        lines.append(f"最慢节点: {slowest.get('node')} {slowest.get('ms')}ms")
    if diagnosis.get("evaluation_status"):
        lines.append(f"评估: {diagnosis['evaluation_status']}")
    if diagnosis.get("clarification_reason"):
        lines.append(f"澄清原因: {diagnosis['clarification_reason']}")
    if diagnosis.get("answer_preview"):
        lines.append("回答摘要: " + str(diagnosis["answer_preview"])[:220])
    suggestions = diagnosis.get("suggestions") or []
    if suggestions:
        lines.append("建议:")
        lines.extend(f"- {item}" for item in suggestions)
    return "\n".join(lines)


def _suggestions(
    run: dict[str, Any],
    failed_tools: list[dict[str, Any]],
    slowest: dict[str, Any],
    evaluation: dict[str, Any],
    routing: dict[str, Any],
) -> list[str]:
    suggestions: list[str] = []
    if failed_tools:
        suggestions.append("检查失败工具的输入、网络/API 配置，或改进对应参数抽取。")
    if run.get("route") == "need_more_info":
        suggestions.append("如果这是普通问答，应补充黄金测试或 RoutingPolicy，避免误入澄清模板。")
    if slowest and float(slowest.get("ms") or 0) > 3000:
        suggestions.append(f"优先排查 {slowest.get('node')}，该节点耗时较高。")
    if evaluation.get("failed_checks"):
        suggestions.append("查看 evaluation.failed_checks，优先修复失败检查项。")
    if routing.get("prefer_general_reason") and run.get("route") == "need_more_info":
        suggestions.append("路由策略倾向 general_reason，工作流应回退回答而不是继续澄清。")
    if not suggestions:
        suggestions.append("本次运行未发现明显故障；可用 --trace 或 runs inspect 查看完整细节。")
    return suggestions

from __future__ import annotations

from typing import Any

from monkey_agent.domains.evaluation.models import EvaluationCheck


def check_answer_not_empty(state: dict[str, Any]) -> EvaluationCheck:
    answer = str(state.get("answer") or "").strip()
    route = str(state.get("route") or "")
    if answer:
        return EvaluationCheck("answer_not_empty", True, "回答非空。")
    if route == "need_more_info" and state.get("clarification_questions"):
        return EvaluationCheck("answer_not_empty", True, "已提供澄清问题。")
    return EvaluationCheck("answer_not_empty", False, "回答为空。", "error")


def check_rule_value_consistency(state: dict[str, Any]) -> EvaluationCheck:
    answer = str(state.get("answer") or "")
    missing: list[str] = []
    for result in state.get("deterministic_results", []) or []:
        if not isinstance(result, dict):
            continue
        value = result.get("value")
        if value and str(value) not in answer:
            missing.append(str(result.get("rule_id") or value))
    if missing:
        return EvaluationCheck(
            "rule_value_consistency",
            False,
            "回答缺少 Rules 确定性结果：" + ", ".join(missing),
            "error",
            {"missing_rule_values": missing},
        )
    return EvaluationCheck("rule_value_consistency", True, "Rules 确定性结果未被覆盖。")


def check_deterministic_result_used(state: dict[str, Any]) -> EvaluationCheck:
    results = [item for item in state.get("deterministic_results", []) or [] if isinstance(item, dict)]
    if not results:
        return EvaluationCheck("deterministic_result_used", True, "无确定性结果需要校验。")
    answer = str(state.get("answer") or "")
    if not answer:
        return EvaluationCheck(
            "deterministic_result_used",
            False,
            "存在确定性结果但回答为空。",
            "error",
        )
    usable = []
    for item in results:
        for key in ("value", "content", "recommendation"):
            value = item.get(key)
            if value and str(value) in answer:
                usable.append(str(item.get("rule_id") or item.get("source_tool") or key))
                break
    if usable or state.get("route") in {"rules", "capability", "tool_builder"}:
        return EvaluationCheck(
            "deterministic_result_used",
            True,
            "回答使用了确定性结果。",
            data={"used": usable},
        )
    return EvaluationCheck(
        "deterministic_result_used",
        False,
        "确定性结果未体现在回答中。",
        "error",
    )


def check_tool_error_not_hidden(state: dict[str, Any]) -> EvaluationCheck:
    failures: list[str] = []
    for result in state.get("deterministic_results", []) or []:
        if not isinstance(result, dict):
            continue
        if result.get("error") or result.get("requires_more_info"):
            failures.append(str(result.get("error") or result.get("rule_id") or "tool_error"))
    exploration = state.get("exploration")
    if isinstance(exploration, dict) and exploration.get("tool_found") and not exploration.get("success", True):
        failures.append(str(exploration.get("error") or exploration.get("tool_id") or "tool_error"))
    if not failures:
        return EvaluationCheck("tool_error_not_hidden", True, "无工具失败需要披露。")
    answer = str(state.get("answer") or "")
    disclosed = any(token in answer for token in ["失败", "无法", "请确认", "补充", "错误", "不可用"])
    if disclosed:
        return EvaluationCheck(
            "tool_error_not_hidden",
            True,
            "工具失败已在回答中说明。",
            data={"failures": failures},
        )
    return EvaluationCheck(
        "tool_error_not_hidden",
        False,
        "工具失败未在回答中说明，存在编造风险。",
        "error",
        {"failures": failures},
    )


def check_counterexamples(state: dict[str, Any]) -> tuple[EvaluationCheck, list[dict[str, Any]]]:
    answer = str(state.get("answer") or "")
    hits: list[dict[str, Any]] = []
    for counterexample in state.get("counterexamples_checked", []) or []:
        if not isinstance(counterexample, dict):
            continue
        bad_pattern = str(
            counterexample.get("bad_pattern")
            or counterexample.get("bad_case")
            or ""
        )
        if bad_pattern and bad_pattern in answer:
            hits.append(
                {
                    "id": str(counterexample.get("id") or "unknown"),
                    "bad_pattern": bad_pattern,
                    "correction": counterexample.get("correction"),
                }
            )
    if hits:
        return (
            EvaluationCheck(
                "counterexample_not_repeated",
                False,
                "回答复现了历史反例。",
                "error",
                {"hits": hits},
            ),
            hits,
        )
    return EvaluationCheck("counterexample_not_repeated", True, "未复现历史反例。"), hits


def check_evidence_available(state: dict[str, Any]) -> EvaluationCheck:
    route = str(state.get("route") or "")
    if route not in {"capability", "tool_builder"}:
        return EvaluationCheck("evidence_available", True, "该路径不要求额外证据。")
    has_evidence = bool(state.get("deterministic_results") or state.get("exploration") or state.get("tool_builder"))
    if has_evidence:
        return EvaluationCheck("evidence_available", True, "工具/探索证据存在。")
    return EvaluationCheck("evidence_available", False, "工具路径缺少证据。", "warning")


def check_clarification_specificity(state: dict[str, Any]) -> EvaluationCheck:
    if str(state.get("route") or "") != "need_more_info":
        return EvaluationCheck("clarification_specificity", True, "非澄清路径。")
    task_type = str(state.get("task_type") or "")
    if task_type not in {"sales_support", "meeting_preparation", "planning_advice", "communication_advice", "personal_advice"}:
        return EvaluationCheck("clarification_specificity", True, "澄清问题适配当前任务。")
    answer = str(state.get("answer") or "")
    generic_tokens = ["字段定义", "计算口径", "数据源/API", "业务场景或分析目标"]
    if any(token in answer for token in generic_tokens):
        return EvaluationCheck(
            "clarification_specificity",
            False,
            "个人助理类问题不应返回通用字段/API澄清模板。",
            "error",
        )
    return EvaluationCheck("clarification_specificity", True, "澄清问题没有使用通用模板。")


def check_route_policy(state: dict[str, Any]) -> EvaluationCheck:
    policy = state.get("routing_policy")
    if not isinstance(policy, dict):
        return EvaluationCheck("route_policy_check", True, "无路由策略摘要。")
    route = str(state.get("route") or "")
    category = str(policy.get("category") or "")
    clarification_allowed = bool(policy.get("clarification_allowed"))
    if route == "need_more_info" and not clarification_allowed:
        return EvaluationCheck(
            "route_policy_check",
            False,
            "当前问题不允许进入通用澄清模板。",
            "error",
            {"category": category, "policy": policy},
        )
    if route == "rules" and policy.get("blocked_rules"):
        blocked = policy.get("blocked_rules") or []
        matched_ids = {
            str(item.get("id"))
            for item in state.get("matched_rules", []) or []
            if isinstance(item, dict)
        }
        leaked = [
            item for item in blocked
            if isinstance(item, dict) and str(item.get("rule_id")) in matched_ids
        ]
        if leaked:
            return EvaluationCheck(
                "route_policy_check",
                False,
                "被路由策略阻断的 Rule 仍被执行。",
                "error",
                {"blocked_rules": leaked},
            )
    return EvaluationCheck("route_policy_check", True, "路由策略检查通过。")


def check_tool_builder_safety(tool_builder: dict[str, Any]) -> list[EvaluationCheck]:
    if not tool_builder:
        return [EvaluationCheck("tool_builder_present", True, "未触发 Tool Builder。")]
    checks = [EvaluationCheck("tool_builder_present", True, "已触发 Tool Builder。")]
    report = tool_builder.get("safety_report")
    if isinstance(report, dict):
        checks.append(
            EvaluationCheck(
                "tool_builder_safety",
                bool(report.get("passed")),
                "Tool Builder 静态安全检查通过。" if report.get("passed") else "Tool Builder 静态安全检查失败。",
                "error" if not report.get("passed") else "info",
                {"errors": report.get("errors", [])},
            )
        )
    test = tool_builder.get("test_result")
    if isinstance(test, dict):
        checks.append(
            EvaluationCheck(
                "tool_builder_dry_run",
                bool(test.get("success")),
                "Tool Builder dry-run 通过。" if test.get("success") else "Tool Builder dry-run 失败。",
                "error" if not test.get("success") else "info",
                {"error": test.get("error")},
            )
        )
    metadata = tool_builder.get("metadata")
    if isinstance(metadata, dict):
        permission = str(metadata.get("permission") or "")
        read_only = bool(metadata.get("read_only"))
        checks.append(
            EvaluationCheck(
                "tool_builder_permission_policy",
                read_only or permission == "confirm",
                "工具权限策略符合只读自动、写操作确认。"
                if read_only or permission == "confirm"
                else "写操作工具必须设置 permission=confirm。",
                "error" if not (read_only or permission == "confirm") else "info",
                {"permission": permission, "read_only": read_only},
            )
        )
    return checks

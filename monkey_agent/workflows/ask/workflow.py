from __future__ import annotations

from time import perf_counter
from typing import Any

from monkey_agent.workflows.ask.nodes import (
    GraphNodes,
    capability_solved,
    generated_tool_ready,
    has_rules,
    has_skills,
    tool_code_drafted,
    tool_code_valid,
    tool_spec_discovered,
    tool_test_passed,
)
from monkey_agent.core.state import AgentState


class SequentialWorkflow:
    def __init__(self, nodes: GraphNodes) -> None:
        self.nodes = nodes

    def invoke(self, state: AgentState) -> AgentState:
        current: AgentState = dict(state)
        current.update(_invoke_node("keyword_classify", self.nodes.keyword_classify, current))
        current.update(_invoke_node("llm_classify", self.nodes.llm_classify, current))
        current.update(_invoke_node("merge_classification", self.nodes.merge_classification, current))
        current.update(_invoke_node("match_rules", self.nodes.match_rules, current))
        if current.get("matched_rules"):
            current.update(_invoke_node("execute_rules", self.nodes.execute_rules, current))
            current.update(_invoke_node("reason", self.nodes.reason, current))
            current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
        else:
            current.update(_invoke_node("match_skills", self.nodes.match_skills, current))
            if current.get("matched_skills"):
                current.update(_invoke_node("reason", self.nodes.reason, current))
                current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
            else:
                current.update(_invoke_node("explore_capabilities", self.nodes.explore_capabilities, current))
                if current.get("exploration", {}).get("success"):
                    current.update(_invoke_node("reason", self.nodes.reason, current))
                    current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                elif capability_solved(current) == "general_reason":
                    current.update(_invoke_node("general_reason", self.nodes.general_reason, current))
                    current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                elif current.get("exploration", {}).get("tool_found"):
                    current.update(_invoke_node("need_more_info", self.nodes.need_more_info, current))
                    current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                else:
                    current.update(_invoke_node("discover_tool_spec", self.nodes.discover_tool_spec, current))
                    if current.get("tool_builder", {}).get("spec"):
                        current.update(_invoke_node("draft_tool_code", self.nodes.draft_tool_code, current))
                        if current.get("tool_builder", {}).get("draft"):
                            current.update(_invoke_node("validate_tool_code", self.nodes.validate_tool_code, current))
                            if current.get("tool_builder", {}).get("safety_report", {}).get("passed"):
                                current.update(_invoke_node("sandbox_test_tool", self.nodes.sandbox_test_tool, current))
                                if current.get("tool_builder", {}).get("test_result", {}).get("success"):
                                    current.update(_invoke_node("register_generated_tool", self.nodes.register_generated_tool, current))
                                    current.update(_invoke_node("learn_generated_tool", self.nodes.learn_generated_tool, current))
                                    current.update(_invoke_node("reason", self.nodes.reason, current))
                                    current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                                else:
                                    current.update(_invoke_node("learn_generated_tool", self.nodes.learn_generated_tool, current))
                                    current.update(_invoke_node("need_more_info", self.nodes.need_more_info, current))
                                    current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                            else:
                                current.update(_invoke_node("learn_generated_tool", self.nodes.learn_generated_tool, current))
                                current.update(_invoke_node("need_more_info", self.nodes.need_more_info, current))
                                current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                    elif tool_spec_discovered(current) == "general_reason":
                        current.update(_invoke_node("general_reason", self.nodes.general_reason, current))
                        current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
                    else:
                        current.update(_invoke_node("explore_learn", self.nodes.explore_learn, current))
                        current.update(_invoke_node("need_more_info", self.nodes.need_more_info, current))
                        current.update(_invoke_node("evaluate", self.nodes.evaluate, current))
        current.update(_invoke_node("learn", self.nodes.learn, current))
        return current


def build_workflow(nodes: GraphNodes) -> Any:
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return SequentialWorkflow(nodes)

    graph = StateGraph(AgentState)
    graph.add_node("keyword_classify", _timed_node("keyword_classify", nodes.keyword_classify))
    graph.add_node("llm_classify", _timed_node("llm_classify", nodes.llm_classify))
    graph.add_node("merge_classification", _timed_node("merge_classification", nodes.merge_classification))
    graph.add_node("match_rules", _timed_node("match_rules", nodes.match_rules))
    graph.add_node("execute_rules", _timed_node("execute_rules", nodes.execute_rules))
    graph.add_node("match_skills", _timed_node("match_skills", nodes.match_skills))
    graph.add_node("need_more_info", _timed_node("need_more_info", nodes.need_more_info))
    graph.add_node("explore_capabilities", _timed_node("explore_capabilities", nodes.explore_capabilities))
    graph.add_node("discover_tool_spec", _timed_node("discover_tool_spec", nodes.discover_tool_spec))
    graph.add_node("draft_tool_code", _timed_node("draft_tool_code", nodes.draft_tool_code))
    graph.add_node("validate_tool_code", _timed_node("validate_tool_code", nodes.validate_tool_code))
    graph.add_node("sandbox_test_tool", _timed_node("sandbox_test_tool", nodes.sandbox_test_tool))
    graph.add_node("register_generated_tool", _timed_node("register_generated_tool", nodes.register_generated_tool))
    graph.add_node("learn_generated_tool", _timed_node("learn_generated_tool", nodes.learn_generated_tool))
    graph.add_node("explore_learn", _timed_node("explore_learn", nodes.explore_learn))
    graph.add_node("general_reason", _timed_node("general_reason", nodes.general_reason))
    graph.add_node("reason", _timed_node("reason", nodes.reason))
    graph.add_node("evaluate", _timed_node("evaluate", nodes.evaluate))
    graph.add_node("learn", _timed_node("learn", nodes.learn))

    graph.add_edge(START, "keyword_classify")
    graph.add_edge("keyword_classify", "llm_classify")
    graph.add_edge("llm_classify", "merge_classification")
    graph.add_edge("merge_classification", "match_rules")
    graph.add_conditional_edges(
        "match_rules",
        has_rules,
        {"rules": "execute_rules", "skills": "match_skills", "adopted": "learn"},
    )
    graph.add_edge("execute_rules", "reason")
    graph.add_conditional_edges(
        "match_skills",
        has_skills,
        {
            "skills": "reason",
            "need_more_info": "explore_capabilities",
            "adopted": "learn",
        },
    )
    graph.add_conditional_edges(
        "explore_capabilities",
        capability_solved,
        {
            "solved": "reason",
            "general_reason": "general_reason",
            "tool_failed": "need_more_info",
            "unsolved": "discover_tool_spec",
        },
    )
    graph.add_conditional_edges(
        "discover_tool_spec",
        tool_spec_discovered,
        {
            "discovered": "draft_tool_code",
            "general_reason": "general_reason",
            "not_discovered": "explore_learn",
        },
    )
    graph.add_conditional_edges(
        "draft_tool_code",
        tool_code_drafted,
        {
            "drafted": "validate_tool_code",
            "failed": "learn_generated_tool",
        },
    )
    graph.add_conditional_edges(
        "validate_tool_code",
        tool_code_valid,
        {
            "valid": "sandbox_test_tool",
            "invalid": "learn_generated_tool",
        },
    )
    graph.add_conditional_edges(
        "sandbox_test_tool",
        tool_test_passed,
        {
            "passed": "register_generated_tool",
            "failed": "learn_generated_tool",
        },
    )
    graph.add_edge("register_generated_tool", "learn_generated_tool")
    graph.add_conditional_edges(
        "learn_generated_tool",
        generated_tool_ready,
        {
            "ready": "reason",
            "failed": "need_more_info",
        },
    )
    graph.add_edge("reason", "evaluate")
    graph.add_edge("general_reason", "evaluate")
    graph.add_edge("evaluate", "learn")
    graph.add_edge("explore_learn", "need_more_info")
    graph.add_edge("need_more_info", "evaluate")
    graph.add_edge("learn", END)
    return graph.compile()


def _timed_node(name: str, fn: Any) -> Any:
    def wrapped(state: AgentState) -> dict[str, Any]:
        return _invoke_node(name, fn, state)

    return wrapped


def _invoke_node(name: str, fn: Any, state: AgentState) -> dict[str, Any]:
    started = perf_counter()
    update = dict(fn(state) or {})
    elapsed_ms = int(round((perf_counter() - started) * 1000))
    update["timings"] = list(state.get("timings", [])) + [
        {"node": name, "ms": elapsed_ms}
    ]
    return update

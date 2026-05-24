from __future__ import annotations

import re
from typing import Any

from monkey_agent.advice import (
    is_personal_advice_task,
    personal_advice_answer,
    personal_advice_clarification_questions,
)
from monkey_agent.workflows.ask.answers import (
    agent_skill_execution_content,
    fallback_answer,
    fast_rule_answer,
    general_knowledge_fallback,
    is_generic_missing_capability_answer,
)
from monkey_agent.domains.tools.capability import CapabilityRegistry
from monkey_agent.domains.classifier import ClassificationResult, QuestionClassifier
from monkey_agent.domains.evaluation import AskEvaluator, ToolBuilderEvaluator
from monkey_agent.domains.learning.usage_memory import UsageMemory
from monkey_agent.domains.learning.review_store import ReviewStore
from monkey_agent.domains.models.bailian import ChatModel
from monkey_agent.domains.agent_skills.matcher import AgentSkillMatcher
from monkey_agent.domains.agent_skills.repository import AgentSkillRepository
from monkey_agent.domains.agent_skills.runtime import AgentSkillRuntime
from monkey_agent.domains.agent_skills.selector import AgentSkillScriptSelector
from monkey_agent.domains.memory import PersonalMemoryStore
from monkey_agent.domains.rules.handlers import RuleExecutor
from monkey_agent.domains.rules.matcher import RuleMatcher
from monkey_agent.domains.rules.repository import RuleRepository
from monkey_agent.domains.routing import RoutingPolicy
from monkey_agent.domains.skills.matcher import SkillMatcher
from monkey_agent.domains.skills.repository import SkillRepository
from monkey_agent.core.state import AgentState
from monkey_agent.domains.tool_builder import ToolBuilderService
from monkey_agent.domains.tools import Permission, ToolExecutionResult, ToolRegistry, ToolRisk


class GraphNodes:
    def __init__(
        self,
        rule_repository: RuleRepository,
        skill_repository: SkillRepository,
        agent_skill_repository: AgentSkillRepository,
        chat_model: ChatModel,
        review_store: ReviewStore,
        capability_registry: CapabilityRegistry,
        usage_memory: UsageMemory,
        classifier: QuestionClassifier,
        personal_memory: PersonalMemoryStore,
        tool_builder: ToolBuilderService,
        tool_registry: ToolRegistry,
        agent_skill_runtime: AgentSkillRuntime | None = None,
        agent_skill_script_selector: AgentSkillScriptSelector | None = None,
    ) -> None:
        self.rule_repository = rule_repository
        self.skill_repository = skill_repository
        self.agent_skill_repository = agent_skill_repository
        self.chat_model = chat_model
        self.review_store = review_store
        self.capability_registry = capability_registry
        self.usage_memory = usage_memory
        self.classifier = classifier
        self.personal_memory = personal_memory
        self.tool_builder = tool_builder
        self.tool_registry = tool_registry
        self.agent_skill_runtime = agent_skill_runtime
        self.agent_skill_script_selector = agent_skill_script_selector
        self.rule_matcher = RuleMatcher()
        self.skill_matcher = SkillMatcher()
        self.agent_skill_matcher = AgentSkillMatcher()
        self.rule_executor = RuleExecutor()
        self.routing_policy = RoutingPolicy()
        self.ask_evaluator = AskEvaluator(chat_model)
        self.tool_builder_evaluator = ToolBuilderEvaluator()

    def classify(self, state: AgentState) -> dict[str, Any]:
        current = dict(state)
        current.update(self.keyword_classify(current))
        current.update(self.llm_classify(current))
        current.update(self.merge_classification(current))
        return current

    def keyword_classify(self, state: AgentState) -> dict[str, Any]:
        question = state["question"]
        adoption = self.try_adopt_latest(state)
        if adoption:
            return {
                **adoption,
                "classification_adopted": True,
                "task_type": "adoption",
                "intent_keywords": ["adoption"],
                "deterministic_parts": [],
                "deterministic_content": [],
                "semi_deterministic_content": [],
                "uncertain_content": [],
                "uncertain_parts": [],
                "execution_path": ["keyword_classify", "adopt_latest"],
            }
        keyword = self.classifier.keyword_classify(question)
        return {
            "keyword_classification": keyword.to_dict(),
            "execution_path": ["keyword_classify"],
        }

    def llm_classify(self, state: AgentState) -> dict[str, Any]:
        if state.get("classification_adopted"):
            return {"execution_path": state.get("execution_path", []) + ["llm_classify"]}
        if _can_skip_llm_classify(state):
            return {
                "llm_classification": {
                    "deterministic": [],
                    "semi_deterministic": [],
                    "uncertain": [],
                    "intents": [],
                    "required_tools": [],
                    "task_type": "general",
                    "confidence": 0.0,
                    "clarification_questions": [],
                    "source": "llm_skipped",
                },
                "llm_classification_skipped": True,
                "execution_path": state.get("execution_path", []) + ["llm_classify_skipped"],
            }
        llm = self.classifier.llm_classify(
            state["question"],
            state.get("context", {}),
        )
        return {
            "llm_classification": llm.to_dict(),
            "execution_path": state.get("execution_path", []) + ["llm_classify"],
        }

    def merge_classification(self, state: AgentState) -> dict[str, Any]:
        if state.get("classification_adopted"):
            return {
                "execution_path": state.get("execution_path", []) + ["merge_classification"]
            }
        keyword = ClassificationResult.from_dict(
            state.get("keyword_classification", {}),
            source="keyword",
        )
        llm = ClassificationResult.from_dict(
            state.get("llm_classification", {}),
            source="llm",
        )
        merged = self.classifier.merge(keyword, llm)
        preview = {
            **state,
            "task_type": merged.task_type,
            "intent_keywords": merged.intents or ["general"],
            "required_tools": merged.required_tools,
        }
        return {
            "classification": {
                "keyword": keyword.to_dict(),
                "llm": llm.to_dict(),
                "merged": merged.to_dict(),
            },
            "task_type": merged.task_type,
            "intent_keywords": merged.intents or ["general"],
            "deterministic_parts": merged.deterministic,
            "deterministic_content": merged.deterministic,
            "semi_deterministic_content": merged.semi_deterministic,
            "uncertain_content": merged.uncertain,
            "uncertain_parts": merged.uncertain,
            "required_tools": merged.required_tools,
            "classification_confidence": merged.confidence,
            "routing_policy": self.routing_policy.summarize(preview),
            "execution_path": state.get("execution_path", []) + ["merge_classification"],
        }

    def match_rules(self, state: AgentState) -> dict[str, Any]:
        if state.get("adopted_candidate_id"):
            return {
                "route": "adopted",
                "execution_path": state.get("execution_path", []) + ["match_rules"],
            }
        matches = self.rule_matcher.match(
            state["question"],
            state.get("intent_keywords", []),
            self.rule_repository.active(),
        )
        matched_rules = [match.to_dict() for match in matches]
        allowed, blocked = self.routing_policy.filter_rule_matches(state, matched_rules)
        routing_policy = {
            **state.get("routing_policy", {}),
            "blocked_rules": blocked,
            "candidate_route": "rules" if allowed else "skills",
        }
        return {
            "matched_rules": allowed,
            "route": "rules" if allowed else "skills",
            "routing_policy": routing_policy,
            "execution_path": state.get("execution_path", []) + ["match_rules"],
        }

    def execute_rules(self, state: AgentState) -> dict[str, Any]:
        matched_ids = {str(item.get("id")) for item in state.get("matched_rules", [])}
        rules = [rule for rule in self.rule_repository.active() if rule.id in matched_ids]
        results: list[dict[str, Any]] = []
        local_rules = []
        for rule in rules:
            if rule.handler != "capability_tool":
                local_rules.append(rule)
                continue
            tool_id = str(rule.metadata.get("capability_tool_id") or rule.metadata.get("source_tool") or "")
            tool_result = self.capability_registry.execute_by_id(
                tool_id,
                state["question"],
                state.get("context", {}),
            )
            if tool_result is None:
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "type": rule.type,
                        "requires_more_info": True,
                        "error": f"capability tool not found: {tool_id}",
                    }
                )
            elif tool_result.success:
                item = tool_result.to_deterministic_result()
                item["rule_id"] = rule.id
                item["rule_name"] = rule.name
                results.append(item)
            else:
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "type": rule.type,
                        "requires_more_info": True,
                        "error": tool_result.error,
                        "content": tool_result.content,
                        "source_tool": tool_result.tool_id,
                    }
                )
        results.extend(
            self.rule_executor.execute(
                local_rules,
                state["question"],
                state.get("context", {}),
            )
        )
        return {
            "deterministic_results": results,
            "matched_skills": [],
            "execution_path": state.get("execution_path", []) + ["execute_rules"],
        }

    def match_skills(self, state: AgentState) -> dict[str, Any]:
        if state.get("adopted_candidate_id"):
            return {
                "route": "adopted",
                "execution_path": state.get("execution_path", []) + ["match_skills"],
            }
        matches = self.skill_matcher.match(
            state["question"],
            state.get("task_type", "general"),
            self.skill_repository.active(),
        )
        agent_matches = self.agent_skill_matcher.match(
            state["question"],
            state.get("task_type", "general"),
            self.agent_skill_repository.active(),
        )
        matched_skills = [match.to_dict() for match in matches] + [
            match.to_dict() for match in agent_matches
        ]
        matched_skills = sorted(
            matched_skills,
            key=lambda item: int(item.get("match_score", 0)),
            reverse=True,
        )
        runtime_update = self._maybe_prepare_agent_skill_runtime(state, matched_skills)
        return {
            "matched_skills": matched_skills,
            "route": "skills" if matched_skills else "need_more_info",
            **runtime_update,
            "execution_path": state.get("execution_path", []) + ["match_skills"],
        }

    def _maybe_prepare_agent_skill_runtime(
        self,
        state: AgentState,
        matched_skills: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.agent_skill_runtime is None or self.agent_skill_script_selector is None:
            return {}
        for match in matched_skills:
            if match.get("skill_kind") != "agent":
                continue
            scripts = [item for item in match.get("files", []) if item.get("kind") == "scripts"]
            if not scripts:
                continue
            skill = self.agent_skill_repository.get(str(match.get("id")))
            if skill is None:
                continue
            plan = self.agent_skill_script_selector.select(
                state["question"],
                skill,
                state.get("context", {}),
            )
            if plan is None:
                continue
            confirm = bool(state.get("context", {}).get("confirm_skill_execution"))
            execution = self.agent_skill_runtime.execute(skill, plan, confirm=confirm)
            runtime = {
                "skill_id": skill.id,
                "plan": plan.to_dict(),
                "execution": execution.to_dict(),
            }
            if execution.requires_confirmation:
                return {
                    "agent_skill_runtime": runtime,
                    "requires_confirmation": True,
                    "answer": (
                        f"Agent Skill {skill.name} 选择了脚本 {plan.script_path}，"
                        "执行前需要确认。确认后可使用 --context "
                        "'{\"confirm_skill_execution\":true}' 重新提问，或使用 "
                        f"monkey skills run {skill.id} --script {plan.script_path} --confirm。"
                    ),
                    "confidence": 0.45,
                    "routing_policy": {
                        **state.get("routing_policy", {}),
                        "final_route": "skills",
                        "agent_skill_runtime": "waiting_confirmation",
                    },
                }
            return {
                "agent_skill_runtime": runtime,
                "deterministic_results": [
                    {
                        "rule_id": f"agent_skill:{skill.id}",
                        "rule_name": skill.name,
                        "type": "agent_skill_script",
                        "content": agent_skill_execution_content(execution.to_dict()),
                        "value": execution.stdout.strip(),
                        "requires_more_info": not execution.success,
                        "error": execution.error,
                        "artifacts": execution.artifacts,
                    }
                ],
                "routing_policy": {
                    **state.get("routing_policy", {}),
                    "final_route": "skills",
                    "agent_skill_runtime": "executed",
                },
            }
        return {}

    def need_more_info(self, state: AgentState) -> dict[str, Any]:
        routing_policy = self.routing_policy.summarize(state)
        if not routing_policy.get("clarification_allowed"):
            redirected = self.general_reason(
                {
                    **state,
                    "routing_policy": {
                        **routing_policy,
                        "candidate_route": "need_more_info",
                        "final_route": "general_reason",
                        "redirect_reason": "clarification_not_allowed",
                    },
                    "execution_path": state.get("execution_path", []) + ["need_more_info_guard"],
                }
            )
            redirected["routing_policy"] = {
                **routing_policy,
                "candidate_route": "need_more_info",
                "final_route": "general_reason",
                "redirect_reason": "clarification_not_allowed",
            }
            return redirected
        exploration = state.get("exploration", {})
        candidate_id = exploration.get("candidate_id")
        questions = _clarification_questions_for_task(state.get("task_type", "general"))
        prefix = ""
        if exploration.get("tool_found") and not exploration.get("success"):
            prefix = (
                f"已探索到可调用能力：{exploration.get('tool_name')}，"
                f"但本次执行失败：{exploration.get('error')}\n"
            )
            if candidate_id:
                prefix += (
                    f"已生成待审核能力沉淀候选：{candidate_id}\n"
                    "请先确认该能力的网络/API/配置后再批准沉淀。\n"
                )
        elif candidate_id:
            prefix = (
                f"当前未命中已沉淀能力，已自动生成待审核学习候选：{candidate_id}\n"
                "审核通过后，后续同类问题会优先使用沉淀能力。\n"
            )
        return {
            "clarification_questions": questions,
            "answer": prefix + "\n".join(f"- {item}" for item in questions),
            "confidence": 0.2,
            "routing_policy": {
                **routing_policy,
                "candidate_route": "need_more_info",
                "final_route": "need_more_info",
            },
            "execution_path": state.get("execution_path", []) + ["need_more_info"],
        }

    def explore_capabilities(self, state: AgentState) -> dict[str, Any]:
        result = self.tool_registry.explore(
            state["question"],
            state.get("context", {}),
        )
        if result is None:
            return {
                "execution_path": state.get("execution_path", [])
                + ["explore_capabilities"],
            }
        if (
            not result.success
            and (
                state.get("context", {}).get("force_tool_builder")
                or _explicit_tool_build_requested(state["question"])
            )
            and self.tool_builder.should_build(state["question"], state.get("context", {}))
        ):
            context = dict(state.get("context", {}))
            context["public_evidence"] = result.public_evidence or result.data.get("results", [])
            return {
                "context": context,
                "exploration": {
                    "tool_id": result.tool_id,
                    "tool_name": result.tool_name,
                    "tool_found": False,
                    "success": False,
                    "candidate_id": None,
                    "candidate_type": "rule",
                    "learning_policy": "force_tool_builder_after_tool_failure",
                    "reason": "现有工具不足以完成目标，继续交给 Tool Builder 生成受控工具。",
                },
                "execution_path": state.get("execution_path", [])
                + ["explore_capabilities"],
            }
        if (
            result.success
            and result.candidate_type == "skill"
            and self.tool_builder.should_build(state["question"], state.get("context", {}))
        ):
            context = dict(state.get("context", {}))
            context["public_evidence"] = result.public_evidence or result.data.get("results", [])
            return {
                "context": context,
                "exploration": {
                    "tool_id": result.tool_id,
                    "tool_name": result.tool_name,
                    "tool_found": False,
                    "success": False,
                    "candidate_id": None,
                    "candidate_type": "rule",
                    "learning_policy": "public_evidence_for_tool_builder",
                    "reason": "公开搜索已提供证据，继续交给 Tool Builder 生成受控工具。",
                },
                "execution_path": state.get("execution_path", [])
                + ["explore_capabilities"],
            }
        if not result.success:
            candidate_id = None
            candidate_type = None
            candidate_type_hint = result.candidate_type or (
                "rule" if result.stable_rule_candidate else "skill"
            )
            decision = self.usage_memory.decide(
                question=state["question"],
                task_type=state.get("task_type", "general"),
                candidate_type=candidate_type_hint,
                stable_rule_candidate=result.stable_rule_candidate,
                explicit_learning=_explicit_learning_requested(state["question"]),
            )
            if decision.should_create_candidate and (
                result.stable_rule_candidate or result.candidate_type
            ):
                draft = self._draft_candidate(
                    state,
                    candidate_type_hint,
                    {
                        "tool_id": result.tool_id,
                        "tool_name": result.tool_name,
                        "content": result.content,
                        "error": result.error,
                        "data": result.data,
                        "handler_name": result.handler_name,
                        "handler_code_proposal": result.handler_code_proposal,
                        "public_evidence": result.public_evidence,
                    },
                )
                candidate_id, candidate = self.review_store.create_capability_candidate(
                    question=state["question"],
                    task_type=state.get("task_type", "general"),
                    intent_keywords=state.get("intent_keywords", []),
                    tool_result=result,
                    context=state.get("context", {}),
                    llm_draft=draft,
                )
                candidate_type = candidate.get("candidate_type")
            return {
                "exploration": {
                    "tool_id": result.tool_id,
                    "tool_name": result.tool_name,
                    "tool_found": True,
                    "success": False,
                    "error": result.error,
                    "candidate_id": candidate_id,
                    "candidate_type": candidate_type,
                    "learning_policy": decision.reason,
                    "repeat_count": decision.repeat_count,
                    "reason": "发现可调用能力，但执行失败，需要补充信息或配置。",
                },
                "learning_candidate_id": candidate_id,
                "adoption_prompt": _adoption_prompt(candidate_id, candidate_type),
                "execution_path": state.get("execution_path", [])
                + ["explore_capabilities"],
            }
        candidate_id = None
        candidate_type = None
        candidate_type_hint = result.candidate_type or (
            "rule" if result.stable_rule_candidate else "skill"
        )
        decision = self.usage_memory.decide(
            question=state["question"],
            task_type=state.get("task_type", "general"),
            candidate_type=candidate_type_hint,
            stable_rule_candidate=result.stable_rule_candidate,
            explicit_learning=_explicit_learning_requested(state["question"]),
        )
        if decision.should_create_candidate and (
            result.stable_rule_candidate or result.candidate_type
        ):
            draft = self._draft_candidate(
                state,
                candidate_type_hint,
                {
                    "tool_id": result.tool_id,
                    "tool_name": result.tool_name,
                    "content": result.content,
                    "data": result.data,
                    "handler_name": result.handler_name,
                    "handler_code_proposal": result.handler_code_proposal,
                    "public_evidence": result.public_evidence,
                },
            )
            candidate_id, candidate = self.review_store.create_capability_candidate(
                question=state["question"],
                task_type=state.get("task_type", "general"),
                intent_keywords=state.get("intent_keywords", []),
                tool_result=result,
                context=state.get("context", {}),
                llm_draft=draft,
            )
            candidate_type = candidate.get("candidate_type")
        return {
            "route": "capability",
            "deterministic_results": [result.to_deterministic_result()],
            "matched_skills": [],
            "exploration": {
                "tool_id": result.tool_id,
                "tool_name": result.tool_name,
                "tool_found": True,
                "success": True,
                "candidate_id": candidate_id,
                "candidate_type": candidate_type,
                "learning_policy": decision.reason,
                "repeat_count": decision.repeat_count,
                "reason": "已探索现有可调用能力并成功解决问题。",
            },
            "learning_candidate_id": candidate_id,
            "adoption_prompt": _adoption_prompt(candidate_id, candidate_type),
            "execution_path": state.get("execution_path", [])
            + ["explore_capabilities"],
        }

    def explore_learn(self, state: AgentState) -> dict[str, Any]:
        if _likely_memory_candidate(state["question"]):
            kind = "memory"
        else:
            kind = "rule" if _likely_code_candidate(state["question"]) else "skill"
        decision = self.usage_memory.decide(
            question=state["question"],
            task_type=state.get("task_type", "general"),
            candidate_type=kind,
            stable_rule_candidate=False,
            explicit_learning=_explicit_learning_requested(state["question"]),
        )
        if not decision.should_create_candidate:
            return {
                "exploration": {
                    "candidate_id": None,
                    "candidate_type": kind,
                    "candidate_name": None,
                    "learning_policy": decision.reason,
                    "repeat_count": decision.repeat_count,
                    "reason": "该问题暂按一次性问题处理，仅记录到记忆观察；相似问题重复出现后再建议沉淀。",
                },
                "learning_candidate_id": None,
                "adoption_prompt": None,
                "execution_path": state.get("execution_path", []) + ["explore_learn"],
            }
        draft = self._draft_candidate(
            state,
            kind,
            {
                "reason": "未找到现有 Rules、Skills 或可调用能力。",
                "task_type": state.get("task_type", "general"),
                "intent_keywords": state.get("intent_keywords", []),
            },
        )
        candidate_id, candidate = self.review_store.create_exploration_candidate(
            question=state["question"],
            task_type=state.get("task_type", "general"),
            intent_keywords=state.get("intent_keywords", []),
            context=state.get("context", {}),
            llm_draft=draft,
            preferred_kind=kind,
        )
        return {
            "exploration": {
                "candidate_id": candidate_id,
                "candidate_type": candidate.get("candidate_type"),
                "candidate_name": candidate.get("name"),
                "learning_policy": decision.reason,
                "repeat_count": decision.repeat_count,
                "reason": candidate.get("exploration_reason")
                or "当前未命中已沉淀能力，自动生成待审核候选。",
            },
            "learning_candidate_id": candidate_id,
            "adoption_prompt": _adoption_prompt(
                candidate_id,
                str(candidate.get("candidate_type")),
            ),
            "execution_path": state.get("execution_path", []) + ["explore_learn"],
        }

    def discover_tool_spec(self, state: AgentState) -> dict[str, Any]:
        spec = self.tool_builder.discover_tool_spec(state["question"], state)
        tool_builder_state = {"stage": "discover_tool_spec", "spec": spec or {}}
        if spec is None:
            tool_builder_state.update(
                {
                    "success": False,
                    "error": "not_a_tool_builder_candidate",
                }
            )
        return {
            "tool_builder": tool_builder_state,
            "execution_path": state.get("execution_path", []) + ["discover_tool_spec"],
        }

    def draft_tool_code(self, state: AgentState) -> dict[str, Any]:
        spec = state.get("tool_builder", {}).get("spec")
        if not spec:
            return {
                "execution_path": state.get("execution_path", []) + ["draft_tool_code"],
            }
        try:
            draft = self.tool_builder.draft_tool_code(
                state["question"],
                spec,
                state.get("context", {}),
            )
        except Exception as exc:  # noqa: BLE001 - model boundary
            return {
                "tool_builder": {
                    **state.get("tool_builder", {}),
                    "stage": "draft_tool_code",
                    "success": False,
                    "error": str(exc),
                },
                "execution_path": state.get("execution_path", []) + ["draft_tool_code"],
            }
        return {
            "tool_builder": {
                **state.get("tool_builder", {}),
                "stage": "draft_tool_code",
                "draft": draft,
            },
            "execution_path": state.get("execution_path", []) + ["draft_tool_code"],
        }

    def validate_tool_code(self, state: AgentState) -> dict[str, Any]:
        draft = state.get("tool_builder", {}).get("draft") or {}
        report = self.tool_builder.validate_tool_code(draft)
        return {
            "tool_builder": {
                **state.get("tool_builder", {}),
                "stage": "validate_tool_code",
                "safety_report": report,
                "success": bool(report.get("passed")),
                "error": None if report.get("passed") else "unsafe_code",
            },
            "execution_path": state.get("execution_path", []) + ["validate_tool_code"],
        }

    def sandbox_test_tool(self, state: AgentState) -> dict[str, Any]:
        draft = state.get("tool_builder", {}).get("draft") or {}
        result = self.tool_builder.sandbox_test_tool(
            state["question"],
            draft,
            state.get("context", {}),
        )
        return {
            "tool_builder": {
                **state.get("tool_builder", {}),
                "stage": "sandbox_test_tool",
                "test_result": result,
                "success": bool(result.get("success")),
                "error": None if result.get("success") else "test_failed",
            },
            "execution_path": state.get("execution_path", []) + ["sandbox_test_tool"],
        }

    def register_generated_tool(self, state: AgentState) -> dict[str, Any]:
        tool_builder_state = state.get("tool_builder", {})
        result = self.tool_builder.register_generated_tool(
            state["question"],
            tool_builder_state.get("spec") or {},
            tool_builder_state.get("draft") or {},
            tool_builder_state.get("test_result") or {},
            tool_builder_state.get("safety_report") or {},
        )
        if result.tool is not None:
            self.tool_registry.add(result.tool)
            self.capability_registry.add(result.tool)
        metadata = result.metadata or {}
        deterministic_result = {
            "rule_id": f"generated:{metadata.get('id')}",
            "rule_name": metadata.get("name") or metadata.get("id"),
            "type": "generated_tool",
            "requires_more_info": False,
            "content": (result.test_result or {}).get("content", ""),
            "data": (result.test_result or {}).get("data", {}),
            "source_tool": metadata.get("id"),
        }
        return {
            "route": "tool_builder",
            "deterministic_results": [deterministic_result] if result.success else [],
            "matched_skills": [],
            "tool_builder": {
                **tool_builder_state,
                "stage": "register_generated_tool",
                "success": result.success,
                "metadata": metadata,
                "error": result.error,
            },
            "exploration": {
                "tool_id": metadata.get("id"),
                "tool_name": metadata.get("name"),
                "tool_found": True,
                "success": result.success,
                "candidate_id": None,
                "candidate_type": None,
                "learning_policy": "tool_builder_generated",
                "reason": "已通过受控 Tool Builder 生成并注册工具。",
            },
            "execution_path": state.get("execution_path", []) + ["register_generated_tool"],
        }

    def learn_generated_tool(self, state: AgentState) -> dict[str, Any]:
        tool_builder_state = state.get("tool_builder", {})
        tool_evaluation = self.tool_builder_evaluator.evaluate(tool_builder_state).to_dict()
        metadata = tool_builder_state.get("metadata") or {}
        if not tool_builder_state.get("success"):
            failure_stage = str(tool_builder_state.get("stage") or "unknown")
            failure_error = str(tool_builder_state.get("error") or "unknown")
            candidate_id = self.review_store.create_candidate(
                question=state["question"],
                feedback=(
                    "错误案例：Tool Builder 生成或验证失败，"
                    f"阶段={failure_stage}，错误={failure_error}。"
                    "下次遇到同类需求时，应先检查是否属于可稳定工具化目标，"
                    "并在生成代码前确认安全边界、输入输出和 dry-run 样例。"
                ),
                context={
                    **_context_with_evaluation(state, tool_evaluation),
                    "tool_builder_failure": {
                        "stage": failure_stage,
                        "error": failure_error,
                        "safety_report": tool_builder_state.get("safety_report"),
                        "test_result": tool_builder_state.get("test_result"),
                    },
                },
            )
            return {
                "learning_candidate_id": candidate_id,
                "adoption_prompt": _adoption_prompt(candidate_id, "counterexample"),
                "tool_builder": {**tool_builder_state, "evaluation": tool_evaluation},
                "execution_path": state.get("execution_path", []) + ["learn_generated_tool"],
            }
        tool_result = ToolExecutionResult(
            tool_id=str(metadata.get("id")),
            tool_name=str(metadata.get("name") or metadata.get("id")),
            success=True,
            stable_rule_candidate=True,
            candidate_type="rule",
            content=str((tool_builder_state.get("test_result") or {}).get("content") or ""),
            data={
                "generated_tool": metadata,
                "tool_builder": {
                    "safety_report": tool_builder_state.get("safety_report"),
                    "test_result": tool_builder_state.get("test_result"),
                },
            },
            permission=Permission(str(metadata.get("permission") or "confirm")),
            risk=ToolRisk(str(metadata.get("risk") or "medium")),
            read_only=bool(metadata.get("read_only")),
        )
        candidate_id, candidate = self.review_store.create_capability_candidate(
            question=state["question"],
            task_type=state.get("task_type", "general"),
            intent_keywords=state.get("intent_keywords", []),
            tool_result=tool_result,
            context=_context_with_evaluation(state, tool_evaluation),
            llm_draft={
                "stability_decision": "tool_builder_generated_rule_candidate",
                "rule": "该能力由受控 Tool Builder 生成、静态校验并 dry-run 测试通过。",
                "required_human_review": [
                    "确认适用范围",
                    "确认权限和外部副作用",
                    "确认测试覆盖真实失败兜底",
                ],
            },
        )
        return {
            "learning_candidate_id": candidate_id,
            "adoption_prompt": _adoption_prompt(candidate_id, candidate.get("candidate_type")),
            "tool_builder": {**tool_builder_state, "evaluation": tool_evaluation},
            "exploration": {
                **state.get("exploration", {}),
                "candidate_id": candidate_id,
                "candidate_type": candidate.get("candidate_type"),
            },
            "execution_path": state.get("execution_path", []) + ["learn_generated_tool"],
        }

    def _draft_candidate(
        self,
        state: AgentState,
        candidate_type: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self.chat_model.draft_learning_candidate(
                question=state["question"],
                candidate_type=candidate_type,
                evidence=evidence,
                context=state.get("context", {}),
            )
        except Exception as exc:  # noqa: BLE001 - draft generation must not block flow
            return {"draft_error": str(exc)}

    def reason(self, state: AgentState) -> dict[str, Any]:
        runtime_execution = (state.get("agent_skill_runtime") or {}).get("execution") or {}
        if runtime_execution.get("requires_confirmation"):
            return {
                "answer": state.get("answer", ""),
                "confidence": state.get("confidence", 0.45),
                "requires_confirmation": True,
                "routing_policy": {
                    **state.get("routing_policy", {}),
                    "final_route": state.get("route") or "skills",
                },
                "execution_path": state.get("execution_path", []) + ["reason_waiting_confirmation"],
            }
        memory_context = self.personal_memory.retrieve(
            state["question"],
            state.get("context", {}),
        )
        context = dict(state.get("context", {}))
        context["memory"] = memory_context.to_dict()
        context["task_type"] = state.get("task_type", "general")
        context["intent_keywords"] = state.get("intent_keywords", [])
        errors = list(state.get("errors", []))
        confidence = 0.75
        fast_answer = fast_rule_answer(state)
        if fast_answer is not None:
            return {
                "answer": fast_answer,
                "confidence": 0.95,
                "memory_used": memory_context.preferences,
                "counterexamples_checked": memory_context.counterexamples,
                "errors": errors,
                "routing_policy": {
                    **state.get("routing_policy", {}),
                    "final_route": state.get("route") or "rules",
                    "reason_fast_path": True,
                },
                "execution_path": state.get("execution_path", []) + ["reason_fast_path"],
            }
        try:
            answer = self.chat_model.generate(
                question=state["question"],
                deterministic_results=state.get("deterministic_results", []),
                skills=state.get("matched_skills", []),
                context=context,
            )
        except Exception as exc:  # noqa: BLE001 - model boundary must not break graph
            errors.append(f"model_generate_failed:{exc}")
            confidence = 0.55
            answer = fallback_answer(state, context)
        return {
            "answer": answer,
            "confidence": confidence,
            "memory_used": memory_context.preferences,
            "counterexamples_checked": memory_context.counterexamples,
            "errors": errors,
            "routing_policy": {
                **state.get("routing_policy", {}),
                "final_route": state.get("route") or "reason",
            },
            "execution_path": state.get("execution_path", []) + ["reason"],
        }

    def general_reason(self, state: AgentState) -> dict[str, Any]:
        memory_context = self.personal_memory.retrieve(
            state["question"],
            state.get("context", {}),
        )
        context = dict(state.get("context", {}))
        context["memory"] = memory_context.to_dict()
        context["task_type"] = state.get("task_type", "general")
        context["intent_keywords"] = state.get("intent_keywords", [])
        errors = list(state.get("errors", []))
        if is_personal_advice_task(
            state.get("task_type", "general"),
            state.get("intent_keywords", []),
        ):
            answer = personal_advice_answer(
                state["question"],
                state.get("task_type", "general"),
                context,
            )
            clarification_questions = personal_advice_clarification_questions(
                state.get("task_type", "general")
            )
        else:
            try:
                answer = self.chat_model.generate(
                    question=state["question"],
                    deterministic_results=[],
                    skills=[],
                    context=context,
                )
            except Exception as exc:  # noqa: BLE001 - model boundary must not block fallback
                errors.append(f"model_generate_failed:{exc}")
                answer = general_knowledge_fallback(state["question"])
            if is_generic_missing_capability_answer(answer):
                answer = general_knowledge_fallback(state["question"])
            clarification_questions = []
        return {
            "route": "general_reason",
            "answer": answer,
            "confidence": 0.65,
            "clarification_questions": clarification_questions,
            "routing_policy": {
                **state.get("routing_policy", {}),
                "final_route": "general_reason",
            },
            "memory_used": memory_context.preferences,
            "counterexamples_checked": memory_context.counterexamples,
            "errors": errors,
            "execution_path": state.get("execution_path", []) + ["general_reason"],
        }

    def evaluate(self, state: AgentState) -> dict[str, Any]:
        evaluation = self.ask_evaluator.evaluate(state).to_dict()
        failed_checks = evaluation.get("failed_checks", [])
        violations = [
            f"evaluation_failed:{item}"
            for item in failed_checks
            if item
            and item
            not in {
                "tool_builder_permission_policy",
                "tool_builder_present",
            }
        ]
        for hit in evaluation.get("counterexample_hits", []) or []:
            if isinstance(hit, dict):
                violations.append(f"counterexample_triggered:{hit.get('id', 'unknown')}")
        current_confidence = float(state.get("confidence", 0.75) or 0.75)
        score = float(evaluation.get("score", current_confidence) or current_confidence)
        confidence = min(current_confidence, max(0.2, score))
        result: dict[str, Any] = {
            "evaluation": evaluation,
            "confidence": confidence,
            "execution_path": state.get("execution_path", []) + ["evaluate"],
        }
        if evaluation.get("requires_confirmation"):
            result["requires_confirmation"] = True
        if violations:
            result["errors"] = state.get("errors", []) + violations
            return result
        return {
            **result,
            "errors": state.get("errors", []),
        }

    def learn(self, state: AgentState) -> dict[str, Any]:
        feedback = state.get("feedback")
        if not feedback:
            return {
                "learning_candidate_id": state.get("learning_candidate_id"),
                "adoption_prompt": state.get("adoption_prompt"),
                "execution_path": state.get("execution_path", []) + ["learn"],
            }
        candidate_id = self.review_store.create_candidate(
            question=state["question"],
            feedback=feedback,
            context=_context_with_evaluation(state, state.get("evaluation")),
        )
        return {
            "learning_candidate_id": candidate_id,
            "adoption_prompt": _adoption_prompt(candidate_id, None),
            "execution_path": state.get("execution_path", []) + ["learn"],
        }

    def try_adopt_latest(self, state: AgentState) -> dict[str, Any] | None:
        question = state["question"]
        context = state.get("context", {})
        if context.get("disable_adoption"):
            return None
        candidate_id = context.get("candidate_id")
        if not candidate_id and not _is_affirmative_adoption(question):
            return None
        if not candidate_id:
            latest = self.review_store.latest_pending()
            if not latest:
                return {
                    "answer": "当前没有待沉淀的 Rules 或 Skills。",
                    "confidence": 0.4,
                    "adopted_candidate_id": None,
                }
            candidate_id = latest["id"]
        try:
            path = self.review_store.approve(str(candidate_id))
        except FileNotFoundError:
            return {
                "answer": f"没有找到待沉淀候选：{candidate_id}",
                "confidence": 0.2,
                "adopted_candidate_id": None,
            }
        return {
            "answer": f"已沉淀候选 {candidate_id}，正式文件：{path}",
            "confidence": 0.9,
            "adopted_candidate_id": str(candidate_id),
            "adopted_path": str(path),
            "learning_candidate_id": str(candidate_id),
        }


def has_rules(state: AgentState) -> str:
    if state.get("adopted_candidate_id"):
        return "adopted"
    return "rules" if state.get("matched_rules") else "skills"


def has_skills(state: AgentState) -> str:
    if state.get("adopted_candidate_id"):
        return "adopted"
    return "skills" if state.get("matched_skills") else "need_more_info"


def capability_solved(state: AgentState) -> str:
    exploration = state.get("exploration", {})
    if exploration.get("success"):
        return "solved"
    if exploration.get("tool_found"):
        return "tool_failed"
    return "unsolved"


def tool_spec_discovered(state: AgentState) -> str:
    if state.get("tool_builder", {}).get("spec"):
        return "discovered"
    if _should_general_reason(state):
        return "general_reason"
    return "not_discovered"


def tool_code_drafted(state: AgentState) -> str:
    return "drafted" if state.get("tool_builder", {}).get("draft") else "failed"


def tool_code_valid(state: AgentState) -> str:
    report = state.get("tool_builder", {}).get("safety_report") or {}
    return "valid" if report.get("passed") else "invalid"


def tool_test_passed(state: AgentState) -> str:
    result = state.get("tool_builder", {}).get("test_result") or {}
    return "passed" if result.get("success") else "failed"


def generated_tool_ready(state: AgentState) -> str:
    return "ready" if state.get("tool_builder", {}).get("success") else "failed"


def _intent_keywords(question: str) -> list[str]:
    mapping = {
        "chart": ["图表", "趋势", "折线图", "柱状图", "环比", "同比"],
        "calculation": ["计算", "公式", "百分比", "%"],
        "report_writing": ["周报", "月报", "总结", "汇报", "复盘"],
        "sales_support": ["销售", "拜访", "客户", "甲方", "乙方", "商机"],
        "meeting_preparation": ["会议", "会前", "参会", "议程", "主持", "启动会"],
        "planning_advice": ["计划", "安排", "准备什么", "应该准备", "怎么准备"],
        "communication_advice": ["沟通", "谈判", "推进", "说服", "话术"],
        "personal_advice": ["建议", "怎么办", "应该怎么", "如何处理"],
        "weather_query": ["天气", "气温", "降水", "风速"],
        "integration": ["飞书", "Lark", "对接", "消息", "发送"],
        "sports_query": ["NBA", "比赛", "赛程", "球队", "赛事"],
    }
    found: list[str] = []
    for intent, words in mapping.items():
        if any(word in question for word in words):
            found.append(intent)
    return found or ["general"]


def _task_type(question: str, keywords: list[str]) -> str:
    if "chart" in keywords:
        return "chart_selection"
    if "calculation" in keywords:
        return "calculation"
    if "report_writing" in keywords:
        return "report_writing"
    if "sales_support" in keywords:
        return "sales_support"
    if "meeting_preparation" in keywords:
        return "meeting_preparation"
    if "planning_advice" in keywords:
        return "planning_advice"
    if "communication_advice" in keywords:
        return "communication_advice"
    if "personal_advice" in keywords:
        return "personal_advice"
    if "weather_query" in keywords:
        return "weather_query"
    if "integration" in keywords:
        return "integration"
    if "sports_query" in keywords:
        return "sports_query"
    return "general"


def _likely_code_candidate(question: str) -> bool:
    return any(
        hint in question
        for hint in [
            "对接",
            "接口",
            "API",
            "代码",
            "工具",
            "自动",
            "SQL",
            "集成",
            "调用",
        ]
    )


def _explicit_tool_build_requested(question: str) -> bool:
    return "工具" in question and any(
        hint in question
        for hint in [
            "生成",
            "创建",
            "构建",
            "开发",
            "写一个",
            "做一个",
            "沉淀",
            "复用",
        ]
    )


def _explicit_learning_requested(question: str) -> bool:
    return any(
        hint in question
        for hint in [
            "沉淀",
            "记住",
            "以后",
            "规则",
            "作为skill",
            "作为Skill",
            "复用",
        ]
    )


def _likely_memory_candidate(question: str) -> bool:
    return any(hint in question for hint in ["我喜欢", "我偏好", "以后", "默认", "习惯", "我的"])


def _should_general_reason(state: AgentState) -> bool:
    return RoutingPolicy().prefer_general_reason(state)


def _can_skip_llm_classify(state: AgentState) -> bool:
    keyword = ClassificationResult.from_dict(
        state.get("keyword_classification", {}),
        source="keyword",
    )
    if keyword.confidence < 0.8:
        return False
    if keyword.required_tools:
        return False
    return keyword.task_type in {
        "calculation",
        "date_calculation",
        "unit_conversion",
    }


def _clarification_questions_for_task(task_type: str) -> list[str]:
    if is_personal_advice_task(task_type):
        return personal_advice_clarification_questions(task_type)
    if task_type == "calculation":
        return [
            "请提供需要计算的字段定义、计算口径和必要数值。",
            "请确认输出格式，例如百分比、小数位、日期范围或是否需要表格。",
            "如果这是固定业务口径，请说明是否需要沉淀为 Rule。",
        ]
    if task_type == "integration":
        return [
            "请确认要对接的系统、公开文档地址和鉴权方式。",
            "请提供输入参数、输出字段、失败兜底和是否允许外部写操作。",
            "如果涉及发送消息、写数据或调用外部系统，请确认是否允许执行副作用。",
        ]
    if task_type == "report_writing":
        return [
            "请补充报告目标、受众和希望采用的结构。",
            "请提供已有事实、数据、结论或需要避免的表达边界。",
            "请确认输出格式，例如摘要、完整报告、表格或行动清单。",
        ]
    return [
        "请补充这个问题所属的业务场景或分析目标。",
        "如果涉及计算，请提供字段定义、计算口径和必要数值。",
        "如果涉及外部查询或系统对接，请确认公开文档、鉴权配置、输入参数、输出字段和失败兜底。",
    ]


def _context_with_evaluation(
    state: AgentState,
    evaluation: dict[str, Any] | None,
) -> dict[str, Any]:
    context = dict(state.get("context", {}))
    if evaluation:
        context["_evaluation"] = evaluation
    return context


def _is_affirmative_adoption(text: str) -> bool:
    normalized = text.strip().lower()
    if normalized in {"同意", "采用", "批准", "确认", "可以", "yes", "y"}:
        return True
    return any(
        phrase in normalized
        for phrase in [
            "同意沉淀",
            "同意采用",
            "采用这个",
            "采用该",
            "批准沉淀",
            "确认沉淀",
            "approve",
            "adopt",
        ]
    )


def _adoption_prompt(candidate_id: str | None, candidate_type: str | None) -> str | None:
    if not candidate_id:
        return None
    label = {
        "rule": "Rule",
        "skill": "Skill",
        "memory": "Memory",
        "counterexample": "反例",
    }.get(str(candidate_type), "候选")
    return (
        f"是否同意将本次结果沉淀为正式 {label}？"
        f"同意请回复“同意沉淀 {candidate_id}”或执行 monkey adopt {candidate_id}。"
    )

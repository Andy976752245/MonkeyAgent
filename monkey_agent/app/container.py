from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from monkey_agent.core.config import Settings
from monkey_agent.core.users import PersonalWorkspace
from monkey_agent.domains.agent_skills import (
    AgentSkillInstaller,
    AgentSkillRepository,
    AgentSkillRuntime,
    AgentSkillScriptSelector,
)
from monkey_agent.domains.classifier import QuestionClassifier
from monkey_agent.domains.goals.store import GoalStore
from monkey_agent.domains.learning.review_store import ReviewStore
from monkey_agent.domains.learning.usage_memory import UsageMemory
from monkey_agent.domains.memory import PersonalMemoryStore
from monkey_agent.domains.models.bailian import ChatModel
from monkey_agent.domains.rules.repository import RuleRepository
from monkey_agent.domains.runs import RunStore
from monkey_agent.domains.skills.repository import SkillRepository
from monkey_agent.domains.tool_builder import ToolBuilderService
from monkey_agent.domains.tools import ToolRegistry
from monkey_agent.domains.tools.capability import CapabilityRegistry
from monkey_agent.domains.tools.generated import GeneratedToolStore
from monkey_agent.workflows.ask.nodes import GraphNodes
from monkey_agent.workflows.ask.workflow import build_workflow
from monkey_agent.workflows.goal.evaluator import GoalEvaluator
from monkey_agent.workflows.goal.executor import GoalExecutor
from monkey_agent.workflows.goal.planner import CompositeGoalPlanner
from monkey_agent.workflows.goal.workflow import build_goal_workflow


@dataclass
class ServiceContainer:
    personal_workspace: PersonalWorkspace
    rules: RuleRepository
    skills: SkillRepository
    agent_skills: AgentSkillRepository
    agent_skill_installer: AgentSkillInstaller
    agent_skill_runtime: AgentSkillRuntime
    agent_skill_script_selector: AgentSkillScriptSelector
    review_store: ReviewStore
    usage_memory: UsageMemory
    personal_memory: PersonalMemoryStore
    global_generated_tool_store: GeneratedToolStore
    generated_tool_store: GeneratedToolStore
    tool_registry: ToolRegistry
    capability_registry: CapabilityRegistry
    classifier: QuestionClassifier
    tool_builder: ToolBuilderService
    goal_store: GoalStore
    run_store: RunStore
    nodes: GraphNodes
    workflow: Any
    goal_workflow: Any


def build_service_container(
    settings: Settings,
    chat_model: ChatModel,
    base_tools: list[Any],
    ask_for_goal: Any,
) -> ServiceContainer:
    personal_workspace = PersonalWorkspace.from_runtime(settings.runtime_dir)
    personal_workspace.ensure()

    rules = RuleRepository(
        personal_workspace.rules_dir,
        fallback_dirs=[settings.rules_dir],
    )
    skills = SkillRepository(
        personal_workspace.skills_dir,
        fallback_dirs=[settings.skills_dir],
    )
    agent_skills = AgentSkillRepository(
        personal_workspace.agent_skills_dir,
        personal_workspace.agent_skills_registry,
    )
    agent_skill_installer = AgentSkillInstaller(
        personal_workspace.agent_skills_dir,
        agent_skills,
    )
    agent_skill_runtime = AgentSkillRuntime(
        personal_workspace.artifacts_dir,
        timeout_seconds=settings.agent_skill_script_timeout,
    )
    agent_skill_script_selector = AgentSkillScriptSelector(chat_model)
    review_store = ReviewStore(
        personal_workspace.pending_review_dir,
        personal_workspace.rules_dir,
        personal_workspace.skills_dir,
        personal_workspace.memory_dir,
        personal_workspace.counterexamples_dir,
    )
    usage_memory = UsageMemory(
        personal_workspace.memory_dir,
        repeat_threshold=settings.learning_repeat_threshold,
    )
    personal_memory = PersonalMemoryStore(
        personal_workspace.memory_dir,
        personal_workspace.counterexamples_dir,
        fallback_memory_dirs=[settings.memory_dir],
        fallback_counterexamples_dirs=[settings.counterexamples_dir],
    )
    global_generated_tool_store = GeneratedToolStore(
        settings.generated_tools_dir,
        settings.generated_tools_registry,
    )
    generated_tool_store = GeneratedToolStore(
        personal_workspace.generated_tools_dir,
        personal_workspace.generated_tools_registry,
    )
    tool_registry = ToolRegistry(list(base_tools))
    for tool in global_generated_tool_store.enabled_tools():
        tool_registry.add(tool)
    for tool in generated_tool_store.enabled_tools():
        tool_registry.add(tool)
    capability_registry = CapabilityRegistry(tool_registry.tools)
    classifier = QuestionClassifier(chat_model)
    tool_builder = ToolBuilderService(
        chat_model,
        generated_tool_store,
        personal_workspace.root,
    )
    goal_store = GoalStore(personal_workspace.goals_dir)
    run_store = RunStore(personal_workspace.runs_dir)
    nodes = GraphNodes(
        rules,
        skills,
        agent_skills,
        chat_model,
        review_store,
        capability_registry,
        usage_memory,
        classifier,
        personal_memory,
        tool_builder,
        tool_registry,
        agent_skill_runtime,
        agent_skill_script_selector,
    )
    workflow = build_workflow(nodes)
    goal_workflow = build_goal_workflow(
        goal_store,
        CompositeGoalPlanner(chat_model),
        GoalExecutor(ask_for_goal, review_store),
        GoalEvaluator(),
    )
    return ServiceContainer(
        personal_workspace=personal_workspace,
        rules=rules,
        skills=skills,
        agent_skills=agent_skills,
        agent_skill_installer=agent_skill_installer,
        agent_skill_runtime=agent_skill_runtime,
        agent_skill_script_selector=agent_skill_script_selector,
        review_store=review_store,
        usage_memory=usage_memory,
        personal_memory=personal_memory,
        global_generated_tool_store=global_generated_tool_store,
        generated_tool_store=generated_tool_store,
        tool_registry=tool_registry,
        capability_registry=capability_registry,
        classifier=classifier,
        tool_builder=tool_builder,
        goal_store=goal_store,
        run_store=run_store,
        nodes=nodes,
        workflow=workflow,
        goal_workflow=goal_workflow,
    )

"""Runtime Factory: the single assembly entry point.

CLI, MCP server, and Web API all build their runtime through
:func:`create_runtime` so there is exactly one initialization path. The factory
assembles core layers only (storage, llm, tools, skills, security); transport
wiring (MCP clients) and growth wiring (evolution) are attached by entry
points, keeping ``runtime`` free of ``Sprout.mcp`` and ``Sprout.evolution``
imports.
"""

from __future__ import annotations

import os
from pathlib import Path

from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.agent.planner import DirectPlanner
from Sprout.config.loader import load_settings
from Sprout.config.settings import ModelSettings, Settings
from Sprout.events import EventBus, register_builtin_events
from Sprout.llm.aiyallm import AiyallmProvider
from Sprout.llm.base import ModelProvider
from Sprout.llm.echo import EchoModel
from Sprout.llm.openai_compatible import ModelAuthError, OpenAICompatibleProvider
from Sprout.llm.orchestrator import ModelOrchestrator
from Sprout.llm.registry import ModelRegistry
from Sprout.orchestration.terminal import (
    LocalOrchestratorBackend,
    TemporalOrchestratorBackend,
)
from Sprout.runtime.queue import TaskQueueBackend
from Sprout.runtime.runtime import Runtime
from Sprout.security.layer import SecurityLayer
from Sprout.security.secrets import resolve_api_key
from Sprout.skills.index import SkillIndex
from Sprout.skills.layout import index_path
from Sprout.skills.registry import create_skill_registry
from Sprout.storage.bundle import StorageBundle, create_storage
from Sprout.storage.local.sqlite.driver import SqlitePragmas
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry, create_tool_registry


def create_runtime(
    settings: Settings | None = None,
    *,
    task_queue: TaskQueueBackend | None = None,
) -> Runtime:
    """Assemble a Runtime from settings (loaded from the default search path)."""
    settings = settings or load_settings()
    sqlite_cfg = settings.sqlite
    pragmas = SqlitePragmas(
        busy_timeout_ms=sqlite_cfg.busy_timeout_ms,
        synchronous=sqlite_cfg.synchronous,
        wal_autocheckpoint=sqlite_cfg.wal_autocheckpoint,
        mmap_size=sqlite_cfg.mmap_size,
        readers=sqlite_cfg.readers,
    )
    storage = create_storage(settings.storage, pragmas=pragmas, memory_settings=settings.memory)
    models = create_model_registry(settings.model)

    # One authorization layer for the whole process: hard floor, rule layers,
    # command/secrets allowlists, SSRF guard, audit stream, approvals (AUTHZ §8).
    # It is assembled *before* the tools so the CLI tools can borrow the guard
    # and the secret broker instead of reinventing weaker versions of them.
    events = register_builtin_events(EventBus())
    # Message-persistence strategy (MESSAGE_PERSISTENCE.md M2): every bus
    # event lands in the observations lane. Fail-open inside the recorder, so
    # a cold observations store never takes the online turn path down.
    if storage.observations is not None:
        from Sprout.events.recorder import ObservationRecorder

        events.subscribe("*", ObservationRecorder(storage.observations))
    # The tool-risk floor grades a tool by looking it up in the registry, never
    # by trusting a risk level that travelled in the request (AUTHZ §6.1). The
    # closure resolves the registry lazily because the layer is assembled first.
    assembled: dict[str, ToolRegistry] = {}

    def tool_risk_lookup(name: str) -> str:
        registry = assembled.get("tools")
        if registry is None:
            raise LookupError("tool registry is not assembled yet")
        return str(registry.get(name).spec.risk_level)

    security = SecurityLayer.from_settings(
        settings.security,
        store=storage.operational,
        events=events,
        tool_risk_lookup=tool_risk_lookup,
    )

    tools = create_tool_registry(
        storage,
        security=security,
        workspace_root=Path.cwd(),
        skills_dir=settings.skills_dir,
    )
    assembled["tools"] = tools
    # The index snapshot is the authority on what was approved (design §8.3);
    # passing it lets a downloaded skill be trusted only while its content still
    # matches the digest that was approved. Without it, managed skills stay
    # untrusted rather than defaulting to trusted.
    skill_index = SkillIndex(index_path(settings.skills_dir))
    skills = create_skill_registry(settings.skills_dir, index=skill_index)

    runtime = Runtime(
        storage=storage,
        models=models,
        tools=tools,
        skills=skills,
        events=events,
        policy_engine=security.policy_engine,
        trajectory_dir=Path(settings.storage.trajectory_dir),
        default_agent=settings.runtime.default_agent,
        security=security,
        skills_dir=settings.skills_dir,
        # Temporal is the production orchestration authority. Local execution
        # remains the offline default so tests and single-process runtimes do
        # not block waiting for a Temporal worker. TEMPORAL_HOST opts into the
        # durable backend explicitly.
        orchestrator_backend=(
            TemporalOrchestratorBackend(metadata=storage.metadata)
            if os.getenv("TEMPORAL_HOST")
            else LocalOrchestratorBackend(storage.metadata or storage.operational)
        ),
        task_queue=task_queue,
        settings=settings,
    )

    tool_executor = ToolExecutor(
        tools=tools,
        policy=security.tool_policy,
        approvals=security.approvals,
        events=runtime.events,
        audit=security.audit,
        # Lets a read-only cli_tool_run (``pwd``, ``git status``) skip the
        # prompt instead of asking again for a command that cannot change
        # anything. Commands that can run workspace-authored code keep asking.
        commands=security.commands,
    )
    agent = AgentLoop(
        model=models.default(),
        executor=ActionExecutor(tools=tool_executor),
        max_steps=settings.runtime.max_tool_steps,
        planner=DirectPlanner(),
    )
    runtime.register_agent(settings.runtime.default_agent, agent, default=True)
    from Sprout.tools.workspace_query_tool import WorkspaceQueryTool

    runtime.tools.register(WorkspaceQueryTool(runtime.analyze_workspace))
    return runtime


def create_model_registry(settings: ModelSettings) -> ModelRegistry:
    """Register the configured providers with retry and fallback."""
    registry = ModelRegistry()
    provider_name = settings.provider
    registry.register(EchoModel(), default=provider_name == "echo")
    if provider_name == "echo":
        return registry

    providers = [
        _build_provider(
            provider_name,
            settings.model,
            settings.base_url,
            settings.api_key_env,
            settings,
        )
    ]
    if settings.fallback_provider:
        providers.append(
            _build_provider(
                settings.fallback_provider,
                settings.fallback_model or settings.model,
                settings.fallback_base_url or settings.base_url,
                settings.fallback_api_key_env or settings.api_key_env,
                settings,
            )
        )
    registry.register(ModelOrchestrator(providers=providers), default=True)
    return registry


def _build_provider(
    provider_name: str,
    model: str,
    base_url: str,
    api_key_env: str,
    settings: ModelSettings,
) -> ModelProvider:
    if provider_name not in {"aiyallm", "openai_compatible"}:
        raise ValueError(
            f"Unknown model provider {provider_name!r}; "
            "expected 'echo', 'aiyallm', or 'openai_compatible'"
        )
    if provider_name == "aiyallm":
        # aiyallm keeps provider configuration in the package, while model
        # families still use their own local credential variables. Resolve the
        # family key here without requiring api_key_env in Sprout's TOML.
        family = model.split("-", 1)[0].split("/", 1)[0]
        model_api_key = settings.api_key or resolve_api_key(family)
        return AiyallmProvider(
            model=model,
            base_url=base_url,
            api_key=model_api_key,
            api_key_env=None,
            providers=settings.providers,
            name=provider_name,
            timeout_seconds=settings.timeout_seconds,
            temperature=settings.temperature,
        )
    api_key = resolve_api_key(provider_name, env_name=api_key_env)
    if not api_key:
        raise ModelAuthError(
            f"No API key for provider {provider_name!r}; set {api_key_env} "
            "in the environment"
        )
    return OpenAICompatibleProvider(
        model=model,
        base_url=base_url,
        api_key=api_key,
        name=provider_name,
        timeout_seconds=settings.timeout_seconds,
        temperature=settings.temperature,
    )


__all__ = ["Runtime", "StorageBundle", "create_model_registry", "create_runtime"]

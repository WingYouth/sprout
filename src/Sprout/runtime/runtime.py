"""Runtime: coordinates one online turn.

The Runtime knows about agents, sessions, context, tools, and skills. It never
knows about transports (CLI, MCP, Web), vendors, or the growth layer; see
``Sprout.runtime.factory`` for assembly and the constraint docs in the README.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from Sprout.agent.base import Agent, AgentResult
from Sprout.agent.router import AgentRouter
from Sprout.context.builder import ContextBuilder
from Sprout.events import (
    AGENT_COMPLETED,
    AGENT_FAILED,
    AGENT_STARTED,
    INTENT_APPROVAL_REQUESTED,
    INTENT_CONVERSATION_REQUESTED,
    INTENT_EVOLUTION_REQUESTED,
    INTENT_MEMORY_REQUESTED,
    INTENT_RECOGNIZED,
    INTENT_STRATEGY_REQUESTED,
    INTENT_TASK_REQUESTED,
    INTENT_TOOL_REQUESTED,
    INTENT_WORKSPACE_REQUESTED,
    MESSAGE_PERSISTED,
    MESSAGE_RECEIVED,
    MESSAGE_SENT,
    RUNTIME_STARTED,
    RUNTIME_STOPPED,
    SESSION_CREATED,
    Event,
    EventBus,
    register_builtin_events,
)
from Sprout.execution.apply import ApplyBroker
from Sprout.execution.database_broker import DatabaseBroker
from Sprout.execution.file_broker import FileBroker
from Sprout.execution.git_broker import GitBroker
from Sprout.execution.models import (
    ApplyResult,
    ChangeProposal,
    ChangeProposalStatus,
    ProcessResult,
    SandboxRef,
)
from Sprout.execution.network_broker import NetworkBroker
from Sprout.execution.process_broker import ProcessBroker
from Sprout.execution.sandbox_tool import SandboxReadTool
from Sprout.gateway.identity import Principal
from Sprout.intents import Intent, detect_task_hint, intent_event
from Sprout.llm.language import detect_language
from Sprout.llm.messages import LLMMessage
from Sprout.message.attachment import Attachment
from Sprout.message.converter import assistant_envelope, turn_envelope
from Sprout.message.models import Message, OutboundMessage, StreamChunk
from Sprout.orchestration.compiler import ExecutionGraphBuilder
from Sprout.orchestration.models import ExecutionGraph, ExecutionNode, NodeStatus
from Sprout.orchestration.terminal import TemporalOrchestratorBackend
from Sprout.registry.base import Registry
from Sprout.rootstock.contract import SessionStore
from Sprout.runtime.changes import ChangeProposalService
from Sprout.runtime.locks import WorkspaceLockManager
from Sprout.runtime.middleware import LoggingMiddleware, MiddlewareChain
from Sprout.runtime.nodes import NodeExecutor
from Sprout.runtime.queue import TaskQueueBackend, create_task_queue
from Sprout.runtime.result import RuntimeInfo
from Sprout.runtime.state import NodeStateMachine, TaskStateMachine
from Sprout.runtime.workspaces import WorkspaceService
from Sprout.sandbox.lifecycle import SandboxLifecycleService
from Sprout.security.approval import ApprovalManager, ApprovalRecord, ApprovalStatus
from Sprout.security.audit import SecurityAuditLog
from Sprout.security.engine import PolicyEngine
from Sprout.security.layer import SecurityLayer
from Sprout.security.layered_policy import LayeredPolicyEngine
from Sprout.security.redact import Redactor
from Sprout.security.secrets import EnvSecretProvider, SecretProvider
from Sprout.session.manager import SessionManager
from Sprout.session.models import Session, Turn
from Sprout.skills.models import Skill
from Sprout.skills.resolver import SkillResolver
from Sprout.storage.contracts.knowledge import KnowledgeItem
from Sprout.storage.contracts.metadata import MetadataStore
from Sprout.storage.embeddings import HashingEmbedder
from Sprout.storage.lanes import CONTEXT_SNAPSHOTS_NS
from Sprout.task.models import (
    DelegationScope,
    Task,
    TaskBudget,
    TaskResult,
    TaskStatus,
)
from Sprout.trajectory.models import ArtifactSnapshot, TrajectoryEvent
from Sprout.trajectory.recorder import JsonlTrajectoryRecorder, trajectory_path
from Sprout.workspace.intelligence import WorkspaceAnalysis
from Sprout.workspace.models import ReadPlan, Workspace, WorkspaceManifest
from Sprout.workspace.read_broker import ReadBroker
from Sprout.workspace.scanner import WorkspaceScanner

logger = logging.getLogger("Sprout.runtime")

_DEFAULT_TRAJECTORY_DIR = Path.home() / ".sprout" / "data" / "trajectory"

_INTENT_EVENTS: dict[str, str] = {
    "conversation": INTENT_CONVERSATION_REQUESTED,
    "task": INTENT_TASK_REQUESTED,
    "workspace": INTENT_WORKSPACE_REQUESTED,
    "tool": INTENT_TOOL_REQUESTED,
    "approval": INTENT_APPROVAL_REQUESTED,
    "memory": INTENT_MEMORY_REQUESTED,
    "evolution": INTENT_EVOLUTION_REQUESTED,
    "strategy": INTENT_STRATEGY_REQUESTED,
}
_PROJECT_ANALYZE_TERMS = (
    "scan project",
    "analyze project",
    "inspect project",
    "project structure",
    "entry file",
    "dependencies",
    "manifest",
    "docker",
    "workspace",
    "扫描项目",
    "掃描專案",
    "分析项目",
    "分析專案",
    "项目结构",
    "專案結構",
    "入口文件",
    "依赖",
    "依賴",
    "プロジェクトをスキャン",
    "プロジェクトを分析",
    "構成",
    "依存関係",
    "프로젝트 스캔",
    "프로젝트 분석",
    "프로젝트 구조",
    "의존성",
    "сканируй проект",
    "проанализируй проект",
    "структура проекта",
    "зависимости",
    "analizar proyecto",
    "escanear proyecto",
    "estructura del proyecto",
    "dependencias",
    "analisar projeto",
    "escanear projeto",
    "estrutura do projeto",
    "dependências",
)


def _package_version() -> str:
    try:
        return version("seam-sprout")
    except PackageNotFoundError:
        return "0.0.0.dev0"


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, score))


def _parse_intent_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {"intent": "conversation", "confidence": 0.0, "reason": "empty_llm_response"}
    if "```" in stripped:
        chunks = stripped.split("```")
        stripped = next(
            (
                chunk.removeprefix("json").strip()
                for chunk in chunks
                if chunk.strip().startswith(("{", "json"))
            ),
            stripped,
        )
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return {"intent": "conversation", "confidence": 0.0, "reason": "invalid_llm_json"}
    return parsed if isinstance(parsed, dict) else {"intent": "conversation"}


def _agent_metadata(metadata: Mapping[str, Any]) -> Mapping[str, Any]:
    if metadata.get("approval_required") or metadata.get("pending_tool_calls"):
        return metadata
    agent = metadata.get("agent")
    if isinstance(agent, Mapping):
        return agent
    return {}


def _project_analyze_tool_call(message: Message, intent: str) -> dict[str, Any] | None:
    if intent != "workspace":
        return None
    text = message.content.casefold()
    if not any(term.casefold() in text for term in _PROJECT_ANALYZE_TERMS):
        return None
    metadata = dict(message.metadata)
    raw_path = (
        metadata.get("workspace_path")
        or metadata.get("project_path")
        or metadata.get("path")
        or metadata.get("root")
        or Path.cwd().as_posix()
    )
    path = str(raw_path)
    return {
        "id": "intent-project-analyze",
        "name": "project_analyze",
        "arguments": {
            "path": path,
            "instruction": message.content,
        },
    }


def _weighted_context_summary(text: str, score: float) -> dict[str, Any]:
    weight = _clamp_float(score, default=0.0)
    sentences = _split_sentences(text)
    if weight >= 0.72:
        detail_level = "high"
        distilled = " ".join(sentences[:6])[:2000] if sentences else text[:2000]
    elif weight >= 0.38:
        detail_level = "medium"
        distilled = " ".join(sentences[:3])[:900] if sentences else text[:900]
    else:
        detail_level = "low"
        distilled = _abstract_context_sentence(sentences, text)
    return {
        "context_weight": round(weight, 4),
        "detail_level": detail_level,
        "distilled_text": distilled,
    }


def _split_sentences(text: str) -> list[str]:
    import re

    pieces = re.split(r"(?<=[。！？.!?])\s+|\n+", text.strip())
    return [piece.strip() for piece in pieces if piece.strip()]


def _abstract_context_sentence(sentences: list[str], text: str) -> str:
    source = sentences[0] if sentences else text.strip()
    if not source:
        return ""
    words = source.split()
    if len(words) > 28:
        return " ".join(words[:28]) + " ..."
    return source[:280]


#: Turn bodies larger than this are offloaded to the blobstore and the turn
#: keeps a preview plus the envelope reference (RUNTIME_DATA_PLAN §2.5).
TURN_BLOB_THRESHOLD_BYTES = 8192

#: How much of an offloaded body stays inline in the turn row.
TURN_PREVIEW_CHARS = 4096

#: Marks a held user turn as awaiting an answer to "which workspace?". The turn
#: is persisted under this key so the consent survives the process that asked
#: for it, and is consumed exactly once.
WORKSPACE_CONSENT_KEY = "workspace_consent_required"

#: Set by the agent loop when the model invoked ``request_workspace``. The
#: agent knows what the user meant from the whole turn; the text-level gate can
#: only guess from the wording, and a typo or an unusual phrasing defeats it.
#: This is the reliable route, and the keyword route stays as the cheap one.
WORKSPACE_REQUESTED_KEY = "workspace_requested"


if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.llm.registry import ModelRegistry
    from Sprout.memory.outbox import OutboxWorker
    from Sprout.skills.registry import SkillRegistry
    from Sprout.storage.bundle import StorageBundle
    from Sprout.tools.registry import ToolRegistry
    from Sprout.tools.spec import ToolSpec


class Runtime:
    """Coordinates one online turn without knowing transports, vendors, or databases."""

    def __init__(
        self,
        *,
        storage: StorageBundle,
        models: ModelRegistry,
        tools: ToolRegistry,
        skills: SkillRegistry,
        events: EventBus | None = None,
        middleware: MiddlewareChain | None = None,
        policy_engine: PolicyEngine | LayeredPolicyEngine | None = None,
        trajectory_dir: Path = _DEFAULT_TRAJECTORY_DIR,
        default_agent: str = "assistant",
        security: SecurityLayer | None = None,
        skills_dir: str | None = None,
        orchestrator_backend: TemporalOrchestratorBackend | None = None,
        task_queue: TaskQueueBackend | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage
        self._settings = settings
        self.models = models
        self.tools = tools
        self.skills = skills
        self.events = register_builtin_events(events or EventBus())
        self.middleware = middleware or MiddlewareChain(
            middlewares=(LoggingMiddleware(),)
        )
        self.agents: Registry[Agent] = Registry()
        self._default_agent = default_agent
        self._session_store: SessionStore = storage.session_store()
        self._sessions = SessionManager(self._session_store)
        self._scanner = WorkspaceScanner()
        self._orchestrator_backend = orchestrator_backend
        self._workspaces = WorkspaceService(
            storage,
            self._scanner,
            skills_dir=skills_dir,
        )
        # Expose the read-only workspace query surface to agents. The import is
        # lazy because the tools package pulls the security/system tool surface.
        from Sprout.tools.workspace_query_tool import WorkspaceQueryTool

        self.tools.register(WorkspaceQueryTool(self._workspaces.analyze))
        self._contexts = ContextBuilder(
            storage,
            workspace_analysis_provider=self._workspaces.analyze,
            skill_disclosure=(
                settings.skills.disclosure if settings is not None else ""
            ),
        )
        self._sandbox_lifecycle = SandboxLifecycleService(storage.metadata)
        self._policy_engine = policy_engine or PolicyEngine()
        self.security = security
        self._approvals = (
            security.approvals
            if security is not None and security.approvals is not None
            else ApprovalManager(storage.operational, events=self.events)
        )
        self._read_broker = ReadBroker(
            self._policy_engine,
            redactor=Redactor(provider=self._secrets_provider()),
            classify_overrides=security.classify_overrides if security is not None else {},
        )
        self._process_broker = ProcessBroker(
            self._policy_engine,
            commands=security.commands if security is not None else None,
            secrets=security.secrets if security is not None else None,
            events=self.events,
            extra_env_names=security.extra_env_names if security is not None else (),
            # Without this the broker refused every REQUIRE_APPROVAL verdict
            # outright, so verification commands never ran and nobody was asked
            # to grant them.
            approvals=self._approvals,
        )
        self._file_broker = FileBroker(
            self._policy_engine,
            classify_overrides=security.classify_overrides if security is not None else {},
        )
        self._apply_broker = ApplyBroker(
            self._policy_engine,
            approvals=self._approvals,
        )
        self._network_broker = NetworkBroker(
            self._policy_engine,
            approvals=self._approvals,
            guard=security.guard if security is not None else None,
            secrets=security.secrets if security is not None else None,
        )
        self._database_broker = DatabaseBroker(self._policy_engine)
        self._git_broker = GitBroker(
            self._policy_engine,
            approvals=self._approvals,
        )
        from Sprout.tools.database_tool import DatabaseQueryTool
        from Sprout.tools.system_tools import (
            CliDownloadTool,
            CliRunTool,
            GitInspectTool,
            GitWriteTool,
        )

        self.tools.register(DatabaseQueryTool(self._database_broker))
        self.tools.register(
            CliRunTool(
                secrets=security.secrets if security is not None else None,
                process_broker=self._process_broker,
            )
        )
        self.tools.register(
            CliDownloadTool(
                guard=security.guard if security is not None else None,
                network_broker=self._network_broker,
            )
        )
        self.tools.register(GitInspectTool(git_broker=self._git_broker))
        self.tools.register(GitWriteTool(git_broker=self._git_broker))
        self.tools.register(
            SandboxReadTool(
                SandboxRef(
                    id="cwd",
                    kind="local_directory",
                    root=Path.cwd(),
                ),
                self._file_broker,
            )
        )
        self._skills_dir = Path(skills_dir) if skills_dir else None
        self._skill_resolver: SkillResolver | None = None
        self._register_skill_tools()
        self._trajectory_dir = trajectory_dir
        self._workspace_locks = WorkspaceLockManager()
        # Production assembly supplies the Temporal queue. Injection keeps
        # isolated unit tests from requiring a running Temporal server.
        self._task_queue = task_queue or create_task_queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._outbox_worker: OutboxWorker | None = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._graph_builder = ExecutionGraphBuilder()
        self._router: AgentRouter | None = None
        self._started = False
        #: Inbound message ids whose workspace consent has already been
        #: answered. Consent is one task, and one answer: without this a second
        #: "yes" would queue the same instruction again under a second task.
        self._consumed_consents: set[str] = set()

    def _register_skill_tools(self) -> None:
        """Expose skill_view / skill_search / skill_install to the agent.

        The L0 index injected into the prompt tells the model to call
        ``skill_view`` for a skill's body, so that tool has to exist or the index
        is a dead end. ``skill_view`` gets a *provider* rather than a snapshot so
        a skill installed during the session becomes viewable immediately.

        Search and install need a resolver, which needs the skill store and the
        skill index snapshot. Both are optional in a bare runtime, so the tools
        are registered whenever the directory is known and degrade to
        "not configured" when the store is absent.
        """
        from Sprout.skills.index import SkillIndex
        from Sprout.skills.layout import index_path
        from Sprout.skills.tools import SkillInstallTool, SkillSearchTool, SkillViewTool

        self.tools.register(SkillViewTool(self.skills.list))
        if self._skills_dir is None:
            return

        index = SkillIndex(index_path(self._skills_dir))
        resolver = SkillResolver(
            index=index,
            sources=self._skill_sources(),
            broker=self._skill_broker(),
            skills_dir=self._skills_dir,
            # Without this, a skill installed mid-session would not be loadable
            # until restart: the registry is a snapshot taken at assembly time.
            on_install=lambda: self.skills.reload(self._skills_dir, index=index),
        )
        self._skill_resolver = resolver
        self.tools.register(SkillSearchTool(resolver))
        self.tools.register(SkillInstallTool(resolver))

    def _skill_sources(self) -> list[Any]:
        """The sources a remote skill search may consult (design §7.3).

        Only ``catalog`` (the discovered-candidate cache) is wired: it reads
        ``.hub/remote.json`` and never touches the network on search, so an
        ordinary turn cannot be turned into a crawl. Refreshing that cache is an
        explicit ``sprout skills crawl``, or ``skill_search`` with ``refresh``.
        """
        if self._skills_dir is None:
            return []
        from Sprout.skills.sources.crawl import build_crawl_source

        settings = self._settings.skills if self._settings is not None else None
        sites = list(settings.catalog_sites) if settings is not None else []
        return [
            build_crawl_source(
                self._skills_dir,
                sites,
                max_results=settings.crawl_max_results if settings else 5,
                timeout=settings.crawl_timeout if settings else 15.0,
                seeds=(
                    tuple(settings.marketplace_seeds)
                    if settings and settings.marketplace_seeds
                    else None
                ),
                awesome=(
                    tuple(settings.marketplace_awesome)
                    if settings and settings.marketplace_awesome
                    else None
                ),
                topics=(
                    tuple(settings.marketplace_topics)
                    if settings and settings.marketplace_topics
                    else None
                ),
            )
        ]

    def _skill_broker(self) -> Any:
        """The install broker, so skill_install obeys the policy engine (§8.4)."""
        if self._skills_dir is None or self.storage.skills is None:
            return None
        from Sprout.skills.broker import SkillInstallBroker

        return SkillInstallBroker(
            self._policy_engine,
            approvals=self._approvals,
            skills=self.storage.skills,
        )

    def _secrets_provider(self) -> SecretProvider:
        if self.security is not None:
            return self.security.secrets.provider
        return EnvSecretProvider()

    @property
    def approvals(self) -> ApprovalManager:
        """The single approval manager for this runtime (AUTHZ §5.1)."""
        return self._approvals

    @property
    def audit(self) -> SecurityAuditLog | None:
        return self.security.audit if self.security is not None else None

    # -- collaborators -----------------------------------------------------
    def _metadata_or_raise(self) -> MetadataStore:
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        return metadata

    def _changes(self) -> ChangeProposalService:
        """The change proposal state machine; built per call, it holds no state."""
        return ChangeProposalService(
            self._metadata_or_raise(),
            self.storage.operational,
            self._apply_broker,
            events=self.events,
            approvals=self._approvals,
        )

    # Node budgets come from configuration, not from the compiler's defaults:
    # ``graph_builder.build`` falls back to ``verify_loops=1`` when the caller
    # does not pass these, which silently disables the configured retry loop.
    def _verify_loops(self) -> int:
        if self._settings is not None:
            return max(1, self._settings.runtime.verify_loops)
        return 2

    def _agent_max_attempts(self) -> int:
        if self._settings is not None:
            return max(1, self._settings.runtime.agent_max_attempts)
        return 2

    def _agent_timeout_seconds(self) -> float:
        if self._settings is not None:
            return max(1.0, self._settings.runtime.agent_timeout_seconds)
        return 300.0

    def _evaluation_timeout_seconds(self) -> float:
        if self._settings is not None:
            return max(1.0, self._settings.runtime.evaluation_timeout_seconds)
        return 600.0

    def _evaluation_attempts(self) -> int:
        if self._settings is not None:
            return max(1, self._settings.runtime.evaluation_attempts)
        return 2

    def _executor(self, metadata: MetadataStore) -> NodeExecutor:
        """The node runner for one task; owns brokers, prompts, and clamping."""
        return NodeExecutor(
            metadata=metadata,
            router=self._router,
            contexts=self._contexts,
            tools=self.tools,
            skills=self.skills,
            read_broker=self._read_broker,
            file_broker=self._file_broker,
            process_broker=self._process_broker,
            apply_broker=self._apply_broker,
            changes=self._changes(),
        )

    # -- assembly ---------------------------------------------------------
    def register_agent(
        self, name: str, agent: Agent, *, default: bool = False, replace: bool = True
    ) -> None:
        self.agents.register(name, agent, replace=replace)
        if default or self._router is None:
            self._default_agent = name if default else self._default_agent
            self._router = AgentRouter(self.agents, default=self._default_agent)

    def set_router(self, router: AgentRouter) -> None:
        """Advanced override for rule-based routing; replaces the default router."""
        self._router = router

    @property
    def default_agent(self) -> str:
        return self._default_agent

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._started:
            return
        if self._settings is not None:
            from Sprout.storage.bootstrap import ensure_storage_ready

            await ensure_storage_ready(self._settings)
        self._started = True
        await self.events.publish(Event(RUNTIME_STARTED, {"version": _package_version()}))
        await self._sandbox_lifecycle.reconcile_orphans()
        await self._sweep_stale_approvals()
        await self._start_outbox_worker()

    async def _sweep_stale_approvals(self) -> None:
        """Settle approvals that lapsed while nothing was running.

        ``sweep_expired`` existed but nothing called it: the only route was an
        operator typing ``sprout approvals sweep``. So an approval whose TTL ran
        out while the process was closed stayed ``PENDING`` forever, and every
        consumer of "what is waiting on a human" counted it — nine had piled up
        across two days, several already hours past expiry, one prompting every
        new session to answer a question whose task was long gone.

        Same shape as ``reconcile_orphans`` above, and for the same reason: work
        parked before a restart is not resumed by the restart, so it has to be
        settled at startup rather than waited on. A failure here is recorded and
        swallowed — expiry is housekeeping, and it must not block startup.
        """
        try:
            swept = await self._approvals.sweep_expired()
        except Exception as exc:  # noqa: BLE001 - housekeeping must not block start
            self._record_security(
                "approval.sweep_failed",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return
        if swept:
            self._record_security("approval.swept_at_startup", {"count": swept})

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        # Drain the outbox before the store closes: the worker's final flush
        # writes through the same database handle.
        await self._stop_outbox_worker()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        await self.events.publish(Event(RUNTIME_STOPPED, {}))
        await self.storage.close()

    async def _start_outbox_worker(self) -> None:
        """Drain the transactional outbox into the derived layers.

        ``SqliteSessionStore.append_turn`` writes the turn and its outbox rows
        in one transaction; this worker delivers them to the memory index and
        the observation store, idempotently on ``event_id``. Stores without an
        outbox table (in-memory backends) are skipped.
        """
        db = getattr(self._session_store, "database", None)
        if db is None:
            return
        from Sprout.memory.outbox import OutboxWorker

        worker = OutboxWorker(
            db=db,
            session_search=self.storage.session_search,
            observations=self.storage.observations,
        )
        await worker.start()
        self._outbox_worker = worker

    async def _stop_outbox_worker(self) -> None:
        worker = self._outbox_worker
        if worker is None:
            return
        self._outbox_worker = None
        await worker.stop()

    # -- online path ---------------------------------------------------------
    async def handle(self, message: Message) -> OutboundMessage:
        """Run one online turn. Middleware -> session -> router -> context -> agent."""
        if self._router is None:
            raise RuntimeError("No agent router configured")

        await self.events.publish(
            Event(
                MESSAGE_RECEIVED,
                {"message_id": message.id, "channel": message.channel},
                message.id,
            )
        )
        message = await self.middleware.before(message)
        session = await self._sessions.resolve(message)
        context = await self._contexts.build(
            message=message,
            session=session,
            tools=self.tools.list(),
            skills=self.skills.list(),
        )
        message, context = await self._recognize_intent(message, context)

        # A recognised task intent is queued for background execution and acked
        # immediately; it never runs inline. A task intent *without* a workspace
        # used to fall through to the conversation path silently — where the
        # agent has no write tools at all, since those live on AGENT nodes that
        # only exist once a task is compiled — so an explicit "write me a file"
        # was answered by an agent that could not do it, and nothing said why.
        # Now it asks which directory instead of degrading.
        handled = await self._dispatch_task_intent(message, context, session)
        if handled is not None:
            outbound, held = handled
            if held is not None:
                # The mark that lets a later consent find this instruction
                # lives on the stored turn, so the held case is the one that
                # has to be written here.
                await self._persist_turns(
                    session,
                    held,
                    AgentResult(
                        content=outbound.content, metadata=dict(outbound.metadata)
                    ),
                )
            return await self.middleware.after(held or message, outbound)

        agent = self._router.route(message)
        await self.events.publish(
            Event(AGENT_STARTED, {"session_id": session.id}, message.id)
        )
        try:
            result = await agent.run(message, context)
        except Exception as exc:
            await self.events.publish(
                Event(
                    AGENT_FAILED,
                    {"error_type": type(exc).__name__, "error": str(exc)},
                    message.id,
                )
            )
            raise

        # The agent may have discovered mid-turn that it needs a workspace
        # (``request_workspace``). That supersedes its own answer: it has no
        # write tools, so its prose could only be an explanation of the
        # obstacle. Hold the instruction and ask the operator instead.
        requested = await self._workspace_request_from_agent(result, message, session)
        if requested is not None:
            held, outbound = requested
            await self._persist_turns(
                session,
                held,
                AgentResult(
                    content=outbound.content, metadata=dict(outbound.metadata)
                ),
            )
            return await self.middleware.after(held, outbound)

        await self._persist_turns(session, message, result)
        await self.events.publish(
            Event(AGENT_COMPLETED, {"session_id": session.id}, message.id)
        )
        await self.events.publish(
            Event(MESSAGE_SENT, {"session_id": session.id}, message.id)
        )
        outbound = OutboundMessage(
            content=result.content,
            channel=message.channel,
            session_id=session.id,
            correlation_id=message.id,
            metadata=dict(result.metadata),
        )
        return await self.middleware.after(message, outbound)

    async def _handle_task(
        self, message: Message, session
    ) -> OutboundMessage:
        """Queue a coding task for background execution and ack immediately.

        Callers reach this when the message carries a workspace id. A task
        intent *without* one no longer falls through to the conversation path;
        it is held at :meth:`_request_workspace` until a human names the
        directory, then resumes here via :meth:`grant_workspace_consent`.
        """
        workspace_id = str(message.metadata.get("workspace_id") or "")
        # The surface the operator used, not the one the resume happens to run
        # on. A consented task resumes over an internal message, and taking the
        # source from there filed every such task as ``unknown``.
        source = str(
            message.metadata.get("origin_channel") or message.channel or ""
        )
        task = await self.create_task(
            workspace_id,
            message.content,
            actor=Principal(
                user_id=message.user_id or "anonymous", source=source
            ),
            source=source,
            # Recorded so a later turn can report this task back to the session
            # that asked for it. Without it a parked task belongs to no
            # conversation, and the person who asked is never told.
            metadata={
                **({"session_id": session.id} if session.id else {}),
                "response_language": str(
                    message.metadata.get("cli_language")
                    or message.metadata.get("response_language")
                    or detect_language(message.content)
                ),
            },
        )
        if message.metadata.get("foreground_task"):
            result = await self.execute(task)
            return OutboundMessage(
                content="",
                channel=message.channel,
                session_id=session.id,
                correlation_id=message.id,
                metadata={
                    "intent": "task",
                    "task_id": task.id,
                    "foreground_task": True,
                    "task_status": result.status.value,
                },
            )
        await self.submit_task(task)
        self.start_worker()
        return OutboundMessage(
            content=f"任务已提交（id={task.id}），正在后台执行。",
            channel=message.channel,
            session_id=session.id,
            correlation_id=message.id,
            metadata={"intent": "task", "task_id": task.id},
        )

    # -- telling the asker what happened -----------------------------------

    #: Task statuses that are waiting on a human. Each names *what* the human
    #: has to decide, because "waiting_approval" alone does not say whether the
    #: next move is `sprout approvals approve` or `sprout project approve` —
    #: and those take different ids.
    _PARKED_TASK_STATUSES = frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_RESOURCE,
            TaskStatus.READY_TO_APPLY,
        }
    )

    async def parked_tasks_for_session(self, session_id: str) -> list[Task]:
        """Tasks this session started that are waiting on a human decision.

        A background task runs detached from the turn that created it, so
        nothing on the chat path can observe it finishing or stalling. Without
        this lookup the operator is told "I will report back" and then hears
        nothing until they think to run ``sprout approvals list`` — which is
        exactly what happened: a task wrote its file and parked, and nobody was
        told for the rest of the session.
        """
        if not session_id or self.storage.metadata is None:
            return []
        parked: list[Task] = []
        for task in await self.list_tasks():
            if task.status not in self._PARKED_TASK_STATUSES:
                continue
            if str(task.metadata.get("session_id") or "") == session_id:
                parked.append(task)
        return parked

    async def task_progress(
        self, task: Task
    ) -> tuple[str, str]:
        """What a parked task is waiting for: ``(kind, id)``.

        ``kind`` is ``"approval"`` or ``"proposal"`` and ``id`` is what the
        matching command takes. Resolved by looking at what actually exists
        rather than inferring from the status, since a task can sit in
        ``WAITING_APPROVAL`` for either reason.
        """
        proposals = await self.list_change_proposals(task.id)
        pending = [
            proposal
            for proposal in proposals
            if proposal.status is ChangeProposalStatus.PENDING
        ]
        if pending:
            return "proposal", pending[0].id
        records = await self.pending_approvals()
        for record in records:
            if str(record.task_id or "") == task.id:
                return "approval", record.id
        return "", ""

    #: Intent classification values that name the coding path. Only ``task``
    #: reaches a compiled graph, hence a sandbox, hence the write tools.
    _WORKSPACE_ASKING_INTENTS = frozenset({"task"})

    def _asks_for_workspace(self, message: Message, context, session=None) -> bool:
        """Is this a coding intent that cannot proceed without a workspace?

        Two conditions, both required:

        1. The classifier called it ``task`` — a workspace-bearing message
           takes the existing path regardless, so this only guards the case
           where there is nothing to compile against.
        2. :func:`detect_task_hint` agrees on the text itself.

        The second is not redundancy. Interrupting a conversation to ask a
        question is the expensive move here, so it asks for *deterministic*
        evidence of a coding request rather than the model's opinion alone. An
        intent mis-classification — which the test doubles produce readily —
        would otherwise turn ordinary chat into a workspace prompt.

        This gate is best-effort by nature: it reads the wording, so a typo or
        an unfamiliar phrasing walks straight past it. That is affordable only
        because it is not the sole route — an agent that reaches the model and
        recognises a coding request calls ``request_workspace``, which
        :meth:`_workspace_request_from_agent` honours after the turn. This one
        exists to save a model round-trip and to interrupt *before* an agent
        starts work it cannot finish.

        A message that already carries the answer (the resume from
        :meth:`grant_workspace_consent`) is never asked again.
        """
        intent = str(context.metadata.get("intent") or "")
        if intent not in self._WORKSPACE_ASKING_INTENTS:
            return False
        if str(message.metadata.get("workspace_id") or ""):
            return False
        if message.metadata.get("workspace_consent"):
            return False
        if session is not None and self.session_workspace_id(session):
            return False
        return detect_task_hint(message.content)

    async def _dispatch_task_intent(
        self, message: Message, context, session
    ) -> tuple[OutboundMessage, Message | None] | None:
        """Handle a coding intent, or return ``None`` to run the turn normally.

        Returns the reply, plus a message to persist when the turn was *held*
        (``None`` otherwise). Holding marks the message and ``Message`` is
        frozen, so the marked copy travels back rather than being written in
        place — and only the held case persists, because that mark is the only
        way :meth:`grant_workspace_consent` can find the instruction later. The
        queued-task path persists nothing, as it always has.

        One place for both online paths to ask the same question, so ``handle``
        and ``handle_stream`` cannot drift apart. They had: ``handle_stream``
        had no task branch at all, so the CLI REPL — the path a user actually
        types into — never reached the coding graph even *with* a workspace,
        and certainly never asked for one.

        This covers the *before-the-agent* half only. The other half,
        :meth:`_workspace_request_from_agent`, runs after the agent and handles
        the case this gate cannot see.
        """
        if self._asks_for_workspace(message, context, session):
            held, outbound = await self._request_workspace(message, session)
            return outbound, held
        if str(context.metadata.get("intent") or "") != "task":
            return None
        explicit = str(message.metadata.get("workspace_id") or "")
        if explicit:
            # The message names its workspace: the resume from a consent grant,
            # or a caller that bound one deliberately. Already an instruction.
            return await self._handle_task(message, session), None
        # A workspace the operator consented to earlier in this session. Without
        # this the session only stopped *asking*; the coding intent still fell
        # through to the conversation path, where the agent has no write tools —
        # so "yes" would silence the question and still not run the task, which
        # is worse than asking.
        workspace_id = self.session_workspace_id(session)
        if not workspace_id:
            return None
        # Creating a task is at least as expensive as asking for a workspace, so
        # it demands no less evidence. The ask gate already requires the
        # classifier *and* :func:`detect_task_hint`, and a bound workspace must
        # not lower that bar: "好了吗" is a status question, the classifier
        # labelled it ``task`` ("are you done?"), and queueing a full
        # read→sandbox→plan→agent→evaluate run for it is exactly the mislabel
        # the keyword requirement exists to absorb. Such a turn stays a
        # conversation, where the agent can answer from what it already knows.
        if not detect_task_hint(message.content or ""):
            return None
        message = replace(
            message,
            metadata={**dict(message.metadata), "workspace_id": workspace_id},
        )
        return await self._handle_task(message, session), None

    async def _workspace_request_from_agent(
        self, result: AgentResult, message: Message, session
    ) -> tuple[Message, OutboundMessage] | None:
        """Hold the turn when the agent itself asked for a workspace.

        :meth:`_asks_for_workspace` decides from the *text*, before the agent
        runs; this decides from what the agent concluded *during* the turn, via
        the ``request_workspace`` tool. The two are complementary: the keyword
        gate is cheap and fires before any model call, while this one sees the
        whole turn and so survives a typo or an unusual phrasing that no
        substring would match. Both end in the same hold.

        Returns ``None`` when nothing was asked for, or when asking again could
        not help: a bound workspace means the request already has an answer, and
        re-asking would loop.
        """
        if not result.metadata.get(WORKSPACE_REQUESTED_KEY):
            return None
        if str(message.metadata.get("workspace_id") or ""):
            return None
        if message.metadata.get("workspace_consent"):
            return None
        if await self._session_has_active_task(session.id):
            return message, OutboundMessage(
                content=(
                    "当前会话已经有正在执行或等待审批的任务。"
                    "请用 /status <task_id> 查看它，或先处理已有任务，"
                    "不要再发起新的编码任务。"
                ),
                channel=message.channel,
                session_id=session.id,
                correlation_id=message.id,
                metadata={"intent": "conversation"},
            )
        # Already answered for this session: the request has a workspace, so
        # asking again is the loop this guard exists to prevent.
        if self.session_workspace_id(session):
            return None
        return await self._request_workspace(message, session)

    async def _session_has_active_task(self, session_id: str) -> bool:
        """Whether this session already owns a task that is not finished."""
        if not session_id or self.storage.metadata is None:
            return False
        terminal = {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.ROLLED_BACK,
        }
        for task in await self.list_tasks():
            if str(task.metadata.get("session_id") or "") == session_id:
                if task.status not in terminal:
                    return True
        return False

    async def _request_workspace(
        self, message: Message, session
    ) -> tuple[Message, OutboundMessage]:
        """Hold a coding task until a human names the directory to work in.

        The consent asked for is the smallest one that unblocks the request: a
        single directory, for a single task. The agent never writes to that
        directory directly — it writes to a git worktree sandbox and the result
        parks on a change proposal — so granting this does not hand over write
        access, it only lets a task be compiled.

        The hold is recorded by returning a *marked copy* of the message rather
        than writing a turn here: ``_persist_turns`` is the single authority
        write point of the online path, and a second writer produced two user
        turns for one instruction. The caller persists the marked copy through
        the normal path, and :meth:`grant_workspace_consent` reads the mark.

        Nothing else is written: no workspace is registered and no task is
        created until the operator answers.
        """
        root = Path.cwd()
        proposed = root.as_posix()
        held = replace(
            message,
            metadata={
                **dict(message.metadata),
                WORKSPACE_CONSENT_KEY: True,
                "proposed_workspace_root": proposed,
                # The channel the operator actually typed into. The resume runs
                # on an internal message, and if the channel is taken from
                # *that* the task's source degrades to ``unknown``: the approval
                # list then shows a source nobody can interpret, and the
                # audit trail loses which surface asked for the work.
                "origin_channel": message.channel,
            },
        )
        await self.events.publish(
            Event(
                INTENT_TASK_REQUESTED,
                {
                    "message_id": message.id,
                    "channel": message.channel,
                    WORKSPACE_CONSENT_KEY: True,
                    "proposed_workspace_root": proposed,
                },
                message.id,
            )
        )
        return held, OutboundMessage(
            content=(
                "这是一个编码任务，但当前会话没有绑定工作区，所以我暂时不能动手"
                "（这个会话里的 agent 没有写文件的工具）。\n\n"
                f"是否以 {proposed} 作为本次任务的工作区？\n"
                "同意后改动会先做在 git 沙箱副本里，落地到你的目录之前还会再问你一次。"
            ),
            channel=message.channel,
            session_id=session.id,
            correlation_id=message.id,
            metadata={
                "intent": "task",
                WORKSPACE_CONSENT_KEY: True,
                "proposed_workspace_root": proposed,
                "proposed_workspace_is_git": (root / ".git").exists(),
            },
        )

    #: Session metadata key holding the workspace a session has been granted.
    #: Kept on the session rather than passed per message because that is what
    #: the operator believes they answered: "yes, for this task" was remembered
    #: only on the one resumed message, so the next coding request in the same
    #: conversation asked again — four times in a row for one operator, each
    #: consent consumed as it was given.
    SESSION_WORKSPACE_KEY = "workspace_id"

    def session_workspace_id(self, session) -> str:
        """The workspace this session already has consent for, if any."""
        metadata = dict(getattr(session, "metadata", None) or {})
        return str(metadata.get(self.SESSION_WORKSPACE_KEY) or "")

    async def _remember_session_workspace(self, session_id: str, workspace_id: str) -> None:
        """Bind a granted workspace to its session so the question is asked once.

        Registration alone does not do this: a workspace can be opened without
        any session involved (``sprout project``, an API caller), and a session
        can outlive several workspaces. Writing it here ties it to the consent
        that produced it.
        """
        session = await self._session_store.get_session(session_id)
        if session is None:
            return
        metadata = dict(session.metadata or {})
        if str(metadata.get(self.SESSION_WORKSPACE_KEY) or "") == workspace_id:
            return
        metadata[self.SESSION_WORKSPACE_KEY] = workspace_id
        session.metadata = metadata
        await self._session_store.save_session(session)

    async def _held_workspace_consent(self, session_id: str):
        """The most recent unanswered consent request for a session, if any.

        The mark lives in the stored *envelope*, which nests the message's own
        metadata under ``message_metadata`` rather than flattening it, so the
        lookup goes one level down.
        """
        for turn in reversed(await self.history(session_id, limit=50)):
            if turn.role != "user":
                continue
            envelope = dict(turn.metadata or {})
            metadata = dict(envelope.get("message_metadata") or {})
            if not metadata.get(WORKSPACE_CONSENT_KEY):
                continue
            if str(envelope.get("message_id") or "") in self._consumed_consents:
                return None, None
            return turn, metadata
        return None, None

    async def grant_workspace_consent(
        self,
        session_id: str,
        *,
        root: str | Path | None = None,
        user_id: str = "anonymous",
    ) -> OutboundMessage:
        """Record consent for the instruction held by :meth:`_request_workspace`.

        The instruction is read back from the held turn rather than taken from
        the caller, so what runs is what the operator was shown — a caller
        cannot attach this consent to a different task.

        Single-task by construction: the held turn is consumed once, and the
        workspace id it produces rides only the resumed message. Answering
        again is an error, not a second task.
        """
        held, metadata = await self._held_workspace_consent(session_id)
        if held is None or metadata is None:
            raise LookupError(
                f"No pending workspace consent for session {session_id!r}"
            )
        proposed = str(metadata.get("proposed_workspace_root") or "")
        workspace = await self.open_workspace(
            root if root is not None else Path(proposed or Path.cwd())
        )
        # Marked consumed before the task is queued: a second answer must fail
        # even if queueing the first one is slow.
        self._consumed_consents.add(
            str(dict(held.metadata or {}).get("message_id") or "")
        )
        session = await self._session_store.get_session(session_id)
        if session is None:
            raise LookupError(f"Unknown session: {session_id!r}")
        # Remember before queueing: if the queue path raises, the operator has
        # still answered, and re-asking is the failure mode being fixed here.
        await self._remember_session_workspace(session_id, workspace.id)
        session = await self._session_store.get_session(session_id) or session
        return await self._handle_task(
            Message(
                content=held.content,
                channel="internal",
                user_id=user_id,
                session_id=session_id,
                metadata={
                    "workspace_id": workspace.id,
                    "workspace_consent": True,
                    **(
                        {"cli_language": str(metadata["cli_language"])}
                        if metadata.get("cli_language")
                        else {}
                    ),
                    **(
                        {"foreground_task": True}
                        if metadata.get("foreground_task")
                        else {}
                    ),
                    # Carried over from the held turn so the task is filed under
                    # the surface the operator used rather than "internal".
                    "origin_channel": str(metadata.get("origin_channel") or ""),
                },
            ),
            session,
        )

    async def _recognize_intent(self, message: Message, context):
        classification = await self._classify_intent_with_llm(message, context)
        intent = str(classification.get("intent") or "conversation")
        if intent not in _INTENT_EVENTS:
            intent = "conversation"
        trigger_event = str(
            classification.get("trigger_event") or _INTENT_EVENTS[intent]
        )
        if trigger_event not in _INTENT_EVENTS.values():
            trigger_event = _INTENT_EVENTS[intent]
        confidence = _clamp_float(classification.get("confidence"), default=0.5)
        payload = {
            "intent": intent,
            "trigger_event": trigger_event,
            "confidence": confidence,
            "message_id": message.id,
            "channel": message.channel,
            "user_id": message.user_id,
        }
        reason = classification.get("reason")
        if isinstance(reason, str) and reason:
            payload["reason"] = reason[:400]
        cli_command_family = classification.get("cli_command_family")
        if isinstance(cli_command_family, str) and cli_command_family:
            payload["cli_command_family"] = cli_command_family
        workspace_id = message.metadata.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            payload["workspace_id"] = workspace_id
        await self.events.publish(Event(INTENT_RECOGNIZED, payload, message.id))
        await self.events.publish(Event(trigger_event, payload, message.id))
        if intent == "conversation":
            return message, context
        metadata: dict[str, Any] = {
            **dict(message.metadata),
            "intent": intent,
            "intent_confidence": confidence,
            "intent_event": trigger_event,
        }
        if isinstance(cli_command_family, str) and cli_command_family:
            metadata["cli_command_family"] = cli_command_family
        project_analyze_call = _project_analyze_tool_call(message, intent)
        if project_analyze_call is not None:
            metadata["resume_tool_calls"] = [project_analyze_call]
        enriched = replace(message, metadata=metadata)
        context = replace(
            context,
            metadata={
                **dict(context.metadata),
                "intent": intent,
                "intent_confidence": confidence,
                "intent_event": trigger_event,
                **(
                    {"resume_tool_calls": [project_analyze_call]}
                    if project_analyze_call is not None
                    else {}
                ),
            },
        )
        return enriched, context

    async def _classify_intent_with_llm(self, message: Message, context) -> dict[str, Any]:
        explicit = message.metadata.get("intent") or message.metadata.get("intent_name")
        if isinstance(explicit, str) and explicit:
            intent = explicit.strip()
            return {
                "intent": intent,
                "trigger_event": message.metadata.get("intent_event")
                or _INTENT_EVENTS.get(intent, f"intent.{intent}.requested"),
                "confidence": message.metadata.get("intent_confidence", 1.0),
                "reason": "metadata override",
            }

        # Cheap task hint before spending an LLM call: an explicit coding task
        # ("修复…", "/task …") is already decidable from the text alone.
        if detect_task_hint(message.content or ""):
            return {
                "intent": Intent.TASK.value,
                "trigger_event": intent_event(Intent.TASK),
                "confidence": 0.8,
                "reason": "task_hint",
            }

        similar_context = await self._similar_context_for_intent(message)
        prompt = self._intent_prompt(message, context, similar_context=similar_context)
        try:
            response = await self.models.default().chat(
                [
                    LLMMessage.system(
                        "Classify the user's intent for SEAM Sprout event routing. "
                        "Return only compact JSON."
                    ),
                    LLMMessage.user(prompt),
                ],
                tools=(),
            )
        except Exception:
            return {"intent": "conversation", "confidence": 0.0, "reason": "llm_error"}
        return _parse_intent_json(response.text)

    async def _similar_context_for_intent(self, message: Message) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        query = message.content.strip()
        if not query:
            return hits
        context_store = self.storage.context
        if self.storage.vectors is not None:
            embed = getattr(self.storage.lanes, "embed", None)
            vector = embed(query) if callable(embed) else HashingEmbedder()(query)
            try:
                vector_hits = await self.storage.vectors.search(
                    vector,
                    limit=5,
                    namespace=CONTEXT_SNAPSHOTS_NS,
                )
            except Exception:
                vector_hits = ()
            for hit in vector_hits:
                record = None
                session_id = hit.metadata.get("session_id")
                snapshot_hash = hit.metadata.get("hash")
                if context_store is not None and isinstance(session_id, str):
                    try:
                        records = await context_store.list_records(session_id, limit=50)
                    except Exception:
                        records = []
                    record = next(
                        (
                            item
                            for item in records
                            if not isinstance(snapshot_hash, str)
                            or item.snapshot_hash == snapshot_hash
                        ),
                        None,
                    )
                text = record.text if record is not None else ""
                weighted = _weighted_context_summary(text, hit.score)
                hits.append(
                    {
                        "score": hit.score,
                        **weighted,
                        "key": hit.key,
                        "session_id": session_id or "",
                        "snapshot_hash": snapshot_hash or "",
                    }
                )
        if not hits and context_store is not None:
            try:
                records = await context_store.search(query, limit=5)
            except Exception:
                records = []
            hits.extend(
                {
                    "score": 0.0,
                    **_weighted_context_summary(record.text, 0.0),
                    "key": f"context:{record.session_id}:{record.snapshot_hash[:16]}",
                    "session_id": record.session_id,
                    "snapshot_hash": record.snapshot_hash,
                }
                for record in records
            )
        return hits

    def _intent_prompt(
        self,
        message: Message,
        context,
        *,
        similar_context: list[dict[str, Any]],
    ) -> str:
        memory_meta = (
            context.memory.metadata
            if hasattr(context.memory, "metadata")
            else {}
        )
        recent = []
        for item in list(context.memory)[-6:]:
            role = getattr(item, "role", "")
            content = str(getattr(item, "content", ""))[:500]
            if role and content:
                recent.append({"role": role, "content": content})
        context_payload = {
            "message": message.content,
            "channel": message.channel,
            "user_id": message.user_id,
            "message_metadata": dict(message.metadata),
            "context_metadata": dict(context.metadata),
            "memory": memory_meta,
            "recent_conversation": recent,
            "similar_context_from_vector_db": similar_context,
        }
        allowed = {
            "conversation": INTENT_CONVERSATION_REQUESTED,
            "task": INTENT_TASK_REQUESTED,
            "workspace": INTENT_WORKSPACE_REQUESTED,
            "tool": INTENT_TOOL_REQUESTED,
            "approval": INTENT_APPROVAL_REQUESTED,
            "memory": INTENT_MEMORY_REQUESTED,
            "evolution": INTENT_EVOLUTION_REQUESTED,
            "strategy": INTENT_STRATEGY_REQUESTED,
        }
        return (
            "Choose exactly one intent from this JSON object, where the value is "
            "the event to trigger:\n"
            f"{json.dumps(allowed, ensure_ascii=False)}\n\n"
            "Use the current message plus context/recent conversation. Return JSON "
            'like {"intent":"task","confidence":0.87,"reason":"..."}.\n\n'
            f"Input:\n{json.dumps(context_payload, ensure_ascii=False, default=str)}"
        )

    async def handle_stream(self, message: Message):
        """Run one online turn and stream the agent's text chunks."""
        if self._router is None:
            raise RuntimeError("No agent router configured")

        await self.events.publish(
            Event(
                MESSAGE_RECEIVED,
                {"message_id": message.id, "channel": message.channel},
                message.id,
            )
        )
        message = await self.middleware.before(message)
        session = await self._sessions.resolve(message)
        context = await self._contexts.build(
            message=message,
            session=session,
            tools=self.tools.list(),
            skills=self.skills.list(),
        )
        message, context = await self._recognize_intent(message, context)

        # Same dispatch as ``handle``. This path had no task branch at all, so
        # the CLI REPL never reached the coding graph even when a workspace was
        # present — the ask-for-workspace fix would have been unreachable from
        # the one surface a user types into.
        handled = await self._dispatch_task_intent(message, context, session)
        if handled is not None:
            outbound, held = handled
            yield StreamChunk(content=outbound.content)
            yield StreamChunk(outbound=outbound)
            if held is not None:
                # ``_finish_stream_turn`` persists through the normal path, so
                # it must receive the marked copy — this is the only writer for
                # a held turn, and writing it twice is what produced duplicate
                # user rows for one instruction.
                await self._finish_stream_turn(
                    session,
                    held,
                    AgentResult(
                        content=outbound.content, metadata=dict(outbound.metadata)
                    ),
                    outbound,
                )
            return

        agent = self._router.route(message)
        await self.events.publish(
            Event(AGENT_STARTED, {"session_id": session.id}, message.id)
        )

        chunks: list[str] = []
        stream = getattr(agent, "stream", None)
        result_metadata: dict[str, Any] = {}
        try:
            if stream is None:
                result = await agent.run(message, context)
                chunks.append(result.content)
                result_metadata = dict(result.metadata)
            else:
                async for chunk in stream(message, context):
                    if isinstance(chunk, AgentResult):
                        if chunk.content:
                            chunks.append(chunk.content)
                            yield StreamChunk(content=chunk.content)
                        result_metadata = dict(chunk.metadata)
                        continue
                    if chunk:
                        chunks.append(chunk)
                        yield StreamChunk(content=chunk)
        except Exception as exc:
            await self.events.publish(
                Event(
                    AGENT_FAILED,
                    {"error_type": type(exc).__name__, "error": str(exc)},
                    message.id,
                )
            )
            yield StreamChunk(error=f"{type(exc).__name__}: {exc}")
            raise

        # Same mid-turn workspace request as ``handle``. Any prose the model
        # streamed before calling the tool has already reached the caller, so
        # the hold adds the runtime's own question after it rather than
        # replacing it �� the agent cannot ask for a directory in a way the
        # runtime can act on, which is precisely why the tool exists.
        requested = await self._workspace_request_from_agent(
            AgentResult(content="".join(chunks), metadata=result_metadata),
            message,
            session,
        )
        if requested is not None:
            held, outbound = requested
            yield StreamChunk(content=outbound.content)
            yield StreamChunk(outbound=outbound)
            await self._finish_stream_turn(
                session,
                held,
                AgentResult(
                    content=outbound.content, metadata=dict(outbound.metadata)
                ),
                outbound,
            )
            return

        result = AgentResult(
            content="".join(chunks),
            metadata=result_metadata,
        )
        outbound = OutboundMessage(
            content=result.content,
            channel=message.channel,
            session_id=session.id,
            correlation_id=message.id,
            metadata=dict(result.metadata),
        )
        yield StreamChunk(outbound=outbound)
        self._schedule_background_task(
            self._finish_stream_turn(session, message, result, outbound)
        )

    def schedule_background(self, coroutine) -> None:
        """Run a coroutine off the turn path, drained by ``stop()``.

        Public so attached layers (growth, MCP) can do background work without
        reaching into Runtime internals; their tasks are awaited on shutdown
        like the runtime's own.
        """
        self._schedule_background_task(coroutine)

    def _schedule_background_task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _finish_stream_turn(
        self,
        session: Session,
        message: Message,
        result: AgentResult,
        outbound: OutboundMessage,
    ) -> None:
        """Finish a streamed turn after its response has reached the caller."""
        try:
            await self._persist_turns(session, message, result)
            await self.events.publish(
                Event(AGENT_COMPLETED, {"session_id": session.id}, message.id)
            )
            await self.events.publish(
                Event(MESSAGE_SENT, {"session_id": session.id}, message.id)
            )
            await self.middleware.after(message, outbound)
        except Exception as exc:
            await self.events.publish(
                Event(
                    AGENT_FAILED,
                    {"error_type": type(exc).__name__, "error": str(exc)},
                    message.id,
                )
            )

    async def resume_pending(
        self,
        session_id: str,
        *,
        user_id: str = "anonymous",
        content: str = "Continue",
    ) -> OutboundMessage:
        """Resume a turn that paused on an approval.

        Looks up the latest assistant turn that carried ``pending_tool_calls``
        and re-enters the online path with those calls attached.
        """
        pending = None
        for turn in reversed(await self.history(session_id, limit=50)):
            if turn.role != "assistant":
                continue
            metadata = _agent_metadata(turn.metadata or {})
            if metadata.get("approval_required") and metadata.get("pending_tool_calls"):
                pending = metadata["pending_tool_calls"]
                break
        if pending is None:
            raise LookupError(
                f"No pending approval found for session {session_id!r}"
            )
        message = Message(
            content=content,
            channel="internal",
            user_id=user_id,
            session_id=session_id,
            metadata={"resume_tool_calls": pending},
        )
        return await self.handle(message)

    async def resume_pending_task(
        self,
        session_id: str,
        *,
        user_id: str = "anonymous",
        response_language: str = "",
    ) -> OutboundMessage:
        """Resume approved pending tool calls without appending a new user turn."""
        if self._router is None:
            raise RuntimeError("No agent router configured")
        pending = None
        for turn in reversed(await self.history(session_id, limit=50)):
            if turn.role != "assistant":
                continue
            metadata = _agent_metadata(turn.metadata or {})
            if metadata.get("approval_required") and metadata.get("pending_tool_calls"):
                pending = metadata["pending_tool_calls"]
                break
        if pending is None:
            raise LookupError(
                f"No pending approval found for session {session_id!r}"
            )
        message = Message(
            content="",
            channel="internal",
            user_id=user_id,
            session_id=session_id,
            metadata={
                "resume_tool_calls": pending,
                **({"cli_language": response_language} if response_language else {}),
            },
        )
        message = await self.middleware.before(message)
        session = await self._sessions.resolve(message)
        context = await self._contexts.build(
            message=message,
            session=session,
            tools=self.tools.list(),
            skills=self.skills.list(),
        )
        agent = self._router.route(message)
        await self.events.publish(
            Event(AGENT_STARTED, {"session_id": session.id}, message.id)
        )
        try:
            result = await agent.run(message, context)
        except Exception as exc:
            await self.events.publish(
                Event(
                    AGENT_FAILED,
                    {"error_type": type(exc).__name__, "error": str(exc)},
                    message.id,
                )
            )
            raise
        await self._persist_assistant_turn(session, message, result)
        await self.events.publish(
            Event(AGENT_COMPLETED, {"session_id": session.id}, message.id)
        )
        await self.events.publish(
            Event(MESSAGE_SENT, {"session_id": session.id}, message.id)
        )
        outbound = OutboundMessage(
            content=result.content,
            channel="cli",
            session_id=session.id,
            correlation_id=message.id,
            metadata=dict(result.metadata),
        )
        return await self.middleware.after(message, outbound)

    # -- turn persistence (the single authority write point) -----------------

    async def _offload_body(
        self, content: str, envelope: dict
    ) -> tuple[str, dict]:
        """Move an oversized turn body to the blobstore (fail-open).

        Below the threshold, or when no blobstore is wired, the body stays
        inline and the envelope is returned unchanged. A blobstore failure
        degrades to inline storage: an oversized authority row beats a lost
        message (RUNTIME_DATA_PLAN §2.5, P4).
        """
        blobs = self.storage.blobs
        size = len(content.encode("utf-8"))
        if blobs is None or size <= TURN_BLOB_THRESHOLD_BYTES:
            return content, envelope
        try:
            uri = await blobs.put(content.encode("utf-8"), mime_type="text/plain")
        except Exception:  # noqa: BLE001 - blobstore is a lane, not authority
            return content, envelope
        offloaded = {**envelope, "blob_uri": uri, "content_bytes": size}
        return content[:TURN_PREVIEW_CHARS], offloaded

    async def _persist_turns(
        self, session: Session, message: Message, result: AgentResult
    ) -> None:
        """Append the user and assistant turns with their full envelopes.

        This is the only authority write point of the online path (P1): the
        envelopes make the stored rows lossless (P2), oversized bodies go to
        the blobstore (P4 fail-open), and the ``message.persisted`` event
        publishes the stored turn ids/seqs so derived lanes and observers can
        react without re-reading the session store.
        """
        user_body, user_envelope = await self._offload_body(
            message.content, turn_envelope(message)
        )
        assistant_body, assistant_envelope_dict = await self._offload_body(
            result.content, assistant_envelope(message, result.metadata)
        )
        user_turn = Turn(
            session.id, "user", user_body, metadata=user_envelope
        )
        assistant_turn = Turn(
            session.id, "assistant", assistant_body, metadata=assistant_envelope_dict
        )
        await self._session_store.append_turn(user_turn)
        await Runtime._persist_attachments(self, user_turn, message)
        await self._session_store.append_turn(assistant_turn)
        stored = list(
            await self._session_store.recent_turns(session.id, limit=2)
        )
        payload: dict = {"session_id": session.id}
        if len(stored) == 2:
            payload["turn_ids"] = [stored[0].id, stored[1].id]
            payload["seqs"] = [stored[0].seq, stored[1].seq]
        else:  # fallback when a backend cannot read back
            payload["turn_ids"] = [user_turn.id, assistant_turn.id]
            payload["seqs"] = [user_turn.seq, assistant_turn.seq]
        await self.events.publish(
            Event(MESSAGE_PERSISTED, payload, message.id)
        )

    @staticmethod
    async def _persist_attachments(runtime: Runtime, turn: Turn, message: Message) -> None:
        """Persist ``message.metadata["attachments"]`` against the user turn.

        This is the fail-open attachment lane: a malformed entry is skipped, and
        no failure here may break the online turn write. Each entry must be a
        mapping; anything else (strings, numbers) is ignored.
        """
        attachments = (message.metadata or {}).get("attachments")
        if not isinstance(attachments, list):
            return
        for entry in attachments:
            if not isinstance(entry, Mapping):
                continue
            try:
                attachment = Attachment(
                    id=str(entry.get("id") or uuid4()),
                    filename=str(entry.get("filename") or ""),
                    mime_type=str(entry.get("mime_type") or "application/octet-stream"),
                    size=int(entry.get("size") or 0),
                    uri=entry.get("uri") if isinstance(entry.get("uri"), str) else None,
                )
                await runtime._session_store.save_attachment(
                    attachment,
                    message_id=turn.id,
                    kind=str(entry.get("kind") or ""),
                    content_hash=str(entry.get("content_hash") or ""),
                    scan_status=str(entry.get("scan_status") or "unscanned"),
                    metadata=entry.get("metadata")
                    if isinstance(entry.get("metadata"), Mapping)
                    else None,
                )
            except Exception as exc:  # noqa: BLE001 - the attachment lane is fail-open
                # Still fail-open, but never silent: iterating over the rest is
                # what hid a missing store method behind a green test suite.
                logger.warning(
                    "attachment lane skipped an entry: %s: %s",
                    type(exc).__name__,
                    exc,
                )
                continue

    async def _persist_assistant_turn(
        self,
        session: Session,
        message: Message,
        result: AgentResult,
    ) -> None:
        """Append only the resumed assistant result for an approved parked turn."""
        assistant_body, assistant_envelope_dict = await self._offload_body(
            result.content, assistant_envelope(message, result.metadata)
        )
        assistant_turn = Turn(
            session.id, "assistant", assistant_body, metadata=assistant_envelope_dict
        )
        await self._session_store.append_turn(assistant_turn)
        stored = list(
            await self._session_store.recent_turns(session.id, limit=1)
        )
        payload: dict = {"session_id": session.id}
        if stored:
            payload["turn_ids"] = [stored[0].id]
            payload["seqs"] = [stored[0].seq]
        else:
            payload["turn_ids"] = [assistant_turn.id]
            payload["seqs"] = [assistant_turn.seq]
        await self.events.publish(
            Event(MESSAGE_PERSISTED, payload, message.id)
        )

    # -- public application services (used by CLI, MCP, Web API) -------------
    def describe(self) -> RuntimeInfo:
        return RuntimeInfo(
            name="SEAM_Sprout",
            version=_package_version(),
            default_agent=self._default_agent,
            agents=tuple(self.agents.list(enabled_only=False)),
            tools=tuple(self.tools.list()),
            skills=tuple(self.skills.list()),
            model_providers=tuple(self.models.list()),
            default_model=self.models.default_name,
            storage={
                "sessions": type(self._session_store).__name__,
                "operational": type(self.storage.operational).__name__,
                "knowledge": type(self.storage.knowledge).__name__,
                "metadata": (
                    type(self.storage.metadata).__name__
                    if self.storage.metadata is not None
                    else "disabled"
                ),
                "observations": (
                    type(self.storage.observations).__name__
                    if self.storage.observations is not None
                    else "disabled"
                ),
                "vectors": (
                    type(self.storage.vectors).__name__
                    if self.storage.vectors is not None
                    else "disabled"
                ),
                "cache": (
                    type(self.storage.cache).__name__
                    if self.storage.cache is not None
                    else "disabled"
                ),
                "blobs": (
                    type(self.storage.blobs).__name__
                    if self.storage.blobs is not None
                    else "disabled"
                ),
            },
        )

    async def create_session(self, user_id: str, *, session_id: str | None = None) -> Session:
        session = await self._sessions.create(user_id, session_id=session_id)
        await self.events.publish(
            Event(SESSION_CREATED, {"session_id": session.id}, session.id)
        )
        return session

    async def history(self, session_id: str, limit: int = 50) -> list[Turn]:
        return list(await self._session_store.recent_turns(session_id, limit=limit))

    async def get_session(self, session_id: str) -> Session | None:
        """Look up one session so a caller can be checked against its owner."""
        return await self._session_store.get_session(session_id)

    # -- SEMA project/task services -------------------------------------
    async def open_workspace(
        self,
        root: str | Path,
        *,
        workspace_id: str | None = None,
    ) -> Workspace:
        """Register a local or Git workspace in the metadata store."""
        return await self._workspaces.open(root, workspace_id=workspace_id)

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return await self._workspaces.get(workspace_id)

    async def list_workspaces(self) -> list[Workspace]:
        return await self._workspaces.list()

    async def scan_workspace(self, workspace_id: str) -> WorkspaceManifest:
        return await self._workspaces.scan(workspace_id)

    async def analyze_workspace(self, workspace_id: str) -> WorkspaceAnalysis:
        return await self._workspaces.analyze(workspace_id)

    async def invalidate_workspace(self, workspace_id: str | None = None) -> None:
        await self._workspaces.invalidate_workspace(workspace_id)

    async def plan_task(self, task_id: str) -> ReadPlan:
        return await self._workspaces.read_plan(task_id)

    async def create_task(
        self,
        workspace_id: str,
        instruction: str,
        *,
        actor: Principal | None = None,
        source: str = "cli",
        delegation_scope: DelegationScope | None = None,
        budget: TaskBudget | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Task:
        """Create and persist a task without starting orchestration yet."""
        store = self.storage.metadata
        if store is None:
            raise RuntimeError("MetadataStore is not configured")
        workspace = await store.get_workspace(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {workspace_id}")
        task = Task(
            workspace_id=workspace_id,
            instruction=instruction,
            actor=actor or Principal(user_id="cli-user"),
            source=source,
            delegation_scope=delegation_scope or DelegationScope(),
            budget=budget or TaskBudget(),
            metadata=metadata or {},
        )
        await store.save_task(task)
        return task

    async def create_task_from_strategy(
        self,
        workspace_id: str,
        requirement: str,
        *,
        actor: Principal | None = None,
        source: str = "cli",
        language: str = "",
        use_model_planner: bool = False,
    ) -> Task:
        """Plan a requirement with the strategy layer, then materialize a task.

        ``use_model_planner`` opts into the LLM-backed planner, which produces
        requirement-specific structured steps. It is off by default because it
        spends a model call: without a configured provider it would either fail
        or silently degrade, and callers that only want the cheap local plan
        should not pay for it.
        """
        workspace = await self.get_workspace(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {workspace_id}")

        from Sprout.strategy.execution import ExecutionPlanner
        from Sprout.strategy.pipeline import StrategyPipeline

        pipeline = StrategyPipeline()
        if use_model_planner:
            plan = await pipeline.plan_user_request_with_model(
                workspace.root,
                requirement,
                self.models.default(),
                language=language,
            )
        else:
            plan = pipeline.plan_user_request(
                workspace.root,
                requirement,
                language=language,
            )
        spec = ExecutionPlanner().plan_to_task_spec(plan)
        return await self.create_task(
            workspace_id,
            spec.instruction,
            actor=actor,
            source=source,
            budget=spec.budget,
            metadata={
                "required_paths": list(spec.resources),
                "tool_names": list(spec.tools),
                "plan_kind": "model" if use_model_planner else "local",
                **({"response_language": language} if language else {}),
                **spec.metadata,
            },
        )

    async def create_task_planned(
        self,
        workspace_id: str,
        instruction: str,
        *,
        actor: Principal | None = None,
        source: str = "cli",
        language: str = "",
        use_model_planner: bool = False,
    ) -> Task:
        """Create a task through strategy planning, falling back if it fails.

        This is the path real entry points use. Planning is best-effort by
        design: a workspace that is not a Git repo, a missing model, or a
        planner bug must degrade to a plain task rather than lose the user's
        request — the bridge adds decomposition, it is not a precondition for
        creating work.

        ``use_model_planner`` is off by default, on measured evidence rather
        than caution. An A/B on one real requirement found the model planner
        costs ~55s more per task and does not make the edit round faster or
        better:

            with decomposition:    plan 10.9s + 5xSUBTASK 47.6s + agent 19.6s = 78.5s
            without:               plan  6.4s +           -    + agent 16.4s = 23.0s

        The agent took essentially the same time either way, so the
        exploration was not buying anything the agent did not already do —
        both nodes read the same READ-node resources. Enabling this also
        emits SUBTASK nodes, making it the slower path even if those were
        later parallelised: the ceiling for any subtask optimisation is the
        no-decomposition baseline.

        Turn it on deliberately (it needs a real provider) when investigating
        whether decomposition helps a *complex*, multi-file requirement. The
        capability is kept, not deleted — it is just not the default.
        """
        try:
            return await self.create_task_from_strategy(
                workspace_id,
                instruction,
                actor=actor,
                source=source,
                language=language,
                use_model_planner=use_model_planner,
            )
        except Exception as exc:  # noqa: BLE001 - planning must never block the task
            logger.warning(
                "strategy planning failed (%s: %s); creating a plain task",
                type(exc).__name__,
                exc,
            )
            return await self.create_task(
                workspace_id,
                instruction,
                actor=actor,
                source=source,
                metadata={
                    "plan_kind": "fallback",
                    **({"response_language": language} if language else {}),
                },
            )

    async def get_task(self, task_id: str) -> Task | None:
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        return await metadata.get_task(task_id)

    async def list_tasks(self, workspace_id: str | None = None) -> list[Task]:
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        return await metadata.list_tasks(workspace_id)

    async def read_trajectory(self, task_id: str) -> list[TrajectoryEvent]:
        recorder = JsonlTrajectoryRecorder(
            trajectory_path(self._trajectory_dir, task_id)
        )
        return await recorder.read_all()

    async def run_task_process(
        self,
        task_id: str,
        command: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> ProcessResult:
        task = await self.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        workspace = await self.get_workspace(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")
        return await self._process_broker.run(
            workspace,
            command,
            cwd=workspace.root,
            task_id=task_id,
            timeout_seconds=timeout_seconds,
            scope=task.delegation_scope,
        )

    async def get_change_proposal(self, proposal_id: str) -> ChangeProposal | None:
        return await self._changes().get(proposal_id)

    async def list_change_proposals(self, task_id: str) -> list[ChangeProposal]:
        return await self._changes().list_for_task(task_id)

    async def find_change_proposal(self, prefix: str) -> ChangeProposal | None:
        return await self._changes().find(prefix)

    async def request_change_approval(self, proposal_id: str) -> ChangeProposal:
        return await self._changes().request_approval(proposal_id)

    async def approve_change_proposal(
        self,
        proposal_id: str,
        *,
        decided_by: str = "cli",
        allow_failing_tests: bool = False,
    ) -> ChangeProposal:
        proposal = await self._changes().approve(
            proposal_id,
            decided_by=decided_by,
            allow_failing_tests=allow_failing_tests,
        )
        await self._resume_task_after_approval(proposal.task_id)
        return proposal

    async def reject_change_proposal(
        self,
        proposal_id: str,
        *,
        reason: str = "",
    ) -> ChangeProposal:
        proposal = await self._changes().reject(proposal_id, reason=reason)
        await self._sandbox_lifecycle.cleanup_proposal(proposal)
        await self._cancel_task_after_rejection(proposal.task_id)
        return proposal

    async def _cancel_task_after_rejection(self, task_id: str) -> None:
        """Terminate a WAITING_APPROVAL task once its only proposal is rejected."""
        metadata = self.storage.metadata
        if metadata is None:
            return
        task = await metadata.get_task(task_id)
        if task is None or task.status is not TaskStatus.WAITING_APPROVAL:
            return
        TaskStateMachine.validate(task.status, TaskStatus.CANCELLED)
        await metadata.update_task_status(task_id, TaskStatus.CANCELLED)

    async def cancel_task(self, task_id: str, *, reason: str = "") -> Task:
        """Stop a task that is waiting on, or running for, a human.

        There was no way to do this from the CLI at all: approvals could be
        decided and proposals rejected, but a task parked on either gate had no
        exit, and the only cancellation in the codebase was the private
        ``_cancel_task_after_rejection`` above. Eight tasks had accumulated in
        ``waiting_approval`` with no supported way to retire them.

        Deliberately a status change, not a delete: the execution nodes,
        change proposals and audit records all cite this task id, and dropping
        the row would orphan them. ``CANCELLED`` says "decided against", which
        is the truth, where a missing row would say "never happened".

        The state machine is the contract, not a hand-kept list: whatever
        ``TaskStateMachine`` permits is allowed and whatever it forbids is
        refused with a ``ValueError``. That leaves ``FAILED`` cancellable —
        it is settled, not terminal, since the machine gives it an exit
        (``RETRYING``) — and refuses ``COMPLETED``, ``CANCELLED`` and
        ``ROLLED_BACK``, which have no way out. Overwriting one of those with
        ``CANCELLED`` would rewrite what actually happened.
        """
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        task = await metadata.get_task(task_id)
        if task is None:
            raise LookupError(f"Task not found: {task_id}")
        if not TaskStateMachine.can_transition(task.status, TaskStatus.CANCELLED):
            raise ValueError(
                f"Task {task_id} is {task.status.value}; it cannot be cancelled"
            )
        await metadata.update_task_status(task_id, TaskStatus.CANCELLED)
        self._record_security(
            "task.cancelled",
            {"task_id": task_id, "from": task.status.value, "reason": reason},
        )
        cancelled = await metadata.get_task(task_id)
        return cancelled if cancelled is not None else task

    async def resolve_orphaned_approvals(self, task_id: str) -> int:
        """Clear a cancelled task's still-PENDING approvals; returns how many.

        Cancelling the task is not enough on its own: the approval record stays
        ``pending``, so anything listing open questions keeps offering one about
        a task that can no longer act on the answer — the operator is asked to
        decide something with no effect. Called alongside :meth:`cancel_task` so
        the two cannot drift.

        A rejection rather than a silent delete: ``decide`` writes the audit
        record and settles the state machine, and the record stays readable as
        the explanation for why the task stopped.
        """
        cleared = 0
        for record in await self.pending_approvals():
            if getattr(record, "task_id", "") != task_id:
                continue
            await self._approvals.decide(
                record.id,
                False,
                decided_by="system",
                reason="Task was cancelled",
                channel="cli",
            )
            cleared += 1
        return cleared

    async def apply_change_proposal(
        self,
        proposal_id: str,
        *,
        allow_failing_tests: bool = False,
    ) -> ApplyResult:
        result = await self._changes().apply(
            proposal_id, allow_failing_tests=allow_failing_tests
        )
        if result.applied:
            proposal = await self._changes().get(proposal_id)
            if proposal is not None:
                await self._sandbox_lifecycle.cleanup_proposal(proposal)
        return result

    async def rollback_change_proposal(
        self,
        proposal_id: str,
        *,
        decided_by: str = "cli",
    ) -> ApplyResult:
        # ``decided_by`` is kept for parity with approve; rollback reuses the
        # grant that was created when the proposal was approved.
        result = await self._changes().rollback(proposal_id)
        if result.applied:
            proposal = await self._changes().get(proposal_id)
            if proposal is not None:
                await self._sandbox_lifecycle.cleanup_proposal(proposal)
        return result

    async def execute(
        self,
        task: Task,
        *,
        artifact_snapshot: ArtifactSnapshot | None = None,
    ) -> TaskResult:
        async with self._workspace_locks.lock(task.workspace_id):
            return await self._execute_task(
                task,
                artifact_snapshot=artifact_snapshot,
            )

    async def submit_task(self, task: Task) -> None:
        """Queue a task for later execution by a worker."""
        await self._task_queue.put(task)

    async def run_task_worker(self) -> None:
        """Consume queued tasks and execute them serially per workspace."""
        while True:
            task = await self._task_queue.get()
            try:
                await self.execute(task)
            finally:
                self._task_queue.task_done()

    def start_worker(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self.run_task_worker(),
                name="sema-task-worker",
            )

    async def stop_worker(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def _execute_task(
        self,
        task: Task,
        *,
        artifact_snapshot: ArtifactSnapshot | None,
    ) -> TaskResult:
        """Run a task through the V0.1 project execution pipeline."""
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        workspace = await metadata.get_workspace(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")

        manifest = self._scanner.scan(workspace)
        workspace = Workspace(
            id=workspace.id,
            root=workspace.root,
            kind=workspace.kind,
            revision=workspace.revision,
            manifest=manifest,
        )
        await metadata.save_workspace(workspace)
        await metadata.save_task(task)

        required_paths = tuple(task.metadata.get("required_paths") or ())
        tool_names = tuple(task.metadata.get("tool_names") or ())
        steps = tuple(task.metadata.get("steps") or ())
        verification_commands = tuple(
            task.metadata.get("verification_commands") or ()
        )
        read_plan = self._scanner.build_read_plan(
            workspace, task, required_paths=required_paths
        )
        graph = self._graph_builder.build(
            task,
            read_plan,
            manifest,
            agent_tool_names=tool_names,
            verify_loops=self._verify_loops(),
            agent_max_attempts=self._agent_max_attempts(),
            agent_timeout_seconds=self._agent_timeout_seconds(),
            evaluation_timeout_seconds=self._evaluation_timeout_seconds(),
            evaluation_attempts=self._evaluation_attempts(),
            steps=steps,
            verification_commands=verification_commands,
        )
        graph = await self._restore_graph(graph)
        recorder = JsonlTrajectoryRecorder(trajectory_path(self._trajectory_dir, task.id))
        executor = self._executor(metadata)
        pinned_skill = await executor.pin_snapshot(recorder, artifact_snapshot, task.id)
        try:
            result = await self._orchestrator_for(metadata).execute(
                graph,
                handler=executor.handler(task, workspace, read_plan),
                recorder=recorder,
                budget=task.budget,
            )
            await self._sandbox_lifecycle.finalize(task, result)
            return result
        finally:
            if pinned_skill is not None:
                self.skills.unregister(pinned_skill.name)

    async def resume_task(self, task: Task) -> TaskResult:
        """Continue a task parked in WAITING_APPROVAL after a human decision.

        Already completed nodes are skipped, so approval decisions never
        replay side effects (SEMA spec 19.2).
        """
        metadata = self.storage.metadata
        if metadata is None:
            raise RuntimeError("MetadataStore is not configured")
        workspace = await metadata.get_workspace(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")
        manifest = workspace.manifest or self._scanner.scan(workspace)
        required_paths = tuple(task.metadata.get("required_paths") or ())
        tool_names = tuple(task.metadata.get("tool_names") or ())
        steps = tuple(task.metadata.get("steps") or ())
        verification_commands = tuple(
            task.metadata.get("verification_commands") or ()
        )
        read_plan = self._scanner.build_read_plan(
            workspace, task, required_paths=required_paths
        )
        graph = self._graph_builder.build(
            task,
            read_plan,
            manifest,
            agent_tool_names=tool_names,
            verify_loops=self._verify_loops(),
            agent_max_attempts=self._agent_max_attempts(),
            agent_timeout_seconds=self._agent_timeout_seconds(),
            evaluation_timeout_seconds=self._evaluation_timeout_seconds(),
            evaluation_attempts=self._evaluation_attempts(),
            steps=steps,
            verification_commands=verification_commands,
        )
        graph = await self._restore_graph(graph)
        recorder = JsonlTrajectoryRecorder(trajectory_path(self._trajectory_dir, task.id))
        executor = self._executor(metadata)
        result = await self._orchestrator_for(metadata).execute(
            graph,
            handler=executor.handler(task, workspace, read_plan),
            recorder=recorder,
            budget=task.budget,
        )
        await self._sandbox_lifecycle.finalize(task, result)
        return result

    async def _restore_graph(self, graph: ExecutionGraph) -> ExecutionGraph:
        """Overlay persisted node state onto a freshly compiled graph.

        The Temporal backend does not run ``SequentialOrchestrator._restore``,
        so a resumed workflow needs the already-completed statuses here.
        """
        metadata = self._metadata_or_raise()
        stored = {
            node.id: node
            for node in await metadata.list_execution_nodes(graph.task_id)
        }
        if not stored:
            return graph
        restored: list[ExecutionNode] = []
        for node in graph.nodes:
            previous = stored.get(node.id)
            if previous is None:
                restored.append(node)
                continue
            restored.append(
                replace(
                    node,
                    status=previous.status,
                    attempts=previous.attempts,
                    metadata=dict(previous.metadata),
                )
            )
        return replace(graph, nodes=tuple(restored))

    async def execute_node(self, node: ExecutionNode) -> dict[str, Any]:
        """Run one orchestration node on behalf of an external scheduler.

        Temporal activities run in a separate process from the submission path,
        so they need a narrow public entry point that prepares the workspace,
        read plan, executor, and trajectory recorder without reaching into
        Runtime private fields.
        """
        metadata = self._metadata_or_raise()
        task = await metadata.get_task(node.task_id)
        if task is None:
            raise LookupError(f"Task not found: {node.task_id}")
        workspace = await metadata.get_workspace(task.workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace not found: {task.workspace_id}")
        manifest = workspace.manifest or self._scanner.scan(workspace)
        workspace = Workspace(
            id=workspace.id,
            root=workspace.root,
            kind=workspace.kind,
            revision=workspace.revision,
            manifest=manifest,
        )
        read_plan = self._scanner.build_read_plan(workspace, task)
        executor = self._executor(metadata)
        recorder = JsonlTrajectoryRecorder(
            trajectory_path(self._trajectory_dir, task.id)
        )
        NodeStateMachine.validate(node.status, NodeStatus.RUNNING)
        running = replace(node, status=NodeStatus.RUNNING, attempts=node.attempts + 1)
        await metadata.save_execution_node(running)
        await recorder.record(
            TrajectoryEvent(
                name="node.started",
                task_id=task.id,
                payload={"node_id": node.id},
            )
        )
        try:
            output = await executor.execute_node(node, workspace, read_plan, task)
        except Exception as exc:
            failed = replace(
                node,
                status=NodeStatus.FAILED,
                metadata={
                    **node.metadata,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            await metadata.save_execution_node(failed)
            await recorder.record(
                TrajectoryEvent(
                    name="node.failed",
                    task_id=task.id,
                    payload={"node_id": node.id},
                )
            )
            raise
        if isinstance(output, dict) and output.get("waiting"):
            waiting = replace(
                node,
                status=NodeStatus.WAITING,
                metadata={**node.metadata, "output": output},
            )
            await metadata.save_execution_node(waiting)
            await recorder.record(
                TrajectoryEvent(
                    name="node.waiting",
                    task_id=task.id,
                    payload={"node_id": node.id},
                )
            )
            return {
                "node_id": node.id,
                "type": node.type.value,
                "status": NodeStatus.WAITING.value,
                "output": output,
            }
        completed = replace(
            node,
            status=NodeStatus.COMPLETED,
            metadata={**node.metadata, "output": output},
        )
        await metadata.save_execution_node(completed)
        await recorder.record(
            TrajectoryEvent(
                name="node.completed",
                task_id=task.id,
                payload={"node_id": node.id},
            )
        )
        return {
            "node_id": node.id,
            "type": node.type.value,
            "status": NodeStatus.COMPLETED.value,
            "output": output,
        }

    def list_skills(self) -> dict[str, Skill]:
        return self.skills.list()

    def _orchestrator_for(self, metadata):
        if self._orchestrator_backend is not None:
            return self._orchestrator_backend
        return TemporalOrchestratorBackend(metadata=metadata)

    def list_tool_specs(self) -> list[ToolSpec]:
        return self.tools.specs()

    async def search_knowledge(self, query: str, limit: int = 5) -> list[KnowledgeItem]:
        return list(await self.storage.knowledge.search(query, limit=limit))

    async def list_approvals(
        self, status: ApprovalStatus | None = None
    ) -> list[ApprovalRecord]:
        return list(await self.storage.operational.list_approvals(status))

    async def pending_approvals(self) -> list[ApprovalRecord]:
        return await self._approvals.pending()

    async def decide_approval(
        self,
        approval_id: str,
        approved: bool,
        *,
        decided_by: str = "cli",
        reason: str | None = None,
        channel: str = "cli",
        resume_session: bool = True,
    ) -> ApprovalRecord:
        """Record a human decision and unblock the task that was waiting (AUTHZ §5.2)."""
        record = await self._approvals.decide(
            approval_id,
            approved,
            decided_by=decided_by,
            reason=reason,
            channel=channel,
        )
        await self._resume_after_decision(record, resume_session=resume_session)
        return record

    async def sweep_approvals(self) -> int:
        """Expire stale pending approvals; returns how many were swept."""
        return await self._approvals.sweep_expired()

    async def approval_backlog_age(self) -> float | None:
        """Age in seconds of the oldest pending approval (monitoring metric)."""
        return await self._approvals.oldest_pending_age()

    async def _resume_after_decision(
        self, record: ApprovalRecord, *, resume_session: bool = True
    ) -> None:
        """Resume a task parked in WAITING_APPROVAL once its grant is approved.

        Rejections leave the task parked: the caller decides whether to retry.
        A resume failure never rolls back the decision, so it is recorded in the
        audit stream instead of raising out of the decide path.
        """
        if record.status is not ApprovalStatus.APPROVED:
            return
        if record.task_id:
            await self._resume_task_after_approval(
                record.task_id,
                approval_id=record.id,
            )
        if resume_session and record.session_id:
            await self._resume_session_after_approval(record)

    async def _resume_session_after_approval(self, record: ApprovalRecord) -> None:
        """Continue a chat turn that parked on this approval's pending tool calls."""
        try:
            await self.resume_pending_task(
                record.session_id,
                user_id=record.requested_by or "approval",
            )
        except LookupError as exc:
            # Another channel may have already resumed the same parked turn.
            if "No pending approval found" in str(exc):
                return
            self._record_security(
                "approval.resume_failed",
                {
                    "approval_id": record.id,
                    "session_id": record.session_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception as exc:  # noqa: BLE001 - the decision stays valid
            self._record_security(
                "approval.resume_failed",
                {
                    "approval_id": record.id,
                    "session_id": record.session_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

    async def _resume_task_after_approval(
        self,
        task_id: str,
        *,
        approval_id: str = "",
    ) -> None:
        """Resume a WAITING_APPROVAL task after its change proposal is approved.

        ``approval_id`` is optional and only enriches the audit record when the
        resume path came from a security approval decision rather than the
        change-proposal service.
        """
        metadata = self.storage.metadata
        if metadata is None:
            return
        try:
            task = await metadata.get_task(task_id)
            if task is None or task.status is not TaskStatus.WAITING_APPROVAL:
                return
            await self.resume_task(task)
        except Exception as exc:  # noqa: BLE001 - the decision stays valid
            self._record_security(
                "approval.resume_failed",
                {
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

    def _record_security(self, kind: str, payload: dict) -> None:
        if self.security is not None:
            self.security.audit.record(kind, payload)

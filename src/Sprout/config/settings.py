"""Typed settings for every layer of the runtime.

Defaults intentionally carry no usable model: ``provider="aiyallm"`` with an
empty ``model``, so a misconfigured runtime fails loudly rather than silently
falling back to echo. Point ``[model]`` at a real provider in a ``sprout.toml``
(see ``Sprout.config.defaults.EXAMPLE_TOML``) plus an API key in the
environment, or select ``echo`` explicitly for fully offline operation.
Supported real providers are ``aiyallm`` and ``openai_compatible``. Storage
defaults to SQLite databases under ``~/.sprout/data/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_SPROUT_DATA = Path.home() / ".sprout" / "data"


def _sqlite_dsn(filename: str) -> str:
    return f"sqlite:///{(_SPROUT_DATA / filename).as_posix()}"


@dataclass(slots=True)
class RuntimeSettings:
    default_agent: str = "assistant"
    max_tool_steps: int = 8
    session_turn_limit: int = 20
    verify_loops: int = 2
    agent_max_attempts: int = 2
    agent_timeout_seconds: float = 300.0
    evaluation_timeout_seconds: float = 600.0
    evaluation_attempts: int = 2


@dataclass(slots=True)
class ModelSettings:
    provider: str = "aiyallm"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    providers: tuple[dict[str, object], ...] = ()
    fallback_provider: str = ""
    fallback_model: str = ""
    fallback_base_url: str = ""
    fallback_api_key_env: str = ""
    timeout_seconds: float = 60.0
    temperature: float | None = None


@dataclass(slots=True)
class ObservationSettings:
    enabled: bool = True
    dsn: str = _sqlite_dsn("sprout_audit.db")


@dataclass(slots=True)
class StorageSettings:
    # Sprout runtime authorities. The legacy field names remain the storage
    # bundle's implementation names; the public topology is the new
    # ``sprout_*`` layout described in guidance.md section 19.
    operational: str = _sqlite_dsn("sprout_audit.db")
    knowledge: str = _sqlite_dsn("sprout_knowledge.db")
    metadata: str = _sqlite_dsn("sprout_core.db")
    observations: ObservationSettings = field(default_factory=ObservationSettings)
    session: str = _sqlite_dsn("sprout_conversation.db")
    cache: str = "memory"
    blobs_dir: str = (_SPROUT_DATA / "sprout_blobs").as_posix()
    trajectory_dir: str = (_SPROUT_DATA / "sprout_trajectory").as_posix()
    vectors: str = "memory"
    #: Derived lanes: a real Neo4j graph store and a durable context log.
    #: ``graph = "neo4j://host:7687"`` activates the graph lane. Context is
    #: persisted by default to its own SQLite authority
    #: (``sprout_context.db``); override with
    #: ``"jsonl://<home>/.sprout/data/context"`` or opt out with ``"none"``.
    graph: str = "none"
    context: str = _sqlite_dsn("sprout_context.db")
    usage: str = _sqlite_dsn("sprout_usage.db")
    project_root: str = (_SPROUT_DATA / "projects").as_posix()

    @property
    def core(self) -> str:
        """Public name for the Sprout runtime coordination authority."""
        return self.metadata

    @core.setter
    def core(self, value: str) -> None:
        self.metadata = value

    @property
    def conversation(self) -> str:
        """Public name for the Sprout user-to-Sprout conversation authority."""
        return self.session

    @conversation.setter
    def conversation(self, value: str) -> None:
        self.session = value

    @property
    def audit(self) -> str:
        """Public name for the Sprout approvals/audit authority."""
        return self.operational

    @audit.setter
    def audit(self, value: str) -> None:
        self.operational = value


@dataclass(slots=True)
class FloorSettings:
    """The hard floor is always on; the key exists so ``sprout info`` can show it."""

    enabled: bool = True


@dataclass(slots=True)
class PolicyRulesSettings:
    """``[security.rules]``: organization / workspace / delegation rule sets."""

    #: ``process.run`` command globs (Hermes ``approvals.deny`` style).
    deny: tuple[str, ...] = ()
    #: Command globs the operator pre-approves (never widens a deny).
    allow: tuple[str, ...] = ()
    #: ``{"file.read:src/**" = "allow"}`` — workspace layer.
    workspace: dict[str, str] = field(default_factory=dict)
    #: Same shape, applied last as the delegation layer.
    delegation: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ClassifySettings:
    """``[security.classify]`` overrides: glob -> ResourceKind name."""

    rules: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class CommandSettings:
    """``[security.commands]``: the server-side ``known_command`` allowlist."""

    allowlist: tuple[str, ...] = ()
    denylist: tuple[str, ...] = ()
    #: Names that may run with no approval at all. Empty by default: see
    #: ``security/commands.py`` for why an allowlist of build tools is not a safe
    #: auto-run list (every one of them executes code the task can write).
    auto_run: tuple[str, ...] = ()
    #: Extra environment variable names to forward to child processes.
    inherit_env: tuple[str, ...] = ()


@dataclass(slots=True)
class NetworkSettings:
    """``[security.network]``: SSRF exemptions and an outbound blocklist."""

    allow_private: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()


@dataclass(slots=True)
class AuditSettings:
    """``[security.audit]``: the tamper-evident authorization stream."""

    enabled: bool = True
    path: str = (_SPROUT_DATA / "audit" / "security.jsonl").as_posix()
    record_allows: bool = True


@dataclass(slots=True)
class ApprovalSettings:
    """``[security.approvals]``: how approvals behave per task source."""

    #: ``deny`` (default, Hermes ``cron_mode``) | ``sandbox_only`` | ``ask``.
    unattended: str = "deny"
    timeout_seconds: float = 3600.0
    sweep_interval_seconds: float = 300.0


@dataclass(slots=True)
class SecuritySettings:
    allow_medium_risk: bool = True
    require_approval: bool = True
    organization_deny_prefixes: tuple[str, ...] = ()
    workspace_deny_prefixes: tuple[str, ...] = ()
    rpc_auth_enabled: bool = False
    rpc_api_token_env: str = "SEMA_RPC_TOKEN"
    #: Web API authentication (AUTHZ §2.1: "an API token is enough to start").
    #: Off only makes sense while the server binds loopback — ``sprout serve``
    #: logs a warning when it is off and the bind address is not local.
    web_auth_enabled: bool = False
    web_api_token_env: str = "SPROUT_WEB_TOKEN"
    floor: FloorSettings = field(default_factory=FloorSettings)
    rules: PolicyRulesSettings = field(default_factory=PolicyRulesSettings)
    classify: ClassifySettings = field(default_factory=ClassifySettings)
    commands: CommandSettings = field(default_factory=CommandSettings)
    network: NetworkSettings = field(default_factory=NetworkSettings)
    audit: AuditSettings = field(default_factory=AuditSettings)
    approvals: ApprovalSettings = field(default_factory=ApprovalSettings)


@dataclass(slots=True)
class MCPServerSettings:
    enabled: bool = True
    transport: str = "stdio"


@dataclass(slots=True)
class MCPPrincipalSettings:
    """The identity an MCP client's calls run as (AUTHZ §2.1).

    Deployment configuration is the trust basis for MCP callers: the client
    never declares its own roles over the wire.
    """

    user_id: str = ""
    display_name: str = ""
    roles: tuple[str, ...] = ()


@dataclass(slots=True)
class MCPClientSettings:
    """One external MCP server spawned over stdio."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    principal: MCPPrincipalSettings = field(default_factory=MCPPrincipalSettings)


@dataclass(slots=True)
class MCPSettings:
    server: MCPServerSettings = field(default_factory=MCPServerSettings)
    clients: tuple[MCPClientSettings, ...] = ()


@dataclass(slots=True)
class EvolutionSettings:
    enabled: bool = True
    approval_required: bool = True
    level: int = 1


@dataclass(slots=True)
class SkillsSettings:
    """Skill discovery and disclosure (docs/SKILLS_SYSTEM_DESIGN.md §17).

    ``skills_dir`` itself stays a top-level setting for backwards compatibility;
    this table holds the behaviour that was added on top of it.
    """

    #: ``progressive`` injects only the L0 index; ``eager`` keeps the legacy
    #: behaviour of putting every enabled skill's full body in the prompt.
    disclosure: str = "progressive"
    search_enabled: bool = True
    #: Sites the crawler is allowed to walk. Empty means "never crawl", which is
    #: the default: discovery of remote skills is opt-in, because it hits
    #: third-party hosts. Only these operator-listed sites are ever visited.
    catalog_sites: list[str] = field(default_factory=list)
    crawl_max_results: int = 5
    crawl_timeout: float = 15.0
    #: Repositories whose ``.claude-plugin/marketplace.json`` is read during
    #: ecosystem discovery. Empty falls back to the built-in seed list, which
    #: starts with Anthropic's curated directory. Set it to curate your own.
    marketplace_seeds: list[str] = field(default_factory=list)
    #: Curated "awesome" list READMEs to mine for repository links.
    marketplace_awesome: list[str] = field(default_factory=list)
    #: GitHub topic names whose pages are scraped for repositories.
    marketplace_topics: list[str] = field(default_factory=list)
    #: Repositories scanned per discovery pass, and skills kept per repository.
    #: Both bound a refresh: the ecosystem publishes tens of thousands of skills.
    discover_max_repos: int = 200
    discover_max_skills_per_repo: int = 400
    #: Search remote sources when nothing matches locally (§7.6).
    search_extra_on_miss: bool = True
    #: Sources consulted, in order, for a remote search.
    sources: list[str] = field(
        default_factory=lambda: ["catalog", "well-known"]
    )


@dataclass(slots=True)
class WebSettings:
    host: str = "127.0.0.1"
    port: int = 8000


@dataclass(slots=True)
class FeishuSettings:
    enabled: bool = False
    verification_token_env: str = "FEISHU_VERIFICATION_TOKEN"
    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"
    encrypt_key_env: str = "FEISHU_ENCRYPT_KEY"
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    default_workspace_id: str = ""
    domain: str = "feishu"


@dataclass(slots=True)
class WeChatDialogSettings:
    enabled: bool = False
    token_env: str = "WECHAT_DIALOG_TOKEN"
    encoding_aes_key_env: str = "WECHAT_DIALOG_ENCODING_AES_KEY"
    appid_env: str = "WECHAT_DIALOG_APPID"
    default_workspace_id: str = ""
    default_channel: int = 0
    dedup_db_path: str = (_SPROUT_DATA / "wechat_dialog_dedup.db").as_posix()
    workspace_by_channel: dict[str, str] = field(default_factory=dict)
    workspace_by_user: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class WeixinIlinkSettings:
    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    token_env: str = "WECHAT_ILINK_TOKEN"
    account_id_env: str = "WECHAT_ILINK_ACCOUNT_ID"
    default_workspace_id: str = ""
    accounts_dir: str = (_SPROUT_DATA / "weixin_ilink" / "accounts").as_posix()
    context_tokens_dir: str = (_SPROUT_DATA / "weixin_ilink" / "context_tokens").as_posix()
    #: ``closed`` (the default) ignores every sender absent from ``allowed_users``.
    #: Fail closed: an unconfigured bot is one nobody can drive. ``open`` is the
    #: explicit opt-out and is logged as a warning at startup (audit R10).
    dm_policy: str = "closed"
    allowed_users: tuple[str, ...] = ()


@dataclass(slots=True)
class SqliteSettings:
    """Per-connection SQLite tuning (M1)."""

    busy_timeout_ms: int = 5000
    synchronous: str = "NORMAL"
    wal_autocheckpoint: int = 1000
    mmap_size: int = 268435456
    share_connections: bool = True
    schema_version: int = 1
    readers: int = 2


@dataclass(slots=True)
class ContextSettings:
    """How much Context Space a turn is allowed to spend (M4)."""

    working_window: int = 20
    anchor_turns: int = 4
    token_budget: int = 0  # 0 = model window × 0.75
    summary_ratio: float = 0.15
    history_ratio: float = 0.30
    recalled_ratio: float = 0.08
    knowledge_ratio: float = 0.08
    skills_ratio: float = 0.06
    completion_ratio: float = 0.20
    compress_threshold: float = 0.85
    offload_threshold: int = 8192
    compact_model: str = ""
    split_on_task_boundary: bool = True
    char_per_token: float = 1.6  # CJK-aware estimator


@dataclass(slots=True)
class MemorySettings:
    """Memory layer tuning (M3/M6/M7).

    Code lives at ``src/Sprout/memory/`` (the layer, peer to context and
    rootstock). Runtime state — ``MEMORY.md`` / ``USER.md`` / per-session
    facts — lives at ``home`` (default ``~/.sprout/data/memory/``), gitignored as
    local data alongside the SQLite databases.
    """

    enabled: bool = True
    user_enabled: bool = True
    home: str = (_SPROUT_DATA / "memory").as_posix()
    session_char_limit: int = 1400  # Chinese-corrected, not Hermes 2200
    user_char_limit: int = 850  # Chinese-corrected, not Hermes 1375
    write_approval: bool = False
    auto_extract: bool = False
    fts_cjk: str = "auto"  # auto | on | off
    require_user_id: bool = True  # C8: refuse writes without a user id


@dataclass(slots=True)
class Settings:
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    model: ModelSettings = field(default_factory=ModelSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    sqlite: SqliteSettings = field(default_factory=SqliteSettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    security: SecuritySettings = field(default_factory=SecuritySettings)
    mcp: MCPSettings = field(default_factory=MCPSettings)
    evolution: EvolutionSettings = field(default_factory=EvolutionSettings)
    web: WebSettings = field(default_factory=WebSettings)
    feishu: FeishuSettings = field(default_factory=FeishuSettings)
    wechat_dialog: WeChatDialogSettings = field(default_factory=WeChatDialogSettings)
    weixin_ilink: WeixinIlinkSettings = field(default_factory=WeixinIlinkSettings)
    skills_dir: str = (Path.home() / ".sprout" / "skills").as_posix()
    skills: SkillsSettings = field(default_factory=SkillsSettings)

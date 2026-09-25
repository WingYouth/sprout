"""Default settings and a documented configuration template."""

from __future__ import annotations

from Sprout.config.settings import Settings

EXAMPLE_TOML = """\
# sprout.toml -- SEAM Sprout configuration (TOML, stdlib-parsed)
# Secrets are never stored here; they come from environment variables.

[runtime]
default_agent = "assistant"
max_tool_steps = 8
verify_loops = 2
agent_max_attempts = 2
agent_timeout_seconds = 300
evaluation_timeout_seconds = 600
evaluation_attempts = 2

# Aiyallm provider definitions. The first name + first model is the default
# route; omit api_key to let aiyallm resolve the provider's local credential.
[[models]]
name = "deepseek"
account = "billing-deepseek"
type = "openai_compatible"
base_url = "https://api.deepseek.com"
models = ["deepseek-flash"]

[storage]
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"
blobs_dir = "<home>/.sprout/data/sprout_blobs"
trajectory_dir = "<home>/.sprout/data/sprout_trajectory"
project_root = "<home>/.sprout/data/projects"

[storage.observations]
enabled = true
dsn = "sqlite:////<home>/.sprout/data/sprout_audit.db"

[security]
allow_medium_risk = true
require_approval = true

# Web API authentication (AUTHZ §2.1). Leave it false only while the server
# binds loopback: with it false, every route — including approval decisions and
# proposal apply — is reachable by anyone who can open a socket. Turn it on and
# export the named variable; the server refuses every request if it is empty.
web_auth_enabled = false
web_api_token_env = "SPROUT_WEB_TOKEN"

# The hard floor (AUTHZ §1.3) is always on; writing it out is self-documentation.
[security.floor]
enabled = true

# Organization layer: command globs that are always denied (fnmatch).
[security.rules]
deny  = ["git push --force*", "git push -f*"]
allow = []

# Workspace layer: "action:path-glob" = allow | allow_redacted | sandbox_only
#                               | require_approval | deny
# [security.rules.workspace]
# "file.read:src/**"   = "allow"
# "file.read:~/.sprout/data/**" = "allow_redacted"
# "file.write:src/**"  = "sandbox_only"

# Resource classification overrides: glob = ResourceKind (AUTHZ §3.1).
# [security.classify]
# "*.pem" = "secret"
# "fixtures/**" = "data"

# Server-side command allowlist, replacing model-supplied known_command (§6.1).
[security.commands]
allowlist = []
denylist = []
# auto_run is the list of commands that may run with NO approval. It is empty on
# purpose: every build tool (pytest, npm, make, cargo…) executes code the task
# itself can write into the sandbox, so an empty list means verification runs ask
# a human. Add names here only if you accept that the agent's own code will run
# unapproved.
auto_run = []
# inherit_env = ["MY_TOOL_HOME"]

# Outbound network guard: SSRF and cloud-metadata protection (§6.3).
[security.network]
allow_private = []
blocked_domains = []

# Tamper-evident authorization stream (§7.1).
[security.audit]
enabled = true
path = "<home>/.sprout/data/audit/security.jsonl"
record_allows = true

# Approval behaviour per task source (§5.3): cron/automation default to deny.
[security.approvals]
unattended = "deny"
timeout_seconds = 3600.0
sweep_interval_seconds = 300.0

[mcp.server]
enabled = true
transport = "stdio"

# [[mcp.clients]] lets Sprout use external MCP servers as tools:
# [[mcp.clients]]
# name = "filesystem"
# command = "npx"
# args = ["-y", "@modelcontextprotocol/server-filesystem", "~/.sprout/data"]

[evolution]
enabled = true
approval_required = true
level = 1

[web]
host = "127.0.0.1"
port = 8000

[feishu]
enabled = false
verification_token_env = "FEISHU_VERIFICATION_TOKEN"
app_id_env = "FEISHU_APP_ID"
app_secret_env = "FEISHU_APP_SECRET"
encrypt_key_env = "FEISHU_ENCRYPT_KEY"
default_workspace_id = ""
domain = "feishu"

[wechat_dialog]
enabled = false
token_env = "WECHAT_DIALOG_TOKEN"
encoding_aes_key_env = "WECHAT_DIALOG_ENCODING_AES_KEY"
appid_env = "WECHAT_DIALOG_APPID"
default_workspace_id = ""
default_channel = 0
dedup_db_path = "<home>/.sprout/data/wechat_dialog_dedup.db"

# [wechat_dialog.workspace_by_channel]
# 0 = "workspace-id-for-channel-0"
# 7 = "workspace-id-for-h5"

# [wechat_dialog.workspace_by_user]
# "openid-1" = "workspace-id-for-user-1"

[weixin_ilink]
enabled = false
base_url = "https://ilinkai.weixin.qq.com"
token_env = "WECHAT_ILINK_TOKEN"
account_id_env = "WECHAT_ILINK_ACCOUNT_ID"
default_workspace_id = ""
accounts_dir = "<home>/.sprout/data/weixin_ilink/accounts"
context_tokens_dir = "<home>/.sprout/data/weixin_ilink/context_tokens"
# "closed" denies every sender that is not listed below. Set it to "open" to
# accept everyone (logged as a warning at startup).
dm_policy = "closed"
# allowed_users = ["wx-user-1"]
"""


def default_settings() -> Settings:
    """Local-only defaults: SQLite files and no MCP clients.

    Deliberately carries no usable model (``provider="aiyallm"``, empty
    ``model``) so a runtime that was never configured fails loudly instead of
    silently answering from echo. Tests and offline runs must opt in with
    ``settings.model.provider = "echo"``.
    """
    return Settings()

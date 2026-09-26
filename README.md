<div align="center">
  <a href="README.md">English</a> |
  <a href="README_CN.md">简体中文</a> |
  <a href="README_ZH-HANT.md">繁體中文</a> |
  <a href="README_JA.md">日本語</a> |
  <a href="README_KO.md">한국어</a> |
  <a href="README_RU.md">Русский</a> |
  <a href="README_ES.md">Español</a> |
  <a href="README_PT.md">Português</a>
</div>

<br />

<div align="center">
  <img src="assets/seam_sprout.svg" alt="SEAM Sprout logo" width="200" />
</div>

<h1 align="center">SEAM Sprout</h1>

SEAM Sprout is an AI engineering runtime embedded inside a software project. It moves a change from user intent to code edits, isolated execution, verification, approval, integration, and traceability, so AI can do more than suggest: it can complete a controlled, reviewable engineering loop inside the project boundary.

The core problem Sprout solves is that real software work is full of small but consequential changes, while context is scattered, risk is hard to control, verification is tedious, and hard-won project knowledge is rarely reused. Sprout brings the codebase, sessions, memory, knowledge, tools, approvals, and audit trail into one runtime so a project can be maintained, repaired, and improved continuously while humans stay in control of dangerous actions.

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## What Sprout Solves

Sprout is built for project-level change delivery, not one-off code Q&A. It places AI inside a controlled pipeline: read project evidence, build a plan, modify code in an isolated worktree, run checks, produce a reviewable proposal, then apply the approved result back to the project with a trace.

| Real project pain | Why it is hard | Sprout's answer |
|---|---|---|
| **AI gives an answer, but the engineering work is still unfinished** | A snippet still has to land in the right files, fit the existing design, pass tests, and survive conflicts. | Turns natural-language requests into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered across code, data, docs, and prior conversations** | Good engineering decisions depend on repository structure, interfaces, storage schemas, historical decisions, and the current goal. | Combines project scans, sessions, memory, knowledge, and storage evidence inside one runtime. |
| **Generated code looks plausible but is not proven** | LLM output is often reviewed before it has run in the target environment. | Executes changes and checks in a git-worktree sandbox, then attaches verification evidence to the proposal. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network access, and database access can break systems, leak secrets, or bypass ownership. | Routes dangerous actions through risk levels, policies, approvals, and controlled brokers. |
| **Maintenance work keeps piling up** | Small bugs, documentation drift, interface mismatches, refactors, and missing tests are important but easy to defer. | Continuously scans, repairs, and creates reviewable growth candidates for future improvement. |
| **Learning does not compound across tasks** | Fixes, project preferences, and workflow knowledge disappear into chat history. | Persists trajectories, memory, knowledge, and versioned skills so completed work can improve future work. |
| **Multiple surfaces drift apart** | CLI, web, MCP, Python API, and gateways can end up with different behavior, permissions, and audit paths. | Sends every surface through the same `create_runtime()` assembly path with shared storage, authorization, events, and audit. |
| **Storage and infrastructure are difficult to trust** | Sessions, knowledge, audit, vectors, graph data, and cache state may live in different backends. | Provides initialization, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## Product Capabilities

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns project-scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and applies file, process, and change operations through brokers.
- **Isolated execution and verification**: runs changes and checks in a git-worktree sandbox before touching the main project.
- **Change integration and traceability**: turns verified work into proposals, waits for approval, applies accepted changes, and records the full trace.
- **Project-level memory**: persists sessions, memory, knowledge, and task history so each task builds on accumulated context.
- **Automatic growth**: learns from completed work and creates reviewable candidates for future improvement.
- **Unified entry points**: exposes one runtime through the Python API, React web console, interactive CLI, MCP server, and gateways.
- **Reusable skills**: imports and manages versioned skills through a safety-scanning broker, extending what the agent can do.

## Use Cases

- Projects that need an embedded AI engineering runtime instead of an external chat assistant.
- Teams that want AI-generated code to pass through tests, approvals, audit, and integration.
- Codebases with ongoing repair, refactoring, test coverage, documentation, and interface-alignment work.
- Organizations that require project-level memory, traceable automation, and reusable engineering capabilities.

## Safety Boundary

Every risky action goes through the authorization layer (hard floor → policy layers → approvals), and changes land in a git-worktree sandbox. That sandbox isolates *change visibility*, not *privileges*: agent processes share the host filesystem, OS user, network, and kernel, and there is no container or OS-level backend. Of the seven execution brokers, the file, process, and apply brokers are the ones assembled into the runtime today; the network, database, and git brokers exist but are not yet wired into the agent path.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Persistence | SQLite, JSONL, filesystem blobs, in-memory stores (Milvus, Neo4j, Redis reserved) |
| Configuration | TOML with typed dataclass settings |
| Tooling | uv, pytest, pytest-asyncio, ruff |

## Project Layout

```text
src/Sprout/
├── runtime/       # Runtime, middleware, lifecycle, workspace, locks, queues, and assembly
├── agent/         # Agent protocol, AgentLoop, routing, planning, execution
├── session/       # Session and turn models
├── memory/        # Memory composition, budgets, snapshots, and persistence
├── context/       # AgentContext and context building
├── message/       # Unified messages, attachments, and conversion
├── llm/           # Model providers: echo, OpenAI-compatible, aiyallm
├── tools/         # ToolSpec, security-gated executor, registry, system tools
├── skills/        # Versioned skills and skill repository
├── security/      # Risk levels, policy, approval
├── events/        # In-process event bus
├── registry/      # Generic registries
├── storage/       # Storage contracts and local implementations
├── evolution/     # Growth layer, replay, maintenance, and trajectory growth
├── strategy/      # Requirement decomposition, impact analysis, and verification plans
├── artifacts/     # Artifact models and metadata
├── capability/    # Capability models
├── execution/     # Change application and broker adapters
├── gateway/       # Runtime, RPC, task, daemon, and transport gateways
├── orchestration/ # Graph compiler, Temporal terminal, worker, and workflows
├── rootstock/     # Session/root persistence backends
├── sandbox/       # Git worktree sandbox
├── task/          # Task models and lifecycle
├── trajectory/    # Trajectory persistence
├── workspace/     # Workspace helpers
├── config/        # Typed settings and TOML loading
├── scheduler/     # Scheduled task support
├── cli/           # sprout command line
└── mcp/           # MCP server, client, and adapters

web/
├── frontend/      # Vite + React web console
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Starlette HTTP/WebSocket application, routes, and database

assets/            # Shared logo and static project assets
~/.sprout/docker/  # Six-database stack: compose file, runner image, bootstrap
```

## Requirement Strategy

`src/Sprout/strategy/` turns a project-scan suggestion or a direct user request
into a reviewable implementation plan. Its `StrategyPipeline` is read-only at
the planning stage and produces the evidence needed before any code is changed.

```text
Project scan / user request
            |
            v
      RequirementIntake
            |
            +-------------------------+
            |                         |
            v                         v
   Database evidence            Full project scan
   schema / records             code / interfaces / tests
            |                         |
            +-----------+-------------+
                        v
                 Cross validation
                        |
                        v
                  ImpactAnalyzer
                        |
                        v
       add / modify / mixed + test plan
                        |
                        v
     database / API / code verification criteria
                        |
                        v
       approval -> coder(apply_patch) -> tests
                        |
                        v
        ChangeProposal -> formal apply -> Git record
```

The impact analysis uses two evidence sources:

- **Database evidence**: read-only access through the database broker to check
  schemas, tables, migrations, persisted records, and existing interface or
  task history.
- **Project evidence**: a full workspace scan that locates source files,
  interfaces, database-related code, and test files, with workspace graph
  relationships when available.
- **Cross validation**: compare both sources and mark matches, database-only
  objects, code-only objects, and unresolved conflicts. Conflicts are surfaced
  for human review instead of being silently treated as permission to edit.

The strategy layer owns requirement intake, impact analysis, change-mode
selection, acceptance criteria, and test-file planning. `workspace/` supplies
read-only project evidence, `runtime/changes.py` owns proposal approval and
formal apply/rollback, and `execution/` owns patch, database, process, and Git
brokers.

## Installation

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

The default configuration is fully offline: the `echo` model provider, local SQLite databases, and no external MCP clients.

For the `aiyallm` model provider, install its distribution:

```bash
pip install aiyallm
```

### Six databases in two commands

The runtime fans out to six databases. Three are plain files — SQLite, the
JSONL evidence log and the blob store — so they need no installation at all;
the other three (Redis, Milvus, Neo4j) are containers. Two commands cover the
lifecycle:

```powershell
sprout db init                    # create/init all configured lanes
sprout db status                  # report healthy/failed per lane
sprout db backup <dir>            # back up SQLite databases
sprout db restore <dir>           # restore SQLite databases
```
```bash
sprout db init
sprout db status
```

`init` builds the five SQLite schemas, the JSONL and blob directories, the three
Milvus collections and the Neo4j constraints — idempotent, and it writes no
rows. `test` writes a session, two turns, a memory fact and an oversized context
snapshot through the normal storage bundle and then reads every lane back with
that lane's own client, which is what makes "all six are up" a verified fact
rather than a claim. `sprout db init` initializes all configured lanes and
`sprout db status` checks them one at a time.
With Docker, `init` also pulls the three service images (with a mirror fallback
for blocked Docker Hub), builds the runner image, starts the lanes, and proves
them.

Ports, configuration, the three testing layers, the no-Docker profile and
troubleshooting live in `~/.sprout/docker/README.md`.

## Usage

### Agent

The Python API is the core usage surface. Build a runtime and send a `Message`:

```python
import asyncio
from Sprout.config.defaults import default_settings
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime

async def main() -> None:
    runtime = create_runtime(default_settings())
    async with runtime:
        reply = await runtime.handle(Message("hello", channel="python"))
        print(reply.content)

asyncio.run(main())
```

All entry points use `create_runtime()` as the single assembly path.

### Web

The web console is a component-based React application built with Vite.

Build the frontend once:

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

Then start the web console:

```bash
uv run sprout serve
```

Open `http://127.0.0.1:8000`. The web application provides chat, a task board, task management, and configuration settings.

For frontend development with hot reload:

```bash
cd web/frontend
npm run dev
```

Available HTTP endpoints include:

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/sessions/{session_id}/history`
- `GET /api/tasks`, `POST /api/tasks`
- `PATCH /api/tasks/{task_id}`, `DELETE /api/tasks/{task_id}`
- `GET /api/settings`, `PUT /api/preferences`
- `GET /api/tokens`
- `GET /api/logs`
- `GET /api/storage/status`, `GET /api/storage/plan`
- `GET /api/storage/graph/status`, `GET /api/storage/vectors/count`
- `GET /api/health`

The WebSocket endpoint is available at `ws://127.0.0.1:8000/ws/chat`.

### CLI

```bash
uv run sprout --help
uv run sprout                     # interactive chat
uv run sprout chat "hello"        # one-shot message
uv run sprout info                # runtime and configuration snapshot
uv run sprout project workspace <path>   # open a local workspace
uv run sprout remote workspace-list      # operate a remote SEMA service
uv run sprout db init             # initialize all configured lanes
uv run sprout db status           # report healthy/failed per lane
uv run sprout db backup ./backup  # back up local databases
uv run sprout mcp inspect         # inspect MCP definitions
uv run sprout evolution candidates  # growth layer: what the pipeline has produced
uv run sprout skills import ~/code/my-skills   # import skills from a local directory
uv run sprout skills list         # what is installed
uv run sprout skills index --rebuild   # sync the snapshot, report registry/disk drift
uv run sprout skills forget <name>     # drop a registry row, leave the files
uv run sprout serve               # web console and API
uv run sprout stop serve          # stop the web console
```

`skills import` walks a directory recursively, treating a folder that contains a
`SKILL.md` as one skill and single-file `*.toml` skills as their own entries. It
finds nested layouts (`skills/writing/docs/SKILL.md`), skips vendored
directories, and installs each skill through the same broker the rest of the
subsystem uses — scanned for unsafe content, then decided by the policy engine.
Because a local path is a first-party source, nothing needs approving; the
scanner's fatal-finding floor still applies and cannot be approved past.

### CLI Language

The interactive CLI can switch its menu language without restarting:

```text
/language
/language ja
/language zh-Hant
```

Supported languages are listed in
[`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md). The
selection is stored in `~/.sprout/settings.json` and reused by the next session.

### Temporal

Task orchestration, queues, schedules, evolution automation, web jobs, and
gateway work can run on Temporal.

Start a local Temporal server with the bundled Compose stack:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Then check it is reachable without installing the Temporal CLI:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` reports server reachability, server version, namespace presence, and
the number of workers polling the configured task queue.

### MCP

Run the MCP server over stdio:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

The server exposes safe operations only: sending messages, creating sessions, reading session history, listing skills, and searching knowledge. High-risk writes, approvals, and growth publishing remain outside the MCP surface.

Inspect the exposed tools, resources, and prompts:

```bash
uv run sprout mcp inspect
```

## Configuration

The user config lives at `~/.sprout/sprout.toml`. Keep configuration in that
single file; do not add a duplicate project-local `sprout.toml`. Use
`SPROUT_CONFIG` only to point at a different explicit path when necessary.

Project Runtime MCP tools include:

```text
workspace_scan
workspace_query
task_create
task_execute
task_plan
task_changes
sandbox_diff
sandbox_test
trajectory_query
proposal_show
proposal_request_approval
proposal_reject
proposal_apply
```

## Real Model Configuration

Edit `~/.sprout/sprout.toml` to use DeepSeek or another provider:

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"
base_url = "https://your-provider.example/v1"

[web]
host = "127.0.0.1"
port = 8000

[storage]
# Sprout runtime authorities: sqlite | jsonl | blobstore for conversation;
# Milvus/Neo4j/Redis remain derived and are never authorities.
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

Secrets are read from environment variables, never from the configuration file.

## Development

```bash
uv run pytest
uv run ruff check .
```

See [guidance.md](guidance.md) for the development workflow and CLI/MCP exposure rules.

## Contributors

Thanks to everyone who has contributed to SEAM Sprout:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## License

This project is licensed under the [MIT License](LICENSE).

---

# Supplementary Project Documents

## Agent Instructions

# SEAM_Sprout

> 项目上下文 · 由 Hermes Agent 自动维护

## 项目概述

SEAM_Sprout 项目。具体目标和范围待补充。

## 关键决策

*重要的技术选型、业务规则、架构决策将自动记录于此。*

## 项目结构

*目录结构和模块说明。*

## 约定与规范

*开发规范、命名规则、编码约定。*

## TODO

- [ ] 补充项目概述
- [ ] 明确项目目标

---

*此文件由 Hermes Agent 自动生成并维护。每次对话中讨论的关键信息会自动更新到此文件。*

---

## Gateway Design

# Gateway 方案文档

## 1. 定位

Gateway 属于 SEMA V1.0 的 Interface Layer。

核心职责：

- 把不同入口统一转换为 Task
- 绑定 Caller Identity
- 绑定 DelegationScope
- 调用 Runtime 公共服务
- 把 TaskResult 转回调用方格式

Gateway 不允许绕过 Runtime、Policy、Trajectory。

## 2. 核心原则

```text
所有入口最终统一成 Task
Gateway 不包含 Agent 业务逻辑
Gateway 不直接访问 Storage 和 Broker
External Agent 不能因 Runtime 权限更高而扩权
EffectivePolicy 必须包含 DelegationScope
```

## 3. 当前模块结构

```text
src/Sprout/gateway/
├── base.py
├── identity.py
├── registry.py
├── task_adapter.py
├── runtime_gateway.py
├── project_gateway.py
├── transport_gateways.py
├── delegation_gateway.py
├── sdk_gateway.py
├── daemon_gateway.py
├── daemon_client.py
├── rpc_gateway.py
├── rpc_client.py
├── rpc_errors.py
├── manager.py
└── channels/
    ├── __init__.py
    ├── feishu.py
    └── wechat_dialog.py
```

## 4. 已实现组件

### 4.1 Gateway 协议

文件：`gateway/base.py`

```python
class Gateway(Protocol):
    async def receive(self) -> Message
    async def send(self, message: OutboundMessage) -> None
```

### 4.2 Principal

文件：`gateway/identity.py`

表示调用者身份：

```text
user_id
display_name
roles
```

### 4.3 GatewayRegistry

文件：`gateway/registry.py`

提供：

```text
register()
get()
list()
```

### 4.4 GatewayRequest / GatewayResponse

文件：`gateway/task_adapter.py`

```text
GatewayRequest
  transport
  instruction
  caller
  workspace_id
  delegation_scope
  budget
  metadata

GatewayResponse
  task_id
  status
  content
  metadata
```

### 4.5 TaskAdapter

文件：`gateway/task_adapter.py`

提供：

```text
GatewayRequest -> Task
Message -> GatewayRequest
```

### 4.6 RuntimeGateway

文件：`gateway/runtime_gateway.py`

统一 Runtime 门面：

```text
GatewayRequest -> Task -> Runtime.execute() -> GatewayResponse
```

同时提供：

```text
execute_message()
handle_message()
```

### 4.7 ProjectGateway

文件：`gateway/project_gateway.py`

统一 Project 操作：

```text
open_workspace()
list_workspaces()
create_task()
execute()
run_task()
list_changes()
show_proposal()
find_proposal()
approve_proposal()
reject_proposal()
apply_proposal()
rollback_proposal()
```

### 4.8 内置 Transport Gateway

文件：`gateway/transport_gateways.py`

```text
CLIGateway
WebGateway
MCPGateway
```

它们都通过 RuntimeGateway 执行 Task。

### 4.9 外部能力 Gateway

```text
DelegationGateway
SDKGateway
DaemonGateway
```

### 4.10 外部 Client

```text
DaemonClient
RPCClient
src/Sprout/cli/commands/remote.py
```

远程命令统一挂在内部 CLI 的 ``remote`` 子命令下：

```text
sprout remote workspace-open ...
sprout remote task-create ...
```

### 4.11 RPC Gateway

文件：`gateway/rpc_gateway.py`

支持：

```text
workspace.open
workspace.list
task.create
task.run
task.changes
```

### 4.12 RPC 错误码

文件：`gateway/rpc_errors.py`

```text
PARSE_ERROR
INVALID_REQUEST
INVALID_PARAMS
METHOD_NOT_FOUND
NOT_FOUND
INVALID_STATE
INTERNAL_ERROR
```

### 4.13 GatewayManager

文件：`gateway/manager.py`

统一管理：

```text
cli
web
mcp
```

### 4.14 飞书 Gateway

文件：`gateway/channels/feishu.py`

支持：

```text
URL 验证
文本消息事件
身份映射
Task 执行
文本回复
```

飞书 HTTP 路由：

```text
POST /api/gateway/feishu/event
```

### 4.15 微信对话开放平台 Gateway

文件：`gateway/channels/wechat_dialog.py`

支持：

```text
第三方客服回调消息解密
用户消息事件解析
身份映射
Task 执行
sendmsg 客服消息加密回复
SQLite 持久化幂等
渠道 / 用户到 Workspace 映射
```

微信对话开放平台 HTTP 路由：

```text
POST /api/gateway/wechat_dialog/event
```

## 5. 核心流程

### 5.1 内置入口流程

```text
CLI / Web
  -> CLIGateway / WebGateway
  -> ProjectGateway
  -> RuntimeGateway
  -> TaskAdapter
  -> Task
  -> Runtime.execute()
  -> GatewayResponse
```

### 5.2 Message 流程

```text
Message
  -> RuntimeGateway.handle_message()
  -> Runtime.handle()
  -> GatewayResponse
```

### 5.3 外部 Agent 委派流程

```text
External Agent
  -> DelegationGateway
  -> GatewayRequest
  -> Task
  -> Runtime.execute()
  -> GatewayResponse
```

### 5.4 Python SDK 流程

```text
Python App
  -> SDKGateway
  -> RuntimeGateway
  -> Task
  -> Runtime.execute()
```

### 5.5 Daemon / RPC 流程

```text
External CLI / Business App
  -> RPCClient / DaemonClient
  -> POST /api/rpc 或 /api/project/*
  -> RPCGateway / DaemonGateway
  -> ProjectGateway
  -> Runtime.execute()
```

### 5.6 飞书流程

```text
Feishu Event
  -> POST /api/gateway/feishu/event
  -> FeishuGateway
  -> 验证 Token
  -> 解析消息
  -> Principal
  -> GatewayRequest
  -> RuntimeGateway
  -> Task
  -> Runtime.execute()
  -> 文本回复
```

### 5.7 微信对话开放平台流程

```text
微信对话开放平台回调
  -> POST /api/gateway/wechat_dialog/event
  -> WeChatDialogGateway
  -> AES 解密消息
  -> 解析 from/userid/content/channel
  -> Principal
  -> GatewayRequest
  -> RuntimeGateway
  -> Task
  -> Runtime.execute()
  -> sendmsg 加密回复
```

## 6. 当前完成状态

已完成：

```text
Gateway 基础协议
身份模型
Task 转换
Runtime 门面
Project 门面
CLI / Web / MCP 内置入口
MCP / Delegation / SDK / Daemon 外部能力
DaemonClient / RPCClient
RPCGateway / RPC 错误码
飞书适配器和 HTTP 回调
微信对话开放平台适配器和 HTTP 回调
`sprout remote` 基础命令
```

尚未完成：

```text
企业微信
QQ
Slack
RPC 鉴权
RPC 限流
远程 CLI 命令补全
飞书生产级加解密和卡片消息
渠道级用户 / Workspace 映射
```

## 7. 后续建议

下一步优先级：

```text
1. RPC 鉴权
2. 远程 CLI 命令补全
3. 飞书生产级能力
4. 企业微信 Adapter
5. 微信对话开放平台富文本消息
6. QQ / Slack Adapter
```

---

## Manual Test Plan

# SEAM_Sprout 手工测试用例集

面向人工验收的测试清单,覆盖 CLI、Agent、Web、存储、安全、技能、进化等全部可操作面。

- **版本**:`d11c442`(branch `dev`)
- **整理日期**:2026-09-24
- **约定**:每条用例含 `前置条件 → 操作 → 预期结果`。优先级 **P0** 必测,**P1** 重要,**P2** 可选/极客向。
- 标记说明:🌐 需要外网 · 🐳 需要 Docker · 🔑 需要真实模型 API Key · 👤 需要外部账号

---

## 0. 环境准备与已知坑

### 0.1 统一命令前缀

本项目虚拟环境是 `.venv`,且**必须**设置 `PYTHONPATH=src`(conda 的 python 缺少依赖 `aiyallm`)。

```bash
cd D:/dev/projects/SEAM_Sprout
export PYTHONPATH=src
SPROUT=".venv/Scripts/python.exe -m Sprout.cli.app"
```

之后所有 `sprout <cmd>` 均等价于 `$SPROUT <cmd>`。

> 若已 `uv sync` 并激活环境,也可直接用 `uv run sprout <cmd>`。

### 0.2 首次运行会发生什么

任何 `sprout` 命令第一次执行时,都会打印三行初始化日志:

```
[1/3] 初始化 ~/.sprout 目录布局
[2/3] 写入缺失的配置文件
[3/3] 预留本地数据库
Sprout 主目录已就绪
```

**这是正常的**(`ensure_sprout_home()`),不是错误。它在 stdout 出现,**会污染 `--json` 输出**。设计上应重定向到 stderr —— 见用例 **TC-1.4** 验证。

### 0.3 ⚠️ 已知环境问题(实测确认)

| # | 问题 | 现象 | 处理 |
|---|---|---|---|
| **KB-1** | 裸 `pytest` 在 Windows 上崩溃 | `PermissionError` 访问系统临时目录 | 必须加 `--basetemp=.pytest_tmp -p no:cacheprovider` |
| **KB-2** | ~~`sprout chat` 启动 Docker 冲突~~ **已彻底修复(2026-09-24)** | 原:`Container name "/sprout-milvus" is already in use` | 根因是**固定 `container_name` 无视 `--project-name`**,两个 compose project 抢同一个 `/sprout-*` 名字。修复三层:①模板**删掉 `container_name`**(project 名自动限定容器名);②**先探测端口**,已通则完全不碰;③**停着的容器用 `docker start` 收养**,不重建(其匿名卷里是真实数据)。**不再需要任何环境变量变通** |
| **KB-3** | ~~`sprout evolution status` 不存在~~ **已修(2026-09-24)** | 原:`No such command 'status'.`(退出码 2) | 两份 README 都已改为 `sprout evolution candidates`;若在别处再见到 `evolution status`,那是漏改的旧文档 |
| **KB-4** | 本机审计流第 0 行有**异物行**(非"链断") | `sprout audit verify` → `1 line(s) are not audit entries: line 0`,退出码 1 | 链本身完好(4363 条全部自洽);根因是流里混入一行 `{"probe": ...}`。见 **TC-7.2** |
| **KB-5** | 前端未构建 | `web/frontend/dist` 不存在,`sprout serve` 的 `static dir` 显示 `not found` | 需先 `cd web/frontend && npm install && npm run build` |
| **KB-6** | `FORCE_COLOR` 未设置时与 CLI help 断言 | 环境变量相关,macOS/Linux 常见 | 如遇 help 输出测试失败,先 `unset FORCE_COLOR` |
| **KB-7** | **`.pytest_tmp/` 里的产物会被 pytest 整个删光** | 跑测试时无任何报错,但目录里的**非测试文件**(如数据库备份)在开跑瞬间消失 | pytest 每次启动**重建** basetemp 树。**长期产物不能放 `.pytest_tmp/` 下** —— 备份放仓库根的 `backups/`(已加入 `.gitignore`,因为里面是操作者数据库副本) |

### 0.4 验收基线(实测)

| 项目 | 当前实测值 | 判定 |
|---|---|---|
| 自动化测试 | `1118 passed, 11 skipped` | ✅ 全绿 |
| Lint | `ruff check src web` → `All checks passed!` | ✅ |
| 模型 | `deepseek-chat` @ aiyallm,`DEEPSEEK_API_KEY` 已配置 | ✅ 可跑真实对话 |
| 六条存储链路 | 全部 healthy(需 Docker 在跑) | ✅ |
| **端到端可跑通** | 给一个真实仓库 → 分析 → 建任务 → 跑 → 停审批 → 批准 → 出提案 → 应用 | ✅ 见 §0.5 |

### 0.5 端到端闭环(实测,真实模型)

「给 Sprout 一个项目,它能分析、改代码、写代码吗」—— **能**。用真实模型实跑过一次:

1. 打开工作区并 `analyze` → 落库 **5 个知识点、6 条边、3 条知识**
2. `task-create` + `task-run` → 任务在 `waiting_approval` 停下(验证命令需要人批准)
3. 批准该验证授权 → agent 节点约 **11 秒**完成;sandbox worktree 里是**正确**的
   `safe_divide` 实现 **加上它自己写的测试**(`3 passed`)
4. **项目目录本身按设计未被改动** —— 改动只在 sandbox 里,直到你批准提案

注意第 4 点是**故意**的:agent 写的代码不落到你的仓库,除非你批准变更提案。
本轮修掉的三个缺陷都在第 3–4 步上(见附录 B.1)。

---

## 1. 安装与冒烟(启动路径)

### TC-1.1 版本与配置快照 — P0
- **操作**:`$SPROUT info`
- **预期**:
  - 顶部显示 `SEAM Sprout 0.1.0` / `Runtime and configuration snapshot`
  - 分节打印 **Runtime / Model / Storage / Security / Evolution / Web / Entry Points**
  - `Model` 段显示 `provider aiyallm (deepseek-chat)`
  - 退出码 0

### TC-1.2 帮助系统 — P0
- **操作**:`$SPROUT --help`
- **预期**:底部 `Quick examples` 区块列出 `sprout chat "hello"`、`sprout info`、`sprout storage init` 等;并说明配置文件位置(`sprout.toml` 或 `SPROUT_CONFIG`)。

### TC-1.3 无参数启动交互 — P0
- **操作**:`$SPROUT`(不带任何子命令)
- **预期**:直接进入交互式对话 REPL,显示 ASCII logo 与 `输入 / 探索命令` 提示。`Ctrl+C` / `/exit` 可退出。

### TC-1.4 `--json` 输出纯净性 — P1
- **操作**:
  ```bash
  $SPROUT security check --json > out.json 2>err.txt
  .venv/Scripts/python.exe -c "import json;json.load(open('out.json'));print('valid json')"
  ```
- **预期**:打印 `valid json`。初始化日志应落在 `err.txt`,**不出现在 stdout**。
- **这是回归用例**:历史上 boot 日志混进 stdout,导致 JSON 无法解析。

### TC-1.5 控制台中文编码 — P1
- **操作**:在 Windows 终端(cp936/gbk)直接运行 `$SPROUT info`
- **预期**:中文标签正常显示,无乱码(`_configure_console_encoding()` 应把流重设为 UTF-8)。

---

## 2. 对话与 Agent 核心

### TC-2.1 一次性对话(真实模型) — P0 🔑
- **前置**:无。需先 `set -a && . ./.env && set +a`(密钥只在 `.env`,不会自动加载)
- **操作**:`$SPROUT chat "reply with exactly: OK"`
- **预期**(实测输出):
  ```
  OK
    模型=deepseek-flash · 步骤=1 · 输入=3163 输出=1 总计=3164
  ```
  - 退出码 0
  - 底部打印模型名、步数、token 统计
  - **容器已在跑时不再需要任何环境变量**(KB-2 已修,2026-09-24 实测:无覆盖直接 EXIT=0)
- **失败排查**:若报 `Docker storage startup failed`,说明探测判定该端口不通而 `up` 又失败 —— 查 `docker ps` 与端口占用。

### TC-2.1b 容器已在跑时不重启(Bug 5 回归) — P1
- **目的**:锁住"先探测、后启动",防止 `docker compose up` 无脑重跑撞名。
- **前置**:Docker 三条链路已在跑(`docker ps` 有 `sprout-redis` / `sprout-milvus` / `sprout-neo4j`,状态 healthy)
- **操作**:**不设任何环境变量**(不要 `SPROUT_STORAGE_AUTO_START=false`),直接:
  ```bash
  $SPROUT chat "reply with exactly: OK"
  ```
- **预期**:
  - 退出码 **0**,输出 `OK`
  - 输出中**不得出现** `Container name "/sprout-*" is already in use`
  - 内部行为:三个端口(6380 / 19530 / 7687)均通 → `_services_needing_start` 返回 `[]` → **完全不 spawn `docker compose`**
- **冷机对照(必测另一半,别只测顺手的那半)**:停掉容器后同样的命令必须**仍然会**把栈拉起来 —— 探测的意义是跳过多余的 `up`,不是取消 `up`。
  ```bash
  docker stop sprout-redis sprout-milvus sprout-neo4j
  $SPROUT chat "reply with exactly: OK"     # 应自动 start 并成功
  ```
- **数据保全(本轮实测,最关键的一条)**:上面这步必须是 **`docker start`(收养)**,不是 `docker compose up`(重建)。判据:
  ```bash
  docker inspect sprout-redis --format '{{.Created}}'   # 必须还是旧日期,不能被刷新
  docker exec sprout-redis redis-cli DBSIZE             # 数字必须 >= 停之前的值
  ```
  **为什么关键**:旧栈的数据在**匿名卷**里(本机实测 redis 47 keys / neo4j 4780 nodes),而当前 compose 声明的命名卷 `sprout_sprout-redis-data` 是**空的**。一旦走 `up` 重建,数据不会被删,但会挂到没人引用的孤儿容器上 —— 对新栈而言等于丢了,且不可逆。
- **自动化**:`test_a_listening_lane_is_not_brought_up_again`、`test_a_silent_lane_is_still_brought_up`、`test_autostart_skips_compose_when_every_lane_listens`、`test_port_probe_reports_a_closed_port_as_down`、`test_the_lane_stack_does_not_pin_container_names`、`test_a_stopped_container_is_adopted_not_replaced`、`test_adoption_is_skipped_when_the_container_does_not_exist`、`test_every_adopted_lane_has_a_dsn_to_wait_on`

### TC-2.2 无 API Key 时的降级 — P1
- **操作**:`DEEPSEEK_API_KEY= $SPROUT chat "hello"`
- **预期**:给出明确的可读错误(提示配置 key),而不是堆栈崩溃。

### TC-2.3 交互 REPL 多轮上下文 — P0 🔑
- **操作**:进入 `$SPROUT`,依次输入:
  1. `我叫小明`
  2. `我叫什么?`
- **预期**:第二句能答出"小明",证明多轮上下文被保留。

### TC-2.4 Slash 命令补全 — P1
- **操作**:在 REPL 输入 `/` 然后按 Tab
- **预期**:弹出命令补全列表(`/storage`、`/session`、`/db`、`/info`、`/mcp`、`/memory`、`/project`、`/evolution`、`/approvals`、`/audit`、`/serve`、`/orchestrator` 等)。

### TC-2.5 语言切换 — P2
- **操作**:在 REPL 输入自然语言请求切换语言(如 "switch to English" / "用中文")
- **预期**:CLI 提示文案语言随之切换,且该切换被持久化到配置。

### TC-2.6 长文本粘贴折叠 — P2
- **操作**:向 REPL 粘贴超过数行的长文本
- **预期**:内容被折叠为占位符显示,提交后完整发送(`_normalize_pasted_text` / `_collapsed_paste_placeholder`)。

### TC-2.7 工具调用与步骤上限 — P1 🔑
- **操作**:`$SPROUT chat "列出当前目录下的文件"`
- **预期**:
  - 模型触发工具调用,元信息里 `步骤=` 大于 1
  - 步数不超过 `max_tool_steps`(默认 8)
  - 轮次不超过 `session_turn_limit`(默认 20)

### TC-2.8 隔离执行沙箱 — P1 🔑 🐳
- **操作**:`$SPROUT chat "在沙箱里运行 python -c 'print(1+1)'"`
- **预期**:走 `sandbox_*` 工具,输出 `2`;沙箱生命周期有起有落。

---

## 3. 会话管理

### TC-3.1 新建会话 — P0
- **操作**:`$SPROUT session new --user tester`
- **预期**:返回一个新的 session id;该 id 可用于后续所有 `--session` 参数。

### TC-3.2 历史回放 — P0
- **前置**:先走 TC-2.3 产生若干轮对话
- **操作**:`$SPROUT session history <session_id> --limit 20`
- **预期**:按 seq 顺序打印最近轮次,含 role 与内容。

### TC-3.3 全文检索 — P0
- **前置**:会话中存在含特定关键词的轮次
- **操作**:`$SPROUT session search "<关键词>"`
- **预期**:命中该轮次,显示所属 session 与片段。无命中时打印 `no hits`。
- **CJK 专项**:用**中文短语**(≥3 字)检索应能命中(trigram 分词)。
- **已知边界**:用 **2 个汉字**检索搜不到 —— 这是 trigram 的 3 字符下限,两种分词器都如此,**不是回归**。

### TC-3.4 压缩回卷 — P1
- **操作**:`$SPROUT session compact --through-seq <N>`
- **预期**:截至 N 的轮次被压成摘要,摘要落入 memory 层;再次 `history` 时被压缩部分不再逐条返回。

### TC-3.5 级联删除 — P0
- **操作**:`$SPROUT session delete <session_id>`
- **预期**:会话及其**派生产物**(检索索引、向量、图节点、附件链接)一并清除,无孤儿残留。

### TC-3.6 `db` 命名空间等价性 — P2
- **操作**:分别运行 `$SPROUT db session-history <id>` 与 `$SPROUT session history <id>`
- **预期**:两者结果一致(旧的 `db session-*` 是兼容入口)。

---

## 4. 存储六链路

### TC-4.1 初始化 — P0
- **操作**:`$SPROUT storage init`
- **预期**:
  - 逐条打印 4 个阶段(`[1/4]`…`[4/4]`)
  - SQLite 文件权限为 `0600`,父目录 `0700`(`--no-chmod` 可跳过)
  - 幂等:连续跑两次不报错
  - 退出码 0

### TC-4.2 全链路健康检查 — P0 🐳
- **操作**:`$SPROUT storage check`
- **预期**(实测):六条链路依次 `[  ok]`,末尾 `[ok] All six lanes hold the data.`
  - SQLite(authority)
  - JSONL(evidence)
  - BlobStore(objects)
  - Redis(hot path)
  - Milvus(vectors)
  - Neo4j(graph)
- **重点**:这是**写后读回**验证,不是"端口通不通"。每条链路都真的写入并读回。

### TC-4.3 Docker 未启动时的行为 — P1
- **操作**:关闭 Docker Desktop 后运行 `$SPROUT storage check`
- **预期**:失败的链路标 `[FAIL]` 并给出原因,**退出码 1**;不应静默通过。

### TC-4.4 JSON 输出的 `ok` 与退出码一致 — P1
- **操作**:`$SPROUT storage check --json > r.json; echo $?`
- **预期**:`r.json` 里的 `"ok"` 字段**必须**与 shell 退出码一致(0↔true)。设计上明确要求二者不可背离。

### TC-4.5 存储状态概览 — P1
- **操作**:`$SPROUT storage status`
- **预期**(实测):打印各存储件数,含 `tokenizer  trigram`、Memory 层 facts 数、knowledge/events/blobs/vectors 计数。

### TC-4.6 数据层计划 — P2
- **操作**:`$SPROUT storage plan` 与 `$SPROUT storage plan --json`
- **预期**:列出每个存储面的角色(authority / derived),说明 Milvus/Neo4j/Redis 是派生而非权威。

### TC-4.7 备份 — P0
- **操作**:`$SPROUT storage backup ./backup_test`
- **预期**:所有 SQLite 库被复制到目标目录;目标目录出现 `.db` 文件。

### TC-4.8 恢复 — P0
- **前置**:TC-4.7 的备份存在
- **操作**:
  ```bash
  $SPROUT db session-new --user t2      # 造一条新数据
  $SPROUT storage restore ./backup_test
  $SPROUT storage status                # 数据应回退到备份时点
  ```
- **预期**:恢复后数据与备份时点一致,无半截写入。

### TC-4.9 健康检查(轻量) — P2
- **操作**:`$SPROUT storage health` / `$SPROUT storage health --all`
- **预期**:报告各链路运行状态;`--all` 用本地默认 DSN 检查全部六条。

### TC-4.10 迁移 — P2
- **操作**:`$SPROUT storage migrate --help` 后按提示运行
- **预期**:显示待执行的 schema 变更;已是最新时应明确说"无需迁移"。

### TC-4.11 FTS 分词器迁移 — P1
- **目的**:验证历史库(`unicode61`)能平滑迁到 `trigram`,且**数据不丢**。
- **前置**:构造一个旧格式库(或使用既有历史库的副本)
- **操作**:打开该库触发runtime,然后 `$SPROUT storage status` 查 `tokenizer`
- **预期**:
  - tokenizer 变为 `trigram`
  - **轮次数不变**(迁移是无损的)
  - 中文子短语检索开始命中
- **回归点**:迁移失败时必须**保留原索引**并告警,不能把表删了。

---

## 5. 记忆层(MEMORY.md / USER.md)

### TC-5.1 记忆状态 — P0
- **操作**:`$SPROUT memory status`
- **预期**(实测):显示 `MEMORY.md` / `USER.md` 字符数、会话上限(默认 1400)、用户上限(默认 850)、会话文件数。

### TC-5.2 添加会话事实 — P0
- **操作**:`$SPROUT memory add --session <sid> --key name --value 小明`
- **预期**:输出 `ok`;再 `$SPROUT memory list --session <sid>` 能看到该条。

### TC-5.3 字符上限拒绝 — P0
- **操作**:添加一条超长 value(超过 1400 字符)
- **预期**:
  - 输出 `Rejected: <当前内容片段>…`
  - **退出码 2**
  - 原有内容**不被覆盖**

### TC-5.4 用户档案 — P1
- **操作**:
  ```bash
  $SPROUT memory add --user --key lang --value 中文
  $SPROUT memory list --user
  ```
- **预期**:写入 `USER.md` 并可列出,上限走 850 字符。

### TC-5.5 替换事实 — P1
- **操作**:`$SPROUT memory replace --old "小明" --key name --value 小红 --session <sid>`
- **预期**:子串匹配成功并**原地替换**;`list` 中旧值消失、新值出现。

### TC-5.6 删除事实 — P1
- **操作**:`$SPROUT memory remove --old "小红" --session <sid>`
- **预期**:该条被删除,其余条目保留。

### TC-5.7 匹配失败的处理 — P2
- **操作**:`$SPROUT memory replace --old "不存在的子串" ...`
- **预期**:明确告知未匹配,**不**静默新增或破坏原内容。

---

## 6. 项目管理与工作区

### TC-6.1 打开工作区 — P0
- **操作**:`$SPROUT project workspace .`
- **预期**:当前目录被登记,返回 workspace id(形如 `local-<hash>`)。

### TC-6.1b 聊天里的编码请求会先问工作区 — P0 🔑
- **目的**:在 chat 里说人话("帮我在根目录写一个 XX")时,**要么真的写,要么明说为什么不能**;
  不允许静默降级。
- **操作**:
  1. `$SPROUT chat`,直接输入 `帮我在当前项目的根目录下写一个冒泡排序的代码`(**不加** `/task`)
  2. 观察是否弹出"以 <cwd> 作为本次任务的工作区?"的问询
  3. 选"同意(本次任务)"
  4. `$SPROUT project changes <task_id>` 看变更提案
- **预期**:
  - 步骤 1 之后**不**继续对话,而是**停下问**;回复里说明"当前会话没有绑定工作区"这个原因
  - 问询之前:**没有**新工作区、**没有**新任务(问 ≠ 做)
  - 同意后才登记工作区并建任务;改动先落在 git 沙箱副本
  - 之后仍需过变更提案这道闸才能真正落到你的目录
- **反例(必须不发生)**:agent 回一句"我的工具集里没有能写文件的工具"就结束 —— 那正是修复前的
  行为:请求被识别成 task,却因为没有 `workspace_id` 掉进对话路径,而那条路径上的 agent
  **本来就没有写工具**(写工具只挂在 AGENT 节点上,只有任务被编译后才存在)。
- **回归点**:普通闲聊(如 `use the tool`)不能被这个问询打断 —— 问询除了分类器的 intent,
  还要求 `detect_task_hint` 在文本上给出确定性证据。
- **两条触发路径(都要覆盖)**:问询有两个入口,互为兜底。
  1. **runtime 的措辞闸**(agent 启动前):分类器判为 `task` **且** `detect_task_hint`
     在文本上命中关键词。便宜,能省一次模型往返,但它读的是**字面**,打错字就废。
  2. **agent 主动举手**(agent 启动后):对话路径的 agent 现在有 `request_workspace` 工具。
     它读的是**整轮对话**,所以措辞再怪也认得出;调用后runtime 照样 hold 住原指令。
- **必测的错字用例** `你能帮我在整个项目的根目录下写一一个冒泡排序的代码吗`:
  `写一一个` 不匹配任何 `TASK_KEYWORDS`,第 1 条路**必然不触发**(实测 `detect_task_hint` 为
  `False`,分类器也返回 `None`)。此时**必须**由第 2 条路兜住,弹出问询。
  这就是用户实际发来的那句话 —— 修复前它掉进对话路径,agent 只能说"我没有写工具",
  然后自己编了一套"请给我绝对路径"的话术(runtime**从不**要求绝对路径,
  `_request_workspace` 用的是 `Path.cwd()`)。
- **自动化**:`src/Sprout/tests/test_workspace_consent.py`(22 例,含上述错字用例的正反两面)。
- **任务挂起后必须回报(否则"我写完告诉你"是空话)**:后台任务脱离产生它的那一轮运行,
  chat 路径**观察不到**它停下。修复前:任务把文件写进了沙箱、停在审批上,然后**整个会话再没人被通知** ——
  用户反复追问"写好了吗",而系统这一侧根本没有能开口的地方。现在每轮结束(含同意/审批处理**之后**)
  会列出本会话仍在等待决定的任务,并给出**确切的下一步命令**:
  - 有待批变更提案 → `sprout project approve <proposal_id 前 8 位>`
  - 否则有 `task_id` 匹配的待批授权 → `sprout approvals approve <approval_id 前 8 位>`
  - 两者都没有 → 只报状态,不猜
  **两种 hold 的 id 与子命令都不同**(`WAITING_APPROVAL` 一个状态对应两种原因),所以
  `task_progress()` 是**看实际存在什么**来判定,而不是从状态反推。
  **只报告、绝不自动决断**:停车本身就是安全属性,一个顺手把问题解决掉的提示会把这个闸门作废。
  配套修复:`_handle_task` 原先取 `message.channel` 记 `source`,而同意是从 `channel="internal"`
  的内部消息恢复的 → `coerce_source("internal")` 无别名 → 每个经同意创建的任务都被记成
  `unknown`(而 `unknown` 恰好也是"没看出来"的取值,记录因此失去意义)。改为优先取
  `origin_channel`。同时任务落库时记 `session_id`,否则挂起的任务不属于任何会话,回报无从匹配。
- **自动化(回报链路)**:同文件的 `test_a_consented_task_is_filed_under_the_surface_it_came_from`、
  `test_a_task_queued_from_chat_can_be_reported_back_to_it`、`test_parked_tasks_are_found_by_the_session_that_asked`、
  `test_settled_tasks_are_not_reported_as_waiting`、`test_a_parked_task_points_at_the_approval_that_unblocks_it`、
  `test_a_change_proposal_takes_precedence_over_an_approval`、
  `test_the_reporter_names_the_exact_command_and_decides_nothing`、
  `test_the_reporter_stays_quiet_when_nothing_is_parked`。

### TC-6.2 列出工作区 — P0
- **操作**:`$SPROUT project workspaces`
- **预期**:以 `id  kind  root` 三列列出所有已登记工作区。

### TC-6.3 分析工作区 — P0
- **操作**:`$SPROUT project analyze <workspace>`
- **预期**:扫描代码库,把项目知识落库;输出的统计(文件数/符号数)与仓库规模量级相符。

### TC-6.4 符号清单 — P0
- **操作**:`$SPROUT project symbols <workspace>`
- **预期**:列出类/函数/方法/测试符号。抽查若干条与源码实际相符。

### TC-6.5 依赖追踪 — P1
- **操作**:`$SPROUT project dependencies <workspace> <path/to/file.py>`
- **预期**:给出该文件的出边依赖;应有反向查询能力(谁依赖它)。

### TC-6.6 子图遍历 — P2
- **操作**:`$SPROUT project subgraph <workspace> <node>`
- **预期**:返回该节点邻域,受深度/数量上限约束。

### TC-6.7 项目知识查询 — P1
- **操作**:`$SPROUT project knowledge <workspace>`(可带查询词)
- **预期**:返回已落库的知识条目,只读。

### TC-6.8 读取计划 — P2
- **操作**:`$SPROUT project readplan <task>`
- **预期**:给出受边界约束的读取计划(不无限膨胀)。

### TC-6.9 任务与变更提案全流程 — P1 🔑
- **操作**:
  ```bash
  $SPROUT project task-create <workspace> "<任务描述>"
  $SPROUT project task-run <task_id>
  $SPROUT project changes <task_id>
  $SPROUT project show <proposal_id>
  $SPROUT project approve <proposal_id>
  $SPROUT project apply <proposal_id>
  $SPROUT project rollback <proposal_id>
  ```
- **预期**:任务创建→执行→产生变更提案→查看 diff→**人工批准**→应用→可回滚。
- **重点**:提案在批准前**不得**自动落地;`apply` 只对已批准提案有效;`rollback` 之后文件回到应用前状态。
- **两道闸,别混淆**:跑 `task-run` 时任务会先停在**验证授权**(`approvals list` 里的 `process_run`),
  批准它之后**才会**产生变更提案,任务再停在提案上,需要 `project approve <proposal_id>`。
  两处的 id 不能混用:`approvals approve` 收审批 id,`project approve` 收提案 id。
- **⚠️ 曾经的坑(已修)—— `__pycache__` 混进提案**:
  验证是在 sandbox worktree **里面**跑的,会写下 `__pycache__` / `.pytest_cache`。
  `git status` 把它们当成"任务改动的文件",于是提案里**大部分是字节码**。
  在**没有 `.gitignore`** 的仓库里(也就是最可能被拿来测试的那种),后果不止是难看:
  `.pyc` 是二进制,`git apply` 对二进制 hunk 会失败,导致**整个提案无法 apply** ——
  任务跑完显示 `failed`,而真正的原因和它改的代码毫无关系。
  现在 `GitWorktreeSandbox` 在 `diff` / `changed_files` 里用 git pathspec 把它们排除掉了
  (`_SANDBOX_EXCLUDES`),不再依赖仓库自己写好 `.gitignore`。
- **验证修复**:用一个**没有** `.gitignore` 的仓库跑上面的全流程,检查
  `project show <proposal_id>` 的 `Files:` 只列出 agent 真正改的文件。

### TC-6.10 `sandbox_apply_patch` 的上下文定位 — P1 🔑

参考实现:OpenAI Codex 的 `codex-rs/apply-patch`(Rust;其 `seek_sequence.rs`)。
其**格式**与我们不同(它用自有的 `*** Begin Patch` 标记语法,我们解析标准 unified diff),
但**定位策略**值得移植 —— 本用例测的就是这一层。

- **背景**:旧实现要求 context **逐字节相等**,不相等即 `PatchError`,整个 tool call 失败。
  但模型凭记忆写 patch 时,**语义**可靠、**空白**不可靠:它看不见行尾空格,会把排版破折号
  写成 ASCII 连字符(文件里是 `–` / `—`,patch 里是 `-`)。于是这类 patch 全部硬失败。
- **现在**:定位分四档升级 —— 精确 → 忽略行尾空白 → 完全 trim → **Unicode 标点折叠**。
  但**升级 ≠ 猜测**,两条护栏必须成立:
  1. **折标点那一档只作用于「文件自己指认」的位置**:`@@` 的行号若能折出匹配就用它;
     否则全文件只有**唯一**匹配时才接受;否则**拒绝**。
     (对照用例:文件里 `# a – b` 与 `# a — b` 折完一样、行号又对不上 → 必须报错,
     不能在两者中挑一个写进用户的文件。)
  2. **context 行写回的是文件自己的那一行,不是 patch 里的副本。**
     否则一个空白有损的 patch 会顺手改掉它根本没打算改的行 —— 这正是当初严格比较想防的破坏。
- **实测口径**:
  - 行尾空格 / 缩进被重排 → 能应用
  - 文件含 `–`,patch 写 `-` → 能应用
  - 行号写错(如 hunk 实际在第 4 行却写 `@@ -1`)→ 按 context 找到,**不**因为行号不符而拒绝
  - 折标点后**两个**候选、行号又不指认任一个 → **拒绝**(必须)
  - 只有折标点会歧义、而「忽略尾空白」能唯一确定时 → 取较松的那档成功(见下条:档位顺序有意义)
  - context 行的空白 → 保留**文件**的
- **档位顺序是有意义的,不能把折标点提到前面**:文件里一行是 `–`、另一行是 `-`(带行尾空格),
  patch 写 ASCII `-`。忽略尾空白后唯一命中第二行 → 成功;但折标点看两行等价 → 歧义 → 拒绝。
  把折标点提前会**误拒一个本来不歧义**的 patch。
- **顺带修正**:多 hunk 的 offset 改由 **ops 实际增删行数**推出,不再取 `@@ -a,b +c,d @@` 的头部计数 ——
  模型数错了头,旧实现会把后面每个 hunk 一起带偏。
- **自动化**:`src/Sprout/tests/test_patch.py`(17 例)。三组消融均能咬住:
  关掉空白档 → 1 失败;折标点改为「挑第一个候选」→ 1 失败;context 行改用 patch 的副本 → 1 失败。

---

## 7. 安全、审计与审批

### TC-7.1 安全态势检查 — P0
- **操作**:`$SPROUT security check`
- **预期**:
  - 分平面(Plane)渲染发现项,每条标注来源:`live` / `structure` / `residual`
  - 有开放控制项时**退出码 1**,全绿时 0
  - `--strict` 时 warning 也算失败
- **实测**:本机当前报告 `1 control(s) are open: V14`(审计链断裂),退出码 1 —— 见下一条。

### TC-7.2 审计链完整性 — P0(根因已查明)
- **操作**:`$SPROUT audit verify`
- **预期(健康态)**:`chain intact (N entries)`,退出码 0
- **实测当前**:`1 line(s) are not audit entries: line 0`,**退出码 1**

**根因(已查明,2026-09-24)**:本机审计流 `~/.sprout/data/audit/security.jsonl` 第 0 行是一条**与审计无关的 JSON 行**,只有一个键:`{"probe": <int>}` —— 没有 `kind`、没有 `ts`、没有 `hash`、没有 `prev_hash`。**链本身没有断**:

```
存在条目:4364 行(第 0 行是异物,第 1–4363 行是正常策略决策条目)
line1 prev_hash == GENESIS: True
从第 1 行起链式自洽:4363 / 4363
```

排除项:
- **不是篡改**:4363 条从创世起逐条校验全部通过;任何中段编辑都会当场暴露。
- **不是并发写入分叉**:`_append` 在 `self._lock` 外还持有 `_append_guard()` 的 OS 锁,且 `_tail_hash()` 每次从磁盘重读尾块(非缓存),写失败降级到 `.fallback` 而非另起一条链 —— 这条路径就是按"绝不分叉"设计的(`test_audit_chain_survives_separate_processes` 已覆盖)。
- **不是常量漂移**:`GENESIS_HASH = "0"*64` 自 `e815706` 建文件起未变。
- 最可能是一条手工/调试写入(`"probe": <int>` 不是任何代码路径的产物;`src/Sprout/security/` 下没有产生无 `kind` 条目的写入点)。

**原诊断错在哪(已修)**:旧 `verify_chain` 把"缺字段的行"和"哈希链断裂"报成同一种失败,于是指着 `entry 0` 说 `prev_hash mismatch` —— 病因被指错了,TC-7.2 和 KB-4 都因此记成了"链断了"。现在两者分开:`foreign` 行单独归类,不冒充断裂。

- **本机剩余动作(未做,需你决定)**:那行 `{"probe": ...}` 仍在你的活动审计流里,`verify` 会继续以退出码 1 报告它。删掉该行即恢复 `chain intact`。这是删除不可逆的实时安全数据,我没有动。

### TC-7.2b 异物行 ≠ 断裂(回归) — P1
- **目的**:锁住本次修复,防止"非条目行"重新被报成断裂。
- **操作**(在**副本**上做):
  1. 在流的第 0 行前插入 `{"probe": 1}`
  2. `$SPROUT audit verify`
- **预期**:报 `1 line(s) are not audit entries: line 0`,**不报** `chain broken at entry N`;退出码仍为 1(有问题行就不能算"完整校验通过")。
- **半写条目仍算断裂**:插入一条 `{"kind": "policy.decision"}`(缺 `hash`/`prev_hash`)必须报 `chain broken at entry N`,且 `foreign` 为空 —— 它自称是条目,就要按条目被追究。
- **自动化**:`test_audit_reports_a_stray_line_as_foreign_not_as_a_break`、`test_audit_verifies_entries_around_a_stray_line`、`test_audit_treats_a_half_written_entry_as_a_break`。

### TC-7.3 审计流浏览 — P1
- **操作**:`$SPROUT audit tail -n 20` / `--kind <event>` / `--json`
- **预期**:按时间倒序打印条目;`--kind` 过滤生效;`--json` 每行一条合法 JSON。

### TC-7.4 审计聚合报告 — P1
- **操作**:`$SPROUT audit report`
- **预期**:按 actor / action / decision / matched_rules 聚合计数,并给出 denials 总数。

### TC-7.5 篡改检测(对抗用例) — P0
- **目的**:证明哈希链真的能发现篡改。
- **操作**(在**副本**上做,勿动生产库):
  1. 备份审计文件
  2. 手工编辑中间某行的一个字段
  3. `$SPROUT audit verify`
- **预期**:精确定位到被改的那一行并报 `chain broken at entry N`,退出码 1。
- **恢复**:用副本覆盖回去。
- **注意**:自 2026-09-24 起,`verify` 区分"断裂"与"异物行"。编辑字段必须报 `chain broken at entry N`(`broken_at` 非空、`foreign` 为空);若报的是"not audit entries",说明改坏了行的结构而非字段内容。

### TC-7.6 审批列表 — P0
- **操作**:`$SPROUT approvals list`
- **预期**:列为空时显示 `0 record(s)` + `nothing to show`;有记录时 **pending 排在最前**。

### TC-7.7 触发一个待审批并处理 — P0 🔑
- **目的**:打通"agent 请求 → 人工批准 → 继续执行"的闭环。
- **操作**:
  1. 让 agent 做一件需要审批的事(如 `git_write` / 写文件 / 执行进程)
  2. `$SPROUT approvals list` 找到 pending 记录
  3. `$SPROUT approvals approve <id>`
- **预期**:
  - 步骤 2 出现待批记录,含动作、参数、来源
  - 批准后任务**继续**而不是重新请求审批(单次授权被消费)
  - 若改参数重试,应**重新**要求审批(指纹变化)
- **⚠️ 曾经的坑(已修)**:`approve` 的 `--resume` 默认是**关**的,所以批准只写了一条决定、
  **不唤醒**停在 `waiting_approval` 的任务。更糟的是 `ApprovalManager.decide` 拒绝对非 PENDING
  记录再决策,所以已经批过的记录**没法重批** —— 操作者回答了自己被问的问题,却没有任何入口
  去兑现这个回答。当时正确的补救是 `project task-run <task_id>` 重跑,而不是
  `approvals resume`。
- **不要这样做**:`approvals resume <id>` 是**错的**。`resume` 接收的是**会话 id**
  (chat 会话),不是审批 id;传审批 id 会得到
  `LookupError: No pending approval found for session '<approval_id>'`。
- **现在的行为**:`approve` 默认就唤醒任务(`--resume/--no-resume`,默认 `resume`),
  并把任务落到的新状态打印出来。没有 registry / 没有 runtime 的场景用 `--no-resume` 只写决定。
- **仍要注意**:批准验证授权后,任务会**在此流程的第二道闸**再次停下 —— 停在变更提案
  (change proposal)上。这是**设计如此**(两层授权是刻意不同的指纹),不是缺陷:
  接下来要 `project approve <proposal_id>`。

### TC-7.8 拒绝审批 — P1
- **操作**:`$SPROUT approvals reject <id>`
- **预期**:记录状态变为 rejected,**不**执行对应动作。

### TC-7.9 过期清理 — P2
- **操作**:`$SPROUT approvals sweep`
- **预期**:陈旧的 PENDING 变为 EXPIRED,使任务可重试;不误伤新记录。

### TC-7.10 白名单建议 — P2
- **操作**:`$SPROUT approvals suggest`(只读),再 `--apply`
- **预期**:从审批历史推导可加入白名单的命令;默认**只读**不改配置,`--apply` 才写。

### TC-7.11 危险动作默认拒绝 — P0
- **验证点**(对照策略矩阵):
  - `file.write` 到普通文件 → 允许;到敏感路径 → 需审批/拒绝
  - `process.run` → **需审批**(除非在 operator 的 auto-run 名单上)
  - `secret.use` → **需审批**
  - `network.post` → **需审批**;`network.get` → 允许
  - `git.commit` / `git.push` → **需审批**
  - `db.write` → **仅沙箱**
- **操作**:构造上述请求,用 `$SPROUT audit tail` 反查 decision 与 matched_rules 是否为 `matrix:*`。

### TC-7.12 SSRF 防护 — P1
- **操作**:让 agent 向 `http://127.0.0.1:8000` 或 `http://169.254.169.254` 发起请求
- **预期**:私网/环回地址被拒。
- **已知残留**:DNS rebinding(TTL-0)仍可绕过,这是记录在案的残余风险,需前置代理。

### TC-7.13 Git 子进程环境净化 — P2
- **操作**:设置一个假的 `GIT_ASKPASS`/API key 后触发 git 操作
- **预期**:敏感变量被剥离,`GIT_TERMINAL_PROMPT=0` 等非交互项存在,`fsmonitor`/`pager` 被覆盖(仓库无法让 git 执行任意命令)。

---

## 8. 技能系统(Skills)

### TC-8.1 列出技能 — P0
- **操作**:`$SPROUT skills list`
- **预期**:空时提示 `No skills indexed. Run \`sprout skills index --rebuild\` to scan the directory.`

### TC-8.2 重建索引 — P0
- **操作**:`$SPROUT skills index --rebuild`
- **预期**:
  - 打印索引技能数与目标路径
  - 有 registry 时**对账**并报告分歧:
    - `missing`(注册表有、磁盘无)→ 报错行,说明"保留在注册表、从快照移除"
    - `unregistered`(磁盘有、注册表无)→ 警告行,说明"以 untrusted 加载、不进提示词"
  - 用 `--dir` 指向独立目录时,退化为纯磁盘扫描并**明确说明**没有 registry

### TC-8.3 信任降级缺陷(回归用例,已修) — P0
- **目的**:验证 `index --rebuild` **不会**把已批准的技能洗成 untrusted。
- **前置**:有一个已批准、已安装的技能(如 `skills install <name>` 后出现 `trust=trusted`)
- **操作**:
  ```bash
  $SPROUT skills list                       # 记录 trust 值
  $SPROUT skills index --rebuild
  $SPROUT skills list                       # 再看 trust 值
  ```
- **预期**:trust 保持 `trusted`
- **⚠️ 曾经的坑(已修)**:快照是从**磁盘扫描**重建的,而加载器对 `.fetched/` / `.evolved/`
  下的东西**一律**标 untrusted(信任是注册表的决定,扫描不可能知道)。扫描的这个"占位判断"
  被写进了 index.json,而 index.json 正是 runtime**恢复信任所依据的权威** —— 于是
  `skills index --rebuild` 静默**撤销**了操作者对每个下载/进化技能的批准,它们从提示词里
  消失,且没有任何报错。
- **影响面(当时实测)**:
  - `skills forget <x>` 会连带把**其他无关技能**也降级
  - 增长流水线刚发布的 `.evolved/` 技能,一次 rebuild 后就掉出提示词
- **修复方式**:`reconcile` 手里有注册表,所以由它把记录在案的 `(trust, digest)` 原样带过去
  (`_carry_approval`),而不是采用磁盘扫描的判断。内容比对仍然只发生在**一处** ——
  runtime 的 `_restore_trust` 会用记录的 digest 和磁盘上的技能核对,被改过的技能在那里降级。
- **边界(应同时验证)**:
  - 注册表里 `trust=untrusted` 的技能,rebuild 后**仍然** untrusted(修复不是"一律放行")
  - 批准之后**又改过内容**的技能,rebuild 后应**降级**(批准不能漂移到没批过的字节上)
  - 无注册表的 `--dir` 独立目录,退化为纯磁盘扫描(那里本来就没有"批准"这回事)
- **对应自动化测试**:`src/Sprout/tests/test_skills_reconcile.py`

### TC-8.4 `skills list` 的 MISSING 标记 — P1
- **操作**:手工删除某个已安装技能的目录,再 `$SPROUT skills list`
- **预期**:该行标为 `[missing]` 并打印**消失的路径**;结尾给出 `index --rebuild` 与 `skills forget` 两条指引。

### TC-8.5 从目录导入 — P0
- **操作**:
  ```bash
  mkdir -p /tmp/impsrc/writing/docs
  cat > /tmp/impsrc/writing/docs/SKILL.md <<'EOF'
  ---
  name: docs
  description: Write documentation
  ---
  Always write clear docs.
  EOF
  $SPROUT skills import /tmp/impsrc --dry-run
  $SPROUT skills import /tmp/impsrc
  ```
- **预期**:
  - `--dry-run` 列出将导入的技能,**不写任何文件**
  - 正式导入后 `skills list` 出现 `docs`
  - 嵌套布局(`writing/docs/SKILL.md`)能被发现,且**不会**继续走进技能内部把 `assets/SKILL.md` 当第二个技能

### TC-8.6 导入的边界 — P1
- **验证点**:
  - `node_modules` / `.git` / `.venv` 被跳过
  - `.fetched` / `.evolved` / `.quarantine` / `.hub` 被跳过(不去重新导入自己装的)
  - 目的地被排除(`import .` 不会把刚写进去的又扫出来)
  - 上限:深度 8 层、最多 500 个技能
  - **已知缺口**:超过 500 时**静默截断**,不告警 —— 建议记录为改进项

### TC-8.7 导入的重复处理 — P1
- **操作**:同一目录导入两次;再加 `--force` 导入第三次
- **预期**:
  - 第二次:同名被**跳过**,提示 `already installed (use --force to replace)`
  - 第三次:**原地替换**,不产生 `docs-<digest>` 版本堆积

### TC-8.8 替换不误删同名前缀技能(回归) — P0
- **操作**:同时存在 `pdf` 与 `pdf.v1` 两个技能,对 `pdf.v1` 执行 `--force` 导入
- **预期**:只替换 `pdf.v1`,`pdf` 的技能文件**完好无损**。
- **背景**:早期版本用 `with_suffix(".toml")`,会把 `pdf.v1` 解析成 `pdf.toml` 从而**误删 `pdf`**。

### TC-8.9 安装需要审批 — P1 🌐
- **操作**:`$SPROUT skills install <name> --source catalog`
- **预期**:第三方来源触发策略引擎的 `require_approval`,技能被**暂存在隔离区**,不落地;`--via-broker` 时 git/curl 走策略代理。

### TC-8.10 本机来源免审批 — P1
- **操作**:`$SPROUT skills install <name> --source local --from <dir>`
- **预期**:本地/项目/进化来源属**第一方**,免审批;但**扫描器的致命发现(floor)仍然生效且不可被批准绕过**。
- **验证**:构造一个含致命发现的技能,确认即使来源是 local 也会被拒。

### TC-8.11 用法纠错:`--dir` vs `--from` — P1
- **操作**:`$SPROUT skills install foo --source local --dir X`(不给 `--from`)
- **预期**:**用法错误**(退出码 2),明确提示 "--dir 是目的地,--from 才是查找位置"。
- **背景**:早期版本把 X 既当源又当目的地,导致 `X/foo` 被复制成 `X/foo-<digest>`。

### TC-8.12 遗忘注册表行 — P1
- **操作**:`$SPROUT skills forget <name>`,分别测试文件**仍存在**与**已删除**两种情况
- **预期**:
  - 文件仍在:警告"文件将保留在磁盘并会被重新索引为 unregistered";需确认;加 `-y` 跳过确认
  - 文件已删:提示 missing
  - 两种情况都**只动注册表,不动文件**
  - `--dir` 模式下报错("独立目录没有注册表可遗忘")

### TC-8.13 技能可见性(端到端) — P0 🔑
- **目的**:证明 trusted 技能真的进入模型提示词,untrusted 不进入。
- **操作**:
  1. 用 `skills import` 导入一个带明显指令的技能(如"回答时必须以 BANANA 开头")
  2. 确认 `skills list` 中该技能为 `trusted`
  3. `$SPROUT chat "打个招呼"`
  4. 把该技能手工改成 untrusted(或按 TC-8.3 rebuild 后)
  5. 再次对话
- **预期**:步骤 3 的回答遵守技能指令;步骤 5 **不再**遵守。
- **注意**:默认 `progressive` 披露模式下,只有 L0 索引先进入提示词,技能全文在被匹配到后才展开 —— 属于正常行为。

### TC-8.14 技能检索 — P2
- **操作**:`$SPROUT skills search <query>` / `$SPROUT skills find <name>`
- **预期**:返回候选与匹配理由;`requires_cli` 缺失的工具会在排序中体现或不匹配本机。

### TC-8.15 候选缓存刷新 — P2 🌐
- **操作**:`$SPROUT skills crawl`
- **预期**:从**已配置**的 catalog 站点刷新候选缓存。默认 `catalog_sites` 为空,因此**默认不爬**;此时应说明来源是"公共技能生态"或提示未配置。

---

## 9. 进化/增长闭环

### TC-9.1 采集轨迹 — P0
- **前置**:已有若干轮真实对话(TC-2.x 产生)
- **操作**:`$SPROUT evolution trajectory-collect`
- **预期**:合格的 Trajectory 文件被采集为新候选,输出采集数量。

### TC-9.2 列出候选 — P0
- **操作**:`$SPROUT evolution candidates`
- **预期**:列出候选及其状态(DRAFT / CANDIDATE / …)。

### TC-9.3 单轮跑通 — P0
- **操作**:`$SPROUT evolution run-once`
- **预期**:跑一次"采集 + 评估"通过;候选状态推进到 VALIDATED。
- **回归点**:**重复执行**应保持有界,不重复铸造相同产物。
  ```bash
  for i in 1 2 3; do $SPROUT evolution run-once; done
  ```
  预期候选数不随轮次线性膨胀。

### TC-9.4 统一流水线 — P0
- **操作**:`$SPROUT evolution unified-run`
- **预期**:等价于 `collect + evaluate` 的组合,行为与 TC-9.3 一致。

### TC-9.5 硬门与效用评分 — P1
- **操作**:`$SPROUT evolution evaluate-candidates`
- **预期**:候选经硬门(hard gates)+ 效用打分;**未通过硬门的不得进入 VALIDATED**。

### TC-9.6 人工批准 — P0
- **操作**:`$SPROUT evolution approve-candidate <id>`
- **预期**:
  - 只有 VALIDATED 的候选可批准
  - 批准后状态推进到 PUBLISHED,产物落到 `.evolved/`
  - **重点**:流水线本身**止步于 VALIDATED**,发布始终是人工决定

### TC-9.7 拒绝 — P1
- **操作**:`$SPROUT evolution reject-candidate <id>`
- **预期**:状态变为 REJECTED,不发布。

### TC-9.8 合并旧版本 — P2
- **操作**:`$SPROUT evolution consolidate`
- **预期**:同名旧版本产物被置为 DEPRECATED,保留最新。
- **回归点**:不应把刚 PUBLISHED 的那个自己给弃用了。**幂等性**:连续跑两次不产生重复。

### TC-9.9 状态推进 — P2
- **操作**:`$SPROUT evolution maintain`
- **预期**:陈旧的 MONITORING / STABLE 产物按时间推进状态。

### TC-9.10 定时调度 — P2
- **操作**:`$SPROUT evolution schedule`
- **预期**:注册周期性采集+评估。**注意**:这是 CLI 守护方式;就目前代码,Temporal 路径下的增长工作流**从未被启动过**(registered but inert)。

### TC-9.11 事件驱动触发 — P1
- **操作**:在对话中说出请求进化的意图(如"学习一下刚才的经验,进化一下")
- **预期**:意图路由器发布 `INTENT_EVOLUTION_REQUESTED`,后台**真的**跑一次增长扫描。
- **背景**:修复前这个意图是**死胡同** —— 事件发布了但没有任何非测试订阅者。这是回归用例。

### TC-9.12 学到的知识回流到下一个任务 — P1 🔑
- **目的**:验证"生长闭环"真的闭合 —— 学到的东西进入后续任务的提示词。
- **操作**:
  1. 跑一轮增长并批准发布某个技能
  2. 新开一个会话,提一个**应当**命中该技能的任务
  3. 观察回答是否体现该技能
- **预期**:技能出现在后续任务的上下文中。
- **⚠️ 曾经的关联缺陷(已修)**:见 TC-8.3 —— 以前任何 `index --rebuild` 都会把它降级,
  从而**打断闭环**。现在 `reconcile` 会带上注册表里的批准决定,重建不再撤销批准。

---

## 10. MCP

### TC-10.1 检查 MCP 服务面 — P0
- **操作**:`$SPROUT mcp inspect`
- **预期**:列出 tools 与 prompts,含 `sprout_chat`、`sprout_skill_review`、`workspace_scan_prompt`、`task_execute_prompt`、`approval_review_prompt`;末尾提示用 `sprout mcp serve` 以 stdio 启动。

### TC-10.2 以 stdio 启动 — P1
- **操作**:`$SPROUT mcp serve`
- **预期**:进入 stdio 服务模式(无 TTY 输出污染 stdout)。

### TC-10.3 MCP 权限边界(关键安全点) — P0
- **验证点**:
  - MCP **只能发起**请求,永远**不能批准**
  - `sprout_chat` 走与 CLI 相同的策略引擎与审批流程
  - 受信主体的判定不可被客户端伪造

---

## 11. Web 控制台

### TC-11.1 构建前端 — P0
- **前置**:`web/frontend/dist` 不存在(当前实测就是如此)
- **操作**:
  ```bash
  cd web/frontend && npm install && npm run build && cd ../..
  ```
- **预期**:生成 `web/frontend/dist`。

### TC-11.2 启动控制台 — P0
- **操作**:在**仓库根目录**执行 `$SPROUT serve`
- **预期**:
  ```
  SEAM_Sprout Web
    host 127.0.0.1
    port 8000
    static dir .../web/frontend/dist
    API HTTP + WebSocket
  ```
  - 浏览器打开 `http://127.0.0.1:8000` 看到界面
  - **注意**:不在仓库根目录运行会报 `web/webapi not found`

### TC-11.3 Chat 视图 — P0 🔑
- **操作**:在 Web 界面发一条消息
- **预期**:消息发送、流式返回、历史可回看(`POST /api/chat`、`POST /api/chat/stream`、`GET /api/sessions/{id}/history`)。

### TC-11.4 WebSocket — P1
- **操作**:连接 `ws://127.0.0.1:8000/ws/chat`
- **预期**:双向通信正常,断线有恢复或明确提示。

### TC-11.5 任务板 — P0
- **操作**:在 Board / TaskManager 视图创建、拖拽、修改、删除任务
- **预期**:对应 `GET/POST /api/tasks`、`PATCH/DELETE /api/tasks/{id}` 全部生效,刷新后状态保持。

### TC-11.6 设置视图 — P1
- **操作**:打开 Settings 视图(`GET /api/settings`),并修改偏好(`PUT /api/preferences`)
- **预期**:
  - 设置**脱敏**返回(DSN 密码被掩掉)
  - 修改后持久化
- **安全点**:即使 web auth 关闭,掩码也必须生效

### TC-11.7 存储视图 — P1
- **操作**:打开 Storage 视图
- **预期**:`GET /api/storage/status`、`/api/storage/plan`、`/api/storage/graph/status`、`/api/storage/vectors/count` 数据正确呈现。

### TC-11.8 Tokens / Logs 视图 — P2
- **操作**:打开对应视图
- **预期**:`GET /api/tokens` 显示用量;`GET /api/logs` 显示日志。

### TC-11.9 健康端点 — P1
- **操作**:`curl http://127.0.0.1:8000/api/health`
- **预期**:返回健康 JSON,HTTP 200。

### TC-11.10 Web 审批 — P1
- **操作**:在 Web 上对一个待审批项点击批准
- **预期**:`decided_by` 取自**已认证的调用者**,不是请求体里的字段(防伪造)。

### TC-11.11 停止服务 — P1
- **操作**:`$SPROUT stop serve`
- **预期**:占用 8000 端口的进程被终止;再访问端口应连接失败。

---

## 12. 外部消息通道(网关) 👤

> 以下都需要外部平台账号,**无法离线完整验证**。至少要验证"未配置时的报错是否清晰"。

### TC-12.1 配置向导 — P1 👤
- **操作**:`$SPROUT gateway setup --channel <feishu|weixin>`
- **预期**:进入交互式配置(飞书走扫码/手工;微信走 ilink 账号);凭据落盘而非写进 toml 明文。

### TC-12.2 未配置时启动网关 — P1
- **操作**:`$SPROUT gateway run`
- **预期**:给出**可读**的错误,指明缺哪个配置项,而不是崩溃。

### TC-12.3 飞书通道 — P2 👤
- **操作**:配置后 `$SPROUT gateway run`,在飞书里给机器人发消息
- **预期**:消息进入 Sprout runtime,回复回到飞书;工作区按 `workspace_by_channel` / `workspace_by_user` 路由。

### TC-12.4 微信通道 — P2 👤
- **操作**:同上,走 Weixin ilink 通道
- **预期**:消息收发正常,账号状态持久化。

### TC-12.5 通道隔离 — P1
- **验证点**:不同通道/不同用户的消息**不串会话**;映射到不同工作区时上下文互不污染。

---

## 13. 编排(Temporal)

### TC-13.1 环境诊断 — P1 🐳
- **操作**:`$SPROUT orchestrator doctor`
- **预期**(实测):
  ```
  Temporal 状态
    Host: 127.0.0.1:7233
    可达: 是
    服务器版本: 1.26.2
    命名空间: default 存在
    任务队列: sprout-tasks worker 数量=1
  ```
  - 未启动时应明确报告不可达

### TC-13.2 运行 worker — P1 🐳
- **操作**:`$SPROUT orchestrator worker`
- **预期**:worker 启动并轮询 `sprout-tasks`。

### TC-13.3 ⚠️ 工作流是否真的生效 — P1
- **验证点(已知设计问题)**:
  - `SproutTaskWorkflow` 在**生产任务队列**上是个 **no-op 存根**,真正干活的是消费同一队列的普通 worker
  - `SproutGrowthWorkflow` 已注册但**没有任何 `start_workflow` 调用点**
- **操作**:启动 worker 后发起一个任务,观察是否走了 Temporal 工作流
- **预期观察**:任务被处理,但**不是**通过那个工作流定义。把这作为设计确认项而非功能缺陷记录。

---

## 14. 远程 RPC 接口

### TC-14.1 连接远程服务 — P2 🌐
- **操作**:`$SPROUT remote workspace-list --url <url> --token <token>`
- **预期**:列出远程 SEMA 工作区;未配置/不可达时给明确错误。

### TC-14.2 远程任务流 — P2 🌐
- **操作**:`remote task-create` → `task-run` → `task-changes` → `proposal-show` → `proposal-approve` → `proposal-apply` → `proposal-rollback`
- **预期**:与本地 `project` 流程语义一致,全部经 RPC。

### TC-14.3 远程轨迹查询 — P2 🌐
- **操作**:`$SPROUT remote trajectory-query`
- **预期**:返回轨迹数据。

---

## 15. 自动化测试套件(必跑)

### TC-15.1 全量测试 — P0
```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  --basetemp=.pytest_tmp -p no:cacheprovider
```
- **预期**:`1131 passed, 11 skipped`
- **必须**带 `--basetemp`(见 KB-1)。**注意**:pytest 会在开跑时**整棵删掉** basetemp 目录 —— 数据库备份之类的长期产物**不能**放在 `.pytest_tmp/` 下(已踩过,见 KB-7)。
- **注意**:不传路径时 `testpaths` 会同时收 `src/Sprout/tests` 与 `web/tests`。`collect-only` 实测:后端 `src/Sprout` 收 1116 条,前端 `web/tests` 收 26 条 —— 只跑后端就会少前端那 26 条。
- **注意**:`ruff check src web` 在本次改动前后**都是 11 条 `UP038`**(全在我未触碰的文件里);本次改动的文件单独跑 `ruff check` 为 `All checks passed`。不要把这 11 条当成回归。

### TC-15.2 仅后端 / 仅前端 — P1
```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest src/Sprout \
  --basetemp=.pytest_tmp -p no:cacheprovider
PYTHONPATH=src .venv/Scripts/python.exe -m pytest web/tests \
  --basetemp=.pytest_tmp -p no:cacheprovider
```

### TC-15.3 代码规范 — P0
```bash
.venv/Scripts/python.exe -m ruff check src web
```
- **预期**:`All checks passed!`

### TC-15.4 手工交互脚本 — P2 🔑
- **操作**:
  ```bash
  PYTHONPATH=src .venv/Scripts/python.exe -m Sprout.tests.interactive_test        # 需求策略流水线
  PYTHONPATH=src .venv/Scripts/python.exe src/Sprout/tests/intent_recognition_repl.py  # 意图识别 REPL
  ```
- **预期**:按提示输入即可交互;这两支是**刻意排除在 pytest 之外**的(避免自动测试卡在输入上)。

---

## 16. 任务取消

### TC-16.1 取消停驻/运行中的任务 — P1
```bash
# 先看有哪些没结束的任务
PYTHONPATH=src .venv/Scripts/python.exe -m Sprout project task-cancel --help
# 取消(前缀即可)
PYTHONPATH=src .venv/Scripts/python.exe -m Sprout project task-cancel <task_id 前 8 位> \
  --reason "本地验证,不需要了"
```
- **预期**:打印 `cancelled <完整 id>` 与 `status  cancelled`
- **要点**:任务**行不会被删** —— `sprout project changes <task_id>` 仍能列出它的提案,审计记录也仍在。这是刻意的:行被删掉,引用它的节点/提案/审批记录就全成了孤儿。
- **边界(实测)**:
  - 重复取消同一个任务 → `Invalid value: Task ... is cancelled; it cannot be cancelled`(不报假的成功)
  - 前缀命中多个任务 → `Task prefix ... matches N tasks`(**拒绝而非猜测**)
  - 未知 id → `Invalid value: Task not found: ...`
  - `FAILED` 的任务**可以**取消(状态机给了它出边 `RETRYING`,属于"已结束"而非"已闭合");`COMPLETED` / `CANCELLED` / `ROLLED_BACK` **拒绝** —— 覆盖它们等于改写实际发生过什么
- **注意**:`sprout approvals reject` **不是**取消任务的出口 —— 拒绝后任务照样停在 `waiting_approval`(见 B.1 第 11 条)

### TC-16.2 取消后待批审批的处理 — P2
- **操作**:取消一个停在 `waiting_approval` 的任务后,跑 `sprout approvals list`
- **预期**:该任务对应的 pending 审批是**独立状态**,取消任务不会自动结掉它。过期后 `decide` 会把它标成 `EXPIRED`(不是 `REJECTED`),这是 `_apply_decision` 的正确行为;要留明确痕迹就显式 `sprout approvals reject <id> --reason "..."`

---

## 附录 A:优先级汇总

| 优先级 | 用例 |
|---|---|
| **P0(必测)** | 1.1 1.2 1.3 2.1 2.3 3.1 3.2 3.3 3.5 4.1 4.2 4.7 4.8 5.1 5.2 5.3 6.1–6.4 7.1 7.2 7.5 7.6 7.7 7.11 8.1 8.2 **8.3** 8.5 **8.8** 8.13 9.1 9.2 9.3 9.4 9.6 10.1 10.3 11.1 11.2 11.3 11.5 15.1 15.3 |
| **P1(重要)** | 1.4 1.5 2.2 2.4 2.7 2.8 3.4 4.3 4.4 4.5 4.11 5.4–5.6 6.5 6.7 6.9 7.3 7.4 7.8 7.12 8.4 8.6 8.7 8.9 8.10 8.11 8.12 9.5 9.11 9.12 10.2 11.4 11.6 11.7 11.9 11.10 11.11 12.1 12.2 12.5 13.1 13.2 13.3 **16.1** 15.2 |
| **P2(可选)** | 2.5 2.6 3.6 4.6 4.9 4.10 5.7 6.2 6.6 6.8 7.9 7.10 7.13 8.14 8.15 9.7 9.8 9.9 9.10 11.8 12.3 12.4 14.1–14.3 15.4 16.2 |

## 附录 B:缺陷清单

### B.1 已修复(本轮)

| # | 缺陷 | 用例 | 严重度 | 修复 |
|---|---|---|---|---|
| 1 | **`index --rebuild` 把已批准技能降级为 untrusted**,技能静默掉出提示词;`skills forget` 会连带降级无关技能;打断增长闭环 | TC-8.3 / 9.12 | **高** | `reconcile` 从注册表带过 `(trust, digest)`(`_carry_approval`);内容比对仍只由 `_restore_trust` 一处负责 |
| 2 | **`approvals approve` 默认不唤醒任务**(`--resume` 默认关),批准了却停在 `waiting_approval`;且 `decide` 拒绝重批,留下**无补救入口** | TC-7.7 | **中** | `--resume` 改为默认开(`--resume/--no-resume`),并打印任务落到的新状态 |
| 3 | **`__pycache__` 混进变更提案**:验证在 sandbox 内跑,字节码被当成 agent 改动。无 `.gitignore` 的仓库上,二进制 hunk 让 `git apply` 整体失败 —— 提案**根本没法落地** | TC-6.9 | **中** | `GitWorktreeSandbox` 用 git pathspec 排除派生产物(`_SANDBOX_EXCLUDES`),不再依赖仓库自己写 `.gitignore` |
| 4 | **审计流的"非条目行"被误报成"哈希链断裂"**:旧 `verify_chain` 对缺 `kind`/`hash` 的行报 `broken at entry 0: prev_hash mismatch`,把读者引向"被篡改"这个错误病因 | TC-7.2 / 7.2b | **中** | `verify_chain` 用 `is_chained_entry` 分出 `foreign` 行,单列报告且不再冒充断裂;CLI 与 V14 各出一个分支。**链本身并未断裂** —— 见 TC-7.2 根因 |
| 5 | **Docker 自动启动撞名**:固定 `container_name` 无视 `--project-name`,两个 compose project(目录派生的 `docker` 与固定的 `sprout`)抢同一个 `/sprout-*` 名字,`up` 退出非 0 → `sprout chat` 起不来。**冷机与「停着没删」都会坏** | KB-2 / TC-2.1 / TC-2.1b | **高** | 三层修复:①`docker-compose.yml` **删掉 4 处 `container_name`**(project 名自动限定,`sprout-sprout-redis-1` 与 `sprout-redis` 不再重叠);②`_port_is_open` **先探测**,已通则完全不碰;③`_start_existing_container` **收养停着的容器**(`docker start`,不重建),保住匿名卷里的数据,并用 `_await_listening` 补上 `--wait` 缺失的等待。<br>**服务名未变**,故 `docker compose exec sprout-redis …` 等配方与容器内 DNS(`redis://sprout-redis:6379`)全部照旧 |
| 6 | **README 文档了两条不存在的命令**:`README.md` 与 `README_CN.md` 的 `sprout evolution status` | KB-3 | 低(文档) | 两份 README 同步改为 `sprout evolution candidates`(实测存在) |
| 7 | **chat 里的编码请求被静默降级成闲聊**:意图已正确识别为 `task`(置信度 0.8),但 `handle` 的任务分支还要求 `workspace_id`,CLI 聊天消息不带它 → 掉进对话路径。而对话路径的 agent **没有任何写文件的工具**(写工具只挂在 AGENT 节点上,任务编译后才存在),于是对一个明确的"帮我写个文件"回"我写不了"。**两层缺陷**:①缺工作区时静默降级;②`handle_stream`(REPL 真正走的那条)**根本没有任务分支**,所以即便补上工作区也到不了编码路径 | TC-6.1b | **高** | 改为**问而不是降级**:无工作区的 task 意图把轮次**挂起**,问操作者"用哪个目录"(单任务同意,`WORKSPACE_CONSENT_KEY`),`grant_workspace_consent` 再恢复执行。两条 online 路径共用 `_dispatch_task_intent`,防止再次漂移。<br>问询**额外要求 `detect_task_hint` 的确定性证据** —— 只凭分类器会把普通闲聊也拦下来(测试替身对含 "task" 子串的提示词一律回 `task`,曾打挂 3 个既有用例)。<br>挂起**通过标记消息**实现而非自写 turn:`_persist_turns` 才是在线路径唯一的权威写点,双写会让一条指令落成两条 user turn |
| 8 | **措辞闸漏字即失效,且 agent 只能自己编话术**:第 7 条的问询读的是**字面** —— `写一一个`(用户实际发来的原话,多了个"一")不匹配任何 `TASK_KEYWORDS`,`detect_task_hint` 返回 `False`,分类器对这句也返回 `None`,两条路同时漏掉。agent 明知这是编码任务、也明知缺的是工作区,却**没有渠道**把这个判断交回 runtime,于是自己编了一套话术,**索要绝对路径**(runtime从不要求:`_request_workspace` 用 `Path.cwd()`,`open_workspace` 内部 `resolve()`),并把只读侦察一路上撞到 HIGH-risk 工具(`skill_script` / `cli_tool_run` / `process_run`,task id 全空)的审批瀑布展示给用户 | TC-6.1b | **高** | 给**对话路径**的 agent 加 `request_workspace` 工具(low risk,无副作用,放全局 registry —— 不是 `sandbox_ref` 守门的 AGENT 节点专属工具):agent 认出"要写文件但没有工作区"时调用它,`ToolResult.workspace_request` 冒泡到 `AgentLoop`,以 `workspace_requested` 元数据结束本轮,由 `_workspace_request_from_agent` 走**同一条** hold → consent 链。<br>这让两条路互补:**措辞闸**读字面、便宜、能省一次模型往返;**agent 举手**读整轮对话,打错字也认得出。<br>护栏:已绑定 `workspace_id` 或已带 `workspace_consent` 时不重复 hold(否则恢复会自己挂住自己) |
| 9 | **任务停下来了,而问它的人永远不会知道**:后台任务脱离产生它的那一轮运行,chat 路径**没有任何机制**观察它的状态,所以 agent 那句"写完我会告诉你"在结构上就无法兑现 —— 任务把文件写进沙箱、停在审批上,然后**整个会话再没人被通知**。用户于是反复追问"怎么还是没写成功",而系统这侧根本没有能开口的地方。**同批暴露的第二个缺陷**:经同意创建的任务 `source` 一律记成 `unknown` —— `_handle_task` 取的是 `message.channel`,而同意是从 `channel="internal"` 的内部消息恢复的,`coerce_source("internal")` 没有别名;`unknown` 恰好也是"没看出来"的取值,记录因此失去意义。第三个:任务落库时不记 `session_id`,挂起的任务不属于任何会话,回报**无从匹配** | TC-6.1b | **高** | 每轮结束(在同意/审批处理**之后**,以覆盖它们刚排入的任务)列出本会话仍在等待决定的任务,并给出**确切命令**:待批提案 → `sprout project approve <proposal_id 前 8 位>`;否则 `task_id` 匹配的待批授权 → `sprout approvals approve <approval_id 前 8 位>`;两者皆无则只报状态、不猜。`WAITING_APPROVAL` 一个状态对应**两种**原因而两者的 id 与子命令都不同,故 `task_progress()` **看实际存在什么**来判定而非从状态反推。**只报告、绝不自动决断** —— 停车本身就是安全属性。配套:`_handle_task` 优先取 `origin_channel` 记 `source`;创建任务时记 `session_id` |
| 10 | **patch 的 context 要求逐字节相等,模型看不见的空白就足以让整个 tool call 失败**:`execution/patch.py` 的 `apply_hunks` 旧实现只做精确比较,任一 context/删除行不等即 `PatchError`。而模型凭记忆写 patch 时**语义可靠、空白不可靠** —— 行尾空格它看不见,排版破折号会被写成 ASCII 连字符(文件里 `–` / `—`,patch 里 `-`)。这类 patch 全部硬失败,而报错只说 `context mismatch`,指不出是哪种不一致 | TC-6.10 | **中** | 移植 Codex `apply-patch` 的 `seek_sequence` 策略:定位分四档升级(精确 → 忽略行尾空白 → 完全 trim → Unicode 标点折叠),但**升级 ≠ 猜测**,加两条护栏 —— ①**折标点那一档只作用于文件自己指认的位置**:`@@` 行号若能折出匹配就用它,否则全文件唯一匹配才接受,否则**拒绝**;②**context 行写回文件自己的那一行**,不是 patch 里的副本,否则空白有损的 patch 会顺手改掉它没打算改的行。另:多 hunk 的 offset 改由 **ops 实际增删行数**推出,不再取 `@@` 头部计数(模型数错头会带偏后面每个 hunk)。<br>档位顺序有意义:折标点**不能**提前,否则会误拒「忽略尾空白即可唯一确定」的 patch |

| 11 | **任务没有任何取消入口,停驻的任务只能一直堆着**:审批可以决断、提案可以拒绝,但**停驻在任一闸门上的任务没有出口**。全代码库唯一的取消是私有的 `_cancel_task_after_rejection` —— 只有"拒绝提案"这一条路能走到它。于是本机积累了 **8 个 `waiting_approval` 任务**(外加 1 个 evaluation 卡死 20 分钟的 `running`),而操作者**没有任何命令**能清掉它们。更隐蔽的是:`approvals reject` 看着像出口,**其实不是** —— `_resume_after_decision` 的注释写明 *"Rejections leave the task parked"*,拒绝了任务照样停着 | TC-16.1 | **中** | 新增 `sprout project task-cancel <task_id 或前缀> [--reason]`,三层打通(runtime `cancel_task` → gateway `cancel_task`/`find_task` → CLI)。**取消而非删除** —— `execution_nodes`(95 行)、`change_proposals`(5 行)、审批记录全部引用 `task_id`,删行会让它们成为孤儿;`cancelled` 说的是"决定不做",空行说的是"从没发生",前者才是事实。<br>**守卫交给状态机而不是手写清单**:`TaskStateMachine` 允许的就允许、禁止的报 `ValueError`。由此 `FAILED` **可以**取消(它有出边 `RETRYING`,是"已结束"不是"已闭合"),而 `COMPLETED`/`CANCELLED`/`ROLLED_BACK` 被拒 —— 覆盖它们等于改写实际发生过什么。前缀歧义**拒绝而非猜测**。<br>实测(隔离存储):正常取消 / 前缀解析 / 重复取消被拒 / 未知 id 报错,四条路径全部符合预期;消融验证 —— 移除状态机守卫 → 3 个用例失败,把实现改成删行 → 4 个用例失败 |

### B.2 待跟进(未修)

| # | 缺陷 | 用例 | 严重度 |
|---|---|---|---|
| 7 | 本机审计流里那行 `{"probe": ...}` **仍在**(代码已能正确报告它,但数据没清),`audit verify` 仍退出码 1 | TC-7.2 | 中(改动不可逆,待用户决定) |
| 8 | `scan_tree` 超过 500 个技能时**静默截断**,不告警 | TC-8.6 | 中 |
| 9 | 知识/回忆/事实/摘要**到不了模型提示词**(`history_messages()` 只迭代 working) | — | 中 |
| 10 | 前端未构建(`web/frontend/dist` 不存在),`sprout serve` 只服务 API | KB-5 | 低(部署步骤) |

---

## Test Cases Supplement (2026-09-24)

# SEAM_Sprout 测试用例补充集

面向人工验收的**增量**测试清单。主手册（`SEAM_Sprout 手工测试用例集`，d11c442）覆盖了功能面，
本集只收录**主手册未覆盖、且经实测确认存在的缺陷**对应的用例，以及现有自动化测试的盲区。

- 版本：d11c442（branch dev）+ 工作区未提交改动
- 整理日期：2026-09-24
- 约定：每条用例含 前置条件 → 操作 → 预期结果。优先级 P0 必测，P1 重要，P2 可选/极客向。
- 标记说明：🌐 需要外网 · 🐳 需要 Docker · 🔑 需要真实模型 API Key · 👤 需要外部账号
- **`[实测]` 标记的预期结果已在本机复现**，非推测。复现命令可直接粘贴运行。

---

## 0. 环境准备

### 0.1 统一命令前缀（同主手册）

```bash
cd D:/SEAM_Sprout
export PYTHONPATH=src
SPROUT=".venv/Scripts/python.exe -m Sprout.cli.app"
```

`kb` 已知坑沿用主手册 KB-1（pytest 必须带 `--basetemp=.pytest_tmp -p no:cacheprovider`）。

### 0.2 本次审查的验收基线 [实测]

| 项目 | 实测值 | 判定 |
|---|---|---|
| 自动化测试 | **945 passed, 11 skipped** | ✅（主手册写 942，已更新） |
| Lint | `ruff check src web` → All checks passed! | ✅ |
| 六条存储链路 | 全部 healthy（Docker 在跑） | ✅ |
| 审计链 | **1177 条，`chain intact`** | ✅（主手册 KB-4 已过期，见 §24） |

> ⚠️ 关键结论：以下 §16–§23 的缺陷**全部逃过了这 945 个测试**。基线全绿不等于无缺陷。

---

## 16. 级联删除与 Blob 回收 ⭐ 最高优先级

> 背景：会话外置的大正文（>8KB，`runtime.py:270`）走 blob store。删除会话时若回收不掉，
> 数据永久残留 —— `BlobStore` 契约只有 put/get/exists/delete/count，**没有任何 GC**
> （`storage/contracts/blobs.py`；`blob_store.py` 的 docstring 却声称有 GC，属文档错误）。

### TC-16.1 真实外置正文必须随会话删除 — P0

**目的**：验证级联删除回收的是**生产实际写入的字段**。

- **前置**：无（纯内存 bundle 即可，不需要 Docker）
- **背景（必读）**：外置 URI 由 `runtime.py:1186` 写入 **metadata 信封**
  （`{"blob_uri": ..., "content_bytes": ...}`）；`Turn.content_blob_uri` 这个**独立列**
  在生产代码中**从未被赋值**（全仓仅有 `turns.py:208` 读取它，写入点为零）。
- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
import asyncio
from Sprout.storage.bundle import StorageBundle
from Sprout.session.models import Turn, Session

async def main():
    b = StorageBundle.in_memory()
    store = b.session_store()
    await store.save_session(Session(id="s1", user_id="u", channel="cli"))
    uri = await b.blobs.put(b"x" * 999999, mime_type="text/plain")
    # 严格复刻 runtime._offload_body 的产物：预览 + 信封记 uri
    await store.append_turn(Turn(session_id="s1", role="user", content="preview...",
        metadata={"blob_uri": uri, "content_bytes": 999999}))
    print("blob before:", await b.blobs.exists(uri))
    report = await b.delete_session_cascade("s1")
    print("report:", report)
    print("blob after :", await b.blobs.exists(uri))

asyncio.run(main())
EOF
```

- **预期结果（应当）**：
  - `blob after: False`
  - `report["blobs"] == 1`
- **⚠️ 实测当前**：`blob after: True`、`report: {'turns': 1, 'fts': 0, 'blobs': 0}`
  —— **blob 泄漏，且报告谎报 0**。
- **根因**：`session_blob_uris()` 读的是 `turn.content_blob_uri`（`sqlite_store.py:259`、
  `jsonl_store.py:135`、`memory_store.py:55`），而该字段生产不写。
  契约与设计文档一致地指向信封：`MESSAGE_PERSISTENCE.md:170`「信封记 `{"blob_uri": ...}`」。

### TC-16.2 生产使用的 session wrapper 必须能报出 blob URI — P0

- **前置**：无
- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
from Sprout.storage.bundle import StorageBundle
from Sprout.session.models import Turn
import asyncio

async def main():
    b = StorageBundle.in_memory()
    print("bundle.sessions ->", type(b.session_store()).__name__)

asyncio.run(main())
EOF
PYTHONPATH=src .venv/Scripts/python.exe -c "
from Sprout.storage.lanes import SixLaneFanout
print('SixLaneFanout.session_blob_uris:', hasattr(SixLaneFanout, 'session_blob_uris'))
"
```

- **预期结果（应当）**：`SixLaneFanout.session_blob_uris` 存在并转发给 authority。
- **⚠️ 实测当前**：`hasattr` → **False**。
- **影响**：`bundle.py:350` 在六链路模式下把 `sessions` 替换为 `SixLaneFanout`，
  所以**生产配置（配了 Milvus/Neo4j/Redis/context 时）走的就是这条缺方法的路径** ——
  即使字段问题修好，该 wrapper 仍会让 `getattr(..., None)` 探针返回 `None`，
  静默当作「本会话无 blob」。

### TC-16.3 上下文快照的外置 blob 也必须回收 — P1

- **前置**：无
- **背景**：`lanes.py:384` 会把超 64KB 的 context 快照写进 blobstore
  （`ContextRecord.blob_uri`）。
- **操作**：构造一个带 `blob_uri` 的 context 记录 → `delete_session_cascade` → 检查 blob 是否还在。
- **预期结果（应当）**：context 外置 blob 一并删除，`report` 反映该项。
- **⚠️ 实测当前**：`delete_session_cascade`（`bundle.py:113-147`）**完全没有 context 分支** ——
  `self.context` 从未被读取。

### TC-16.4 路径探针不得吞掉"后端不会答" — P1

- **目的**：`getattr(store, "session_blob_uris", None)` 让缺失方法静默等于"无 blob"。
- **操作**：对 `BlobSessionStore` / `MilvusSessionStore` / `Neo4jSessionStore` /
  `RedisSessionStore` / `ReservedSessionStore` 逐个检查。
- **预期结果（应当）**：要么全部实现契约，要么探针把"缺失"报成错误。
- **⚠️ 实测当前**：这五个后端**全部缺失**该方法（`grep -c session_blob_uris` = 0）。
  契约（`rootstock/contract.py:44-54`）已声明它是必需项，实现未跟上。

---

## 17. 技能信任完整性 ⭐ 安全级

> 背景：信任是注册表（`sprout_audit.db`）的裁决，快照 `index.json` 是派生视图。
> `reconcile()` 却用**磁盘扫描结果**覆盖快照，而磁盘扫描的 trust 是**常量**：
> managed 目录（`.fetched/` `.evolved/`）硬编码 `untrusted`（`loader.py:96`），
> 普通技能硬编码 `trusted`（`loader.py:172`）。

### TC-17.1 已批准技能在 rebuild 后必须保持 trusted — P0

**目的**：TC-8.3 的替身。主手册依赖"先 install 再看"，本条用最小复现。

- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
import tempfile, pathlib, asyncio
from Sprout.skills.models import SkillRecord
from Sprout.storage.local.memory.skills import MemorySkillStore
from Sprout.skills.index import reconcile, SkillIndex
from Sprout.skills.layout import index_path

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); sdir = d/"skills"; sdir.mkdir()
    p = sdir/".evolved"/"banana"; p.mkdir(parents=True)
    (p/"SKILL.md").write_text("---\nname: banana\ndescription: say BANANA\n---\nAlways start with BANANA.\n", encoding="utf-8")
    store = MemorySkillStore()
    asyncio.run(store.upsert(SkillRecord(name="banana", version="1", description="d",
        source="evolved", trust="trusted", path=str(p))))
    print("registry trust :", asyncio.run(store.get("banana")).trust)
    reconcile(store, sdir)
    print("snapshot trust :", [(r.name, r.trust) for r in SkillIndex(index_path(sdir)).load()])
    print("registry after :", asyncio.run(store.get("banana")).trust)
EOF
```

- **预期结果（应当）**：`snapshot trust: [('banana', 'trusted')]`
- **⚠️ 实测当前**：`[('banana', 'untrusted')]` —— 技能静默掉出模型提示词
  （`matcher.py:61` 按 trust 过滤）。

### TC-17.2 rebuild 不得把 untrusted 提升为 trusted — P0 🔒

**目的**：这是**安全缺陷**（提权），比降级更危险，主手册未收录。

- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
import tempfile, pathlib, asyncio
from Sprout.skills.models import SkillRecord
from Sprout.storage.local.memory.skills import MemorySkillStore
from Sprout.skills.index import reconcile, SkillIndex
from Sprout.skills.layout import index_path
from Sprout.skills.registry import create_skill_registry
from Sprout.skills.loader import artifact_digest

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d); sdir = d/"skills"; sdir.mkdir()
    p = sdir/"evil"; p.mkdir()
    (p/"SKILL.md").write_text("---\nname: evil\ndescription: x\n---\nbody\n", encoding="utf-8")
    rec = SkillRecord(name="evil", version="1", description="x", source="local",
        trust="untrusted", digest=artifact_digest(p), path=str(p))
    SkillIndex(index_path(sdir)).save([rec])          # 操作员的明确裁决
    print("baseline :", create_skill_registry(sdir, index=SkillIndex(index_path(sdir))).list()["evil"].trust)
    store = MemorySkillStore(); asyncio.run(store.upsert(rec))
    reconcile(store, sdir)
    print("snapshot :", [(r.name, r.trust) for r in SkillIndex(index_path(sdir)).load()])
    print("after    :", create_skill_registry(sdir, index=SkillIndex(index_path(sdir))).list()["evil"].trust)
EOF
```

- **预期结果（应当）**：全程 `untrusted`
- **⚠️ 实测当前**：baseline `untrusted` → after **`trusted`** —— 明确的拒绝裁决被反转。
- **加重情节**：`registry.py:80` 读的正是这个被污染的同一个快照，
  所以**runtime 提示词装配继承该结果**，不只是 CLI 显示问题。

### TC-17.3 forget 不得连带降级无关技能 — P1

- **操作**：`.evolved/` 下放 alpha、beta 两个技能，两者注册表均为 `trusted`；
  只 `store.remove("alpha")` → `reconcile` → 检查 beta。
- **预期结果（应当）**：beta 仍为 `trusted`。
- **⚠️ 实测当前**：alpha、beta **双双变 untrusted**（rebuild 重扫全目录所致）。

### TC-17.4 降级要能被端到端观察到 — P0 🔑

- **目的**：证明快照 trust 真的决定提示词可见性（主手册 TC-8.13 的自动化替身）。
- **操作**：对一个 `.evolved/` 技能执行 `reconcile` 前后，分别调用
  `SkillMatcher().match(query, index, injectable_only=True)`。
- **预期结果（应当）**：命中数不因 rebuild 变化。
- **⚠️ 实测当前**：命中数 **1 → 0**。

---

## 18. 存储 JSON 契约与迁移

### TC-18.1 `storage check --json` 必须是纯 JSON — P0

**目的**：主手册 TC-1.4 只覆盖了 `security check`，未覆盖 `storage check`。

- **前置**：Docker 在跑（有 lane 才会暴露问题）
- **操作**：

```bash
export PYTHONPATH=src
.venv/Scripts/python.exe -m Sprout.cli.app storage check --json 2>/dev/null > sc.json
.venv/Scripts/python.exe -c "import json;d=json.load(open('sc.json',encoding='utf-8'));print('valid json');print('ok=',d['ok'],'status=',d['status'])"
```

- **预期结果（应当）**：打印 `valid json`，且 `ok` 与退出码一致（0↔true）。
- **⚠️ 实测当前**：`json.load` **抛 JSONDecodeError**。stdout 实际内容为：

```
healthy  SQLite (authority)
healthy  JSONL (evidence)
... (6 行)
{
  "ok": true,
  ...
```

- **根因**：`cli/commands/storage.py:41` 的 `_lane_progress` 无条件 `typer.echo` 到 stdout，
  而 `--json` 分支（`:235`）在 `check_lanes` **之后**才判断。`init` 同样中招（`:139`）。
- **退出码一致性**（TC-4.4 的实质）：剥离前缀后解析，`ok=True` ↔ exit 0 ✅ 一致。

### TC-18.2 无 lane 时也必须测 JSON 纯净性 — P1

- **目的**：指出为什么现有测试抓不到 TC-18.1。
- **背景**：`test_lanediag.py:107` 用的离线 fixture **零 lane**，
  `progress` 回调从不触发 → 永远测不出污染。
- **操作**：对比 `--json` 在「无 lane」与「有 lane」两种配置下的 stdout 首字节。
- **预期结果（应当）**：两种配置下 `stdout[0]` 都是 `{`。
- **⚠️ 实测当前**：无 lane 时是 `{`，有 lane 时是 `h`（`healthy`）。

### TC-18.3 FTS 迁移中断后重试不得复制数据 — P0

**目的**：主手册 TC-4.11 只测了成功路径的"无损"，未测中断重试。

- **操作**（模拟"复制完成、尚未交换"时进程死亡）：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
from Sprout.storage.local.sqlite.driver import SqliteDatabase
from Sprout.storage.local.sqlite.fts_migrate import migrate_fts_tokenizer, table_tokenizer
import tempfile, os

SCHEMA = ("CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5("
          "session_id UNINDEXED, turn_id UNINDEXED, role UNINDEXED,"
          "seq UNINDEXED, body, tokenize='trigram');")
COLS = ("session_id","turn_id","role","seq","body")
INS = "INSERT INTO turns_fts (session_id,turn_id,role,seq,body) VALUES (?,?,?,?,?)"

d = tempfile.mkdtemp(); db = SqliteDatabase.open(os.path.join(d, "x.db"))
db.executescript(SCHEMA.replace("tokenize='trigram'", "tokenize='unicode61'"))
for i in range(3):
    db.execute_sync(INS, (f"s{i}", "t", "user", i, f"body {i}"))
cnt = lambda t: db.fetchall_sync(f"SELECT count(*) AS c FROM {t}")[0]["c"]
print("before    :", table_tokenizer(db, "turns_fts"), "rows=", cnt("turns_fts"))

# 前一次迁移死在这里：临时表已建好并灌满，交换未执行
db.executescript(SCHEMA.replace(" turns_fts ", " turns_fts_migrating ", 1))
db.execute_sync("INSERT INTO turns_fts_migrating (session_id,turn_id,role,seq,body) "
                "SELECT session_id,turn_id,role,seq,body FROM turns_fts")

migrate_fts_tokenizer(db, "turns_fts", SCHEMA, COLS)   # 下次打开时重试
print("after     : rows=", cnt("turns_fts"), "(期望 3)")
db.close()
EOF
```

- **预期结果（应当）**：`after: rows= 3`（模块 docstring 承诺"失败部分完成会保留原索引"）
- **⚠️ 实测当前**：**`rows= 6`** —— 整批行被复制一遍，检索结果重复。
- **根因**：`fts_migrate.py:69` 用 `IF NOT EXISTS` 建临时表，复用了残留表并**再次 INSERT**；
  `_discard_leftovers`（:90）只在成功路径与"已是 trigram"路径调用。

### TC-18.4 已是 trigram 时清理残留 — P2

- **操作**：表已是 trigram，但存在残留 `turns_fts_migrating` / `turns_fts_old`。
- **预期结果**：`_discard_leftovers` 清掉残留，行数不变。
- **实测**：该分支行为正确（残留被清理，3 行保持 3 行）✅ —— 记录以免误改。

---

## 19. 子进程环境净化

### TC-19.1 `git_env()` 无参调用必须保留 PATH — P1

- **目的**：主手册 TC-7.13 的断言方式会掩盖此缺陷。

- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe -c "
from Sprout.execution.git_env import git_env
import os
e = git_env()
print('keys       :', sorted(e.keys()))
print('PATH kept  :', any(k.upper()=='PATH' for k in e))
print('parent PATH:', bool(os.environ.get('PATH')))
"
```

- **预期结果（应当）**：`PATH kept: True`（子进程需要 PATH 才能找到 git 本身）
- **⚠️ 实测当前**：`keys: ['GIT_ASKPASS','GIT_EDITOR','GIT_PAGER','GIT_SEQUENCE_EDITOR','GIT_TERMINAL_PROMPT']`、
  `PATH kept: False` —— **环境里只有 5 个 GIT_* 变量**。
- **根因**：`git_env.py:56` 是 `child_env(base_env=base_env)`，而四个调用点
  （`git_broker.py:194`、`apply.py:216/235`、`sandbox_tool.py:633`）**全部无参调用**
  → `base_env=None` → `child_env` 以 `{}` 为源 → 白名单无物可留。
- **为什么本机没炸**：本机 git 位于 Windows 系统路径，即使无 PATH 也能被解析。
  **在 Linux/macOS 或 git 装在非系统路径的机器上会直接 command not found。**
- **对照**：`ProcessBroker` 正确地传了 `base_env=os.environ`（`process_broker.py:140`）——
  所以这是 git 路径独有的不一致，不是全局设计。

### TC-19.2 敏感变量必须被剥离 — P0

- **操作**：`child_env(base_env=os.environ)`，环境里植入假 `DEEPSEEK_API_KEY` / `AWS_SECRET_ACCESS_KEY`。
- **预期结果**：两者都不在子环境里，PATH 在。
- **实测**：✅ **正确**（两者均被剥离，PATH 保留）。这部分无需修。

### TC-19.3 姿势检查要测真实调用签名 — P1

- **目的**：指出 V8 为什么查不出 TC-19.1。
- **背景**：`posture.py:704` 是 `git_env(planted)` —— **传了** env，与生产的无参调用不同签名。
- **操作**：断言 `git_env()`（无参）的返回也满足 V8 的不变量。
- **⚠️ 实测当前**：无参调用不满足，但 V8 恒报 OK。

---

## 20. 记忆与提示词装配

### TC-20.1 recalled / knowledge / facts 必须到达模型 — P1

- **目的**：主手册附录 B#5 的复核确认。
- **背景**：`ContextMemory.__iter__`（`memory/models.py:80`）只 yield `working`；
  `history_messages`（`agent/base.py:36`）靠迭代取内容 → 其余四类**全部丢失**。
- **操作**：

```bash
PYTHONPATH=src .venv/Scripts/python.exe - <<'EOF'
from Sprout.memory.models import ContextMemory, SessionFact, SearchHit
from Sprout.session.models import Session, Turn
from Sprout.agent.base import history_messages

mem = ContextMemory(
    session=Session(id="s1", user_id="u"),
    working=(Turn(session_id="s1", role="user", content="工作时轮次"),),
    recalled=(SearchHit(session_id="s1", turn_seq=1, turn_id="t", snippet="被回忆的命中"),),
    facts=(SessionFact(session_id="s1", key="name", value="小明"),),
)
text = "\n".join(m.content for m in history_messages(mem))
print("含 working :", "工作时轮次" in text)
print("含 recalled:", "被回忆的命中" in text)
print("含 facts   :", "小明" in text)
EOF
```

- **预期结果（应当）**：三者都为 True
- **⚠️ 实测当前**：仅 working 为 True，recalled / facts **均未进入模型消息**。

### TC-20.2 摘要与知识条目同样要可见 — P2

- 同上，断言 `summary` 与 `knowledge` 也能到达。当前不可达。

---

## 21. 非 sqlite 后端字段保真

### TC-21.1 Turn 全字段往返 — P1

- **目的**：把工作区里的临时探针 `_probe_fields.py` / `_probe_reopen.py` 转正为**断言**。
- **操作**：对每个后端 `append_turn` 后读回，逐字段比对
  `content_type` / `content_blob_uri` / `line_count` / `token_estimate` / `language`。
- **预期结果**：全部一致。
- **⚠️ 实测当前**：

| 后端 | 丢失字段 |
|---|---|
| `SqliteSessionStore` | 无 ✅ |
| `MemorySessionStore` | **5/5 全丢** |
| `JsonlSessionStore` | **5/5 全丢**（重开文件同样丢） |
| `BlobSessionStore` | **5/5 全丢** |

- **根因**：`blob_store.py:37`、`jsonl_store.py:31` 的序列化只写 7 个字段。
- **备注**：`_probe_fields.py` 当前还会 `TypeError`（`BlobSessionStore` 需要 `blobs` 参数），
  转正时一并修正。

### TC-21.2 生产从未写入 `content_blob_uri` — P1

- **操作**：`grep -rn "content_blob_uri=" src/Sprout --include=*.py | grep -v tests`
- **预期结果（应当）**：存在写入点（契约与 `models.py:59` 如此描述）
- **⚠️ 实测当前**：**零个写入点** —— 只有 `turns.py:208` 的读取。
  这是 TC-16.1 的根因，也说明该列目前是死字段。

### TC-21.3 `folded_block` 契约与实现不符 — P2

- **操作**：`grep -rn "folded_block" src/Sprout web --include=*.py`
- **预期结果（应当）**：CLI 折叠粘贴路径设置 `content_type='folded_block'` + `line_count`
- **⚠️ 实测当前**：只出现在 `session/models.py:59` 的注释和测试里，
  **生产代码从不设置**。主手册 TC-2.6 描述的"折叠"仅发生在 TUI 显示层，
  未落到落库契约。

---

## 22. Web 控制台

> 现状：`web/tests` 共 25 个测试，覆盖 health / chat / auth / approvals / project。
> 主手册的 P0/P1 Web 用例**大部分无自动化覆盖**。

### TC-22.1 任务板 API — P1

- **操作**：`GET/POST /api/tasks`、`PATCH/DELETE /api/tasks/{id}` 全流程。
- **预期结果**：CRUD 生效，刷新后状态保持。
- **⚠️ 实测当前**：`web/tests/test_webapi.py` 中 `tasks` 相关断言 **0 条**。

### TC-22.2 存储视图 API — P1

- **操作**：`GET /api/storage/status`、`/api/storage/plan`、`/api/storage/graph/status`、
  `/api/storage/vectors/count`。
- **⚠️ 实测当前**：**0 条**测试覆盖。

### TC-22.3 设置脱敏（认证关闭时也必须生效） — P1

- **操作**：`web_auth_enabled=false` 下 `GET /api/settings`，断言 DSN 密码被掩。
- **实测**：`mask_settings` 本身 ✅ 正确（植入 `redis://admin:S3cr3tP@ss@...` 后
  `S3cr3tP@ss` 不出现在输出中），`test_web_auth.py:115` 已覆盖。
- **待补**：认证**关闭**时的分支断言。

### TC-22.4 tokens / logs 视图 — P2

- **操作**：`GET /api/tokens`、`GET /api/logs`。
- **⚠️ 实测当前**：**0 条**测试覆盖。

---

## 23. 端到端闭环

### TC-23.1 增长闭环（学到 → 用上） — P0 🔑

- **目的**：证明"生长闭环"真的闭合（主手册 TC-9.12 的自动化替身）。
- **操作**：批准发布一个技能 → 新会话提命中该技能的任务 → 断言回答体现该技能。
- **⚠️ 关联缺陷**：该闭环被 **TC-17.1 / 17.4 打断** —— 任何 `index --rebuild`
  都会把刚发布的 `.evolved/` 技能降级，从而掉出提示词。
- **建议**：本条应在 TC-17.x 修复后作为收尾验收。

### TC-23.2 `scan_tree` 超限必须告警 — P1

- **操作**：构造 >500 个技能的目录树 → `sprout skills import <dir>`。
- **预期结果（应当）**：明确告警"已达上限，N 个未导入"。
- **⚠️ 实测当前**：`tree.py:131` 静默 `return`，**无任何告警**。

---

## 24. 主手册修订建议

### 24.1 已过期，应改为"通过"

| 主手册条目 | 原文 | 实测 |
|---|---|---|
| KB-4 | "本机审计链当前是断的" | ❌ 过期。实测 **1177 条 `chain intact`**，exit 0 |
| TC-7.2 | "chain broken at entry 0"，当作真实缺陷跟进 | ❌ 同上，应改为"已验证通过" |
| 附录 B #2 | 审计哈希链断裂，严重度"高" | ❌ 已修复 |

旁证：`~/.sprout/data/audit/security.jsonl.broken-chain-20260921`
（1622 行归档）表明该问题在 2026-09-21 已被处理并归档重启。

### 24.2 优先级应上调

| 主手册条目 | 原严重度 | 建议 | 理由 |
|---|---|---|---|
| TC-8.3 / 附录B#1 | 高 | **最高** | 不只是降级：rebuild 会**反转明确的 untrusted 裁决**（TC-17.2），是安全缺陷 |
| 附录B#5（记忆到不了提示词） | 中 | **高** | 已复核确认（TC-20.1），影响全部检索增强能力 |

### 24.3 附录 B 应新增

| # | 缺陷 | 用例 | 严重度 |
|---|---|---|---|
| 7 | 级联删除漏 blob（修复方向错误：读了生产不写的字段；`SixLaneFanout` 缺方法；context 快照未管） | TC-16.1–16.4、21.2 | **高** |
| 8 | FTS 迁移中断重试复制整批行 | TC-18.3 | **高** |
| 9 | `storage check/init --json` 输出被 progress 行污染 | TC-18.1 | 中 |
| 10 | `git_env()` 无参调用丢失 PATH | TC-19.1 | 中（跨平台会炸） |
| 11 | 非 sqlite 后端丢 5 个字段 | TC-21.1 | 中 |

### 24.4 基线数字更新

`942 passed, 11 skipped` → **`945 passed, 11 skipped`**
（+3 来自工作区新增的 `test_session_cascade_blobs.py`）。

---

## 附录 A：优先级汇总

| 优先级 | 用例 |
|---|---|
| **P0（必测）** | 16.1 16.2 17.1 17.2 17.4 18.1 18.3 19.2 23.1 |
| **P1（重要）** | 16.3 16.4 17.3 18.2 19.1 19.3 20.1 21.1 21.2 22.1 22.2 22.3 23.2 |
| **P2（可选）** | 18.4 20.2 21.3 22.4 |

---

## 附录 B：必须先修的现有测试（测盲区）

> 这几条**不是"没测到"，而是"测错了对象"** —— 它们给缺陷提供了虚假的安全感。优先级高于新增用例。

| 测试 | 问题 | 对应缺陷 |
|---|---|---|
| `tests/test_session_cascade.py:108` | 直接构造 `content_blob_uri=uri`（生产永不写入的字段）。docstring 写着"from the turns' envelopes"，实现却没用信封 | TC-16.1 |
| `tests/test_session_cascade_blobs.py` | 新增测试重复了同一盲区 | TC-16.1 |
| `tests/test_skills_trust_restore.py` | 直接写 index 设 `trust="trusted"`，**从不执行 `reconcile`** | TC-17.1/17.2 |
| `tests/test_lanediag.py:107` | 离线 fixture 零 lane → `_lane_progress` 永不触发 → JSON 污染测不出 | TC-18.1 |
| `tests/test_security_posture.py:272` | V8 传入 `planted` env（≠ 生产的无参调用） | TC-19.1 |
| `tests/_probe_fields.py` / `_probe_reopen.py` | 是打印式探针非断言；且前者当前 `TypeError` | TC-21.1 |

**修复方向的建议**：断言应建立在**生产代码的真实产物**上
（用 `runtime._offload_body` 的输出、用无参 `git_env()`、用真实的 `reconcile` 流程），
而不是手工构造一个「恰好能让实现通过」的输入。

---

## 附录 C：修复顺序建议

1. **先定契约**：`blob_uri` 归信封（`MESSAGE_PERSISTENCE.md:170` 已如此规定）还是独立列。
   **这一步没定，TC-16 的修复会继续打偏。**
2. TC-17.1/17.2 技能信任双向修复（安全，且解锁 TC-23.1）
3. TC-18.3 FTS 重复行（数据正确性）
4. TC-16.1–16.4 级联回收（按第 1 步的结论）
5. TC-18.1 JSON 污染、TC-19.1 PATH（低风险、高性价比）
6. TC-20.1 / TC-21.1（能力增强）

---

## 附录 D：修复记录（2026-09-24）

以下缺陷已修复并有防回归测试。契约决策（附录 C 第 1 条）取 `MESSAGE_PERSISTENCE.md:170`
的规定：**`blob_uri` 归 metadata 信封**，同时保留 `content_blob_uri` 列为第二种书写位置，
读取侧两者兼容（`rootstock/contract.py: blob_uri_of`）。

| 缺陷 | 修复 | 测试 |
|---|---|---|
| TC-17.1/17.2 技能信任双向篡改 | `reconcile` 保留注册表的 `trust`/`digest`/`enabled`/`pinned`，只从磁盘刷新描述性字段 | `test_skills_reconcile.py`（+5） |
| TC-18.3 FTS 迁移重复行 | 建临时表前先 `DROP TABLE IF EXISTS`，清掉中断残留 | `test_fts_tokenizer_migration.py`（+1） |
| TC-16.1 级联漏 blob（信封形式） | `blob_uri_of` 同时读列与信封；三个后端改用共享 helper | `test_session_cascade.py`（+3）、`test_session_cascade_blobs.py` |
| TC-16.2 `SixLaneFanout` 缺方法 | 转发给 authority | `test_session_cascade_blobs.py` |
| TC-16.3 context 快照漏回收 | 级联新增 context 分支；**另修** `SqliteContextStore._row_to_record` 漏读 `blob_uri` | `test_session_cascade.py`、`test_storage_sqlite.py`（+1） |
| TC-16.4 探针吞错 | 后端缺失方法时 `logger.warning`，不再静默当作"无 blob" | 同上 |
| TC-18.1 `--json` 污染 | progress 回调在 JSON 模式静默 | `test_lanediag.py`（+2） |
| TC-4.1 `[n/4]` 阶段行不打印 | `ui.muted(...)` 是纯格式化函数，裸语句被丢弃；补 `typer.echo` 包裹（13 处） | `test_lanediag.py`（+1） |
| TC-19.1 `git_env()` 丢 PATH | `base_env` 默认取 `os.environ` | `test_system_tools_env.py`（+3） |
| TC-20.1 记忆到不了提示词 | 新增 `memory_block_for`，在 `AgentLoop`/`ModelAgent` 注入 system 消息 | `test_memory_prompt_assembly.py`（新增，6 条） |
| TC-21.1 非 sqlite 后端丢字段 | 共享 `turn_to_document`/`turn_from_document`，兼容旧记录 | `test_storage_message_columns.py`（+3） |
| TC-16.4 其余后端缺方法 | blobstore/milvus/neo4j/redis/reserved 补齐契约 | `test_session_cascade_blobs.py` |

**测试结果**：`973 passed, 11 skipped`（修复前 945），`ruff check src web` 全绿。
连续 3 次全量运行稳定。

### 附录 D.1：新发现的测试污染 bug（已修）

`test_git_broker_approval.py` 在 `--basetemp=.pytest_tmp` 下把 `tmp_path` 置于**仓库内部**，
而 `GitBroker.commit` 会执行 `git add -A` —— **`-A` 从任意子目录都会暂存整个仓库**。
结果该测试真的向开发者的仓库提交了代码（产生了 `x` 为消息的提交），
并因此使自己的断言偶发翻转（外层仓库里 `git commit` 反而会成功）。

- 修复：`_isolated_workspace()` 新建独立仓库，不依赖 `tmp_path` 恰好在仓库外；并断言
  `_has_commits(root)` 为假。
- 验证：连续 6 次运行 + 3 次全量，HEAD 恒定不变，未提交改动未被吞掉。

**遗留**：仓库历史里已有数个 `x` 提交（`c4d0180`/`a3da952`/`58bbe3b`/`5ff6352`），
是被该 bug 卷进去的工作内容，需要人工决定如何处理（保留、squash 还是 reset）。

---

## 附录 E：第二轮审查（2026-09-24 晚）

第二轮换了策略：专门扫前几轮未覆盖的模块（gateway / mcp / orchestration / sandbox /
workspace / evolution / llm），以及"声明了却没人读"的字段。共 4 个真实缺陷
（E.1–E.4），另有 2 条经复核**不成立**（E.5），一并记录以免日后误修。

### E.1 沙箱执行不可信代码时泄漏全部环境变量 — 高

`GitWorktreeSandbox.run_code` 是 runtime**唯一**执行不可信代码的地方（模型生成、可被
抓取的 skill 或仓库内容影响）。它经 `run_capture` 启动子进程，而 `run_capture` 在
`env=None` 时让子进程**继承父环境**——调用点没传 `env=`。

实测：`run_code` 里读取 `SPROUT_FAKE_SECRET` → **LEAK**。

其他所有启动点都已白名单化：`ProcessBroker`、`CliRunTool` 走 `SecretBroker.child_env`，
git 助手走 `git_env`。只有这条最容易出事的路漏了。

修复：传 `SecretBroker().child_env(base_env=os.environ)`。新增
`test_sandbox_execution_env.py`（3 条），其中一个断言 PATH 仍在（别把 runtime 也剥没了）。

### E.2 `DelegationScope.narrow` 会**放宽**权限 — 高（潜伏）

`narrow` 承诺 "never broader than either one"，但路径收窄是反的：`permits` 用
`any(path.startswith(prefix))`，所以 scope 是各前缀子树的**并集**，而原实现把右侧未被
左侧覆盖的前缀也保留了下来。

实测：`narrow(("/a","/b"), ("/b","/c"))` 得到 `("/b","/c")`——**放出了 `/c`**，而父 scope
从未允许 `/c`。

修复过程中穷举还暴露了第二个问题：不相交的两个 scope（`("/a",)` 与 `("/b",)`）交集为空，
但**空元组在 `permits` 里表示"不限"**，所以"无法表示空集"会把"互相排斥"变成"没有限制"。
现改用 `denied_paths=("",)`（空前缀匹配一切）表达空交集。

- 覆盖：676 组穷举验证 `narrow` 恰等于交集，且单调性无违例。
- 影响面：`narrow` **当前无生产调用点**（只有测试），属潜伏缺陷；一旦用于委托收窄即静默提权。
- 新增 4 条测试（含穷举）。

### E.3 `SubprocessRunner` 文档声称的环境过滤并不存在 — 中

docstring 写 "Environment is *not* copied wholesale, mirroring the broker's whitelist
rule"，实际没传 `env=`，子进程继承一切（实测 LEAK）。

生产路径（CLI 的 `github`/`url` 源）走 `ProcessBrokerRunner`/`NetworkBrokerRunner`，
是安全的；`SubprocessRunner` 是**无 broker 时的回退**。但"文档承诺的安全属性代码里没有"
比不承诺更糟——现改为真正白名单化，并订正 docstring。

### E.4 `/api/storage/status` 明文回传 DSN 密码 — 中

同一份 `storage.graph`（真实值 `neo4j://neo4j:sprout123@127.0.0.1:7687`）：
`/api/settings` 走 `mask_settings` 掩码，`/api/storage/status` **原样返回**。
控制台一个页面显示 `[REDACTED]`，另一个页面显示真实密码。

- 缓解：`web_auth_enabled` 默认 false，但只绑 loopback，且 `warn_if_exposed` 会告警。
- 修复：该路由同样经 `Redactor` 处理。新增 1 条测试。

### E.5 复核后**不成立**的两条（记录以免误修）

- **演化发布不写注册表行**：一度怀疑发布路径（`CandidateManager._publish`）会在
  rebuild 后丢失信任。核查后发现它写的是 `<root>/<name>.toml`，根目录技能按设计
  （`loader.py:172`、`registry.py:74`）就是 `trusted`，rebuild 后依然可见——
  **成长闭环是通的**。唯一残留：发布不刷新 `index.json` 快照，所以 `SkillMatcher`
  驱动的检索要等一次 rebuild 才看到它；提示词注入走内存 registry，不受影响。
- **`cron`/`automation` source 伪造**：声称这两个 source 会绕过审批。实测相反——
  它们是**无人审批 → 直接拒绝**（fail closed），伪造只会导致自己的工具调用被拒。

### E.6 第二轮测试结果

`982 passed, 11 skipped`（本轮 +8 条测试），`ruff check src web` 全绿，
HEAD 恒定不变。已修复项的测试均验证过"禁用修复即失败"。

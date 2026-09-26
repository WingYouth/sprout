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
  <img src="assets/seam_sprout.svg" alt="SEAM Sprout logo" width="180" />
</div>

<h1 align="center">SEAM Sprout</h1>

<p align="center">
  An embedded AI Engineering Runtime for turning project intent into verified, reviewable, traceable software changes.
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## Overview

SEAM Sprout is an AI Engineering Runtime embedded inside a software project. It moves a change from user intent to code edits, isolated execution, verification, approval, integration, and traceability.

Sprout is not a chat wrapper. It is the project-side runtime that lets an AI agent read repository evidence, plan work, modify code in a git worktree sandbox, run checks, produce reviewable proposals, and record what happened. The same runtime is shared by the Python API, CLI, web console, gateways, and MCP server.

The product idea is simple: AI-generated code should not jump straight from a model response into your project. It should pass through project context, risk controls, verification, human review, and an audit trail.

## What Sprout Solves

Sprout focuses on the gap between "the model gave me an answer" and "the project has a trustworthy change." That gap is where most AI coding workflows still break.

| Real project pain | Why it is hard | Sprout's answer |
|---|---|---|
| **AI gives an answer, but the engineering work is still unfinished** | A snippet still has to land in the right files, fit existing architecture, pass tests, and survive conflicts. | Turns natural-language intent into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered** | Useful context lives across source files, tests, docs, storage schemas, prior sessions, logs, and project preferences. | Builds context from repository scans, sessions, memory, knowledge, storage evidence, and task history. |
| **Generated code looks plausible but is not proven** | LLM output may look correct before it has ever run in the target environment. | Runs edits and checks inside a git worktree sandbox and attaches verification evidence to the proposal. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network access, database access, and git operations have different blast radii. | Routes sensitive operations through risk classification, policy, approvals, and controlled brokers. |
| **Maintenance work keeps piling up** | Bug fixes, refactors, tests, docs, dependency cleanup, and interface alignment are ongoing work, not one-off prompts. | Supports project tasks, proposals, approval flows, verification, and growth candidates. |
| **Learning does not compound across tasks** | Fixes, project conventions, and workflow knowledge disappear if they only live in chat history. | Persists memory, trajectories, task history, knowledge, and versioned skills for future work. |
| **Entry points drift apart** | CLI, web, API, gateway, and MCP surfaces can accidentally develop different behavior and permissions. | Sends every surface through the same `create_runtime()` assembly path with shared storage, security, events, and tools. |
| **Storage and infrastructure are hard to trust** | Sessions, knowledge, audit, vectors, graph data, and cache state may live in different backends. | Provides initialization, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## Core Workflow

```text
User request
  |
  v
Project evidence + memory
  |
  v
Plan + risk classification
  |
  v
Sandboxed code edits
  |
  v
Verification
  |
  v
Reviewable proposal
  |
  v
Approval + apply
  |
  v
Trace + memory + audit
```

Sprout is designed so that project-changing work remains inspectable. A human can review what changed, why it changed, which checks ran, and whether the change should be applied.

## Product Capabilities

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns project-scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and applies file, process, and change operations through brokers.
- **Isolated execution and verification**: runs changes and checks in a git worktree sandbox before touching the main project.
- **Change proposals**: separates generated work from final integration with review, approval, rejection, apply, and rollback flows.
- **Project-level memory**: persists sessions, memory, knowledge, and task history so future tasks can build on past work.
- **Automatic growth**: learns from completed work and creates reviewable candidates for future improvement.
- **Unified entry points**: exposes one runtime through Python API, CLI, React web console, MCP server, gateways, and remote RPC.
- **Reusable skills**: imports and manages versioned skills through a safety-scanning broker.

## Architecture

```text
                CLI
                 |
Python API -- Runtime factory -- Web API / WebSocket
                 |
              MCP server
                 |
                 v
          Runtime and middleware
                 |
     +-----------+-----------+
     |           |           |
   Agent      Context     Security
     |           |           |
     +-----------+-----------+
                 |
            Tool registry
                 |
              Brokers
                 |
     +-----------+-----------+
     |           |           |
  Sandbox     Storage      Events
```

The runtime is the center of the system. Entry points should stay thin: they translate transport-specific input into runtime calls, then let the runtime handle context, authorization, tools, storage, tasks, proposals, and audit.

## Safety Boundary

Every risky action goes through the authorization layer: hard floor, policy, approvals, and broker checks. Changes land in a git worktree sandbox.

That sandbox isolates **change visibility**, not **privileges**. Agent processes still share the host filesystem, OS user, network, and kernel. There is no container, VM, or OS-level backend isolation boundary. Treat untrusted code accordingly.

Today the runtime assembles the file, process, and apply brokers into the agent path. Network, database, and git brokers exist, but are not yet wired into the default agent execution path.

## Technology Stack

| Area | Technology |
|---|---|
| Core language | Python 3.12+ |
| Frontend | React, Vite, Node.js 20+ |
| Web server | Starlette, Uvicorn |
| CLI | Typer |
| LLM providers | echo, OpenAI-compatible, `aiyallm` |
| MCP | MCP Python SDK |
| Orchestration | Temporal SDK |
| Local persistence | SQLite, JSONL, filesystem blobs |
| Optional lanes | Redis, Milvus, Neo4j |
| Testing | pytest, pytest-asyncio |
| Linting | Ruff |
| Packaging | uv, hatchling |

## Repository Layout

```text
src/Sprout/
├── runtime/       # Runtime, middleware, lifecycle, workspace, locks, queues, assembly
├── agent/         # Agent protocol, AgentLoop, routing, planning, execution
├── context/       # AgentContext and context building
├── memory/        # Memory composition, budgets, snapshots, persistence
├── session/       # Sessions and turns
├── message/       # Unified messages, attachments, conversion
├── llm/           # Model providers
├── tools/         # ToolSpec, gated executor, registry, system tools
├── security/      # Risk levels, policy, approvals
├── execution/     # Change application and broker adapters
├── sandbox/       # Git worktree sandbox
├── storage/       # Storage contracts and local implementations
├── rootstock/     # Session/root persistence backends
├── strategy/      # Requirement intake, impact analysis, verification plans
├── evolution/     # Growth layer, replay, maintenance, trajectory growth
├── skills/        # Versioned skills and skill repository
├── gateway/       # Runtime, RPC, task, daemon, and transport gateways
├── orchestration/ # Temporal terminal, worker, workflows
├── cli/           # sprout command line
└── mcp/           # MCP server, client, adapters

web/
├── frontend/      # Vite + React web console
└── webapi/        # Starlette HTTP/WebSocket application

assets/            # Logo and shared static assets
```

## Installation

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

The default configuration is local-first and offline-friendly: the `echo` model provider, local SQLite databases, and no external MCP clients.

To use the `aiyallm` provider:

```bash
pip install aiyallm
```

## Quick Start

Start with the CLI:

```bash
uv run sprout --help
uv run sprout
uv run sprout chat "hello"
uv run sprout info
```

Open a workspace and inspect it:

```bash
uv run sprout project workspace .
uv run sprout project analyze
uv run sprout project symbols
uv run sprout project knowledge "storage"
```

Initialize and check storage:

```bash
uv run sprout db init
uv run sprout db status
uv run sprout storage check
```

Run the web console:

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Open `http://127.0.0.1:8000`.

## Python API

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

## Common Commands

```bash
uv run sprout --help
uv run sprout chat "hello"
uv run sprout serve
uv run sprout stop serve

uv run sprout project workspace <path>
uv run sprout project analyze
uv run sprout project task-create <workspace-id> "fix the failing tests"
uv run sprout project changes <task-id>
uv run sprout project approve <proposal-id>
uv run sprout project apply <proposal-id>

uv run sprout approvals list
uv run sprout approvals approve <approval-id>
uv run sprout approvals reject <approval-id>

uv run sprout skills import ~/code/my-skills
uv run sprout skills list
uv run sprout skills index --rebuild

uv run sprout mcp inspect
uv run sprout mcp serve

uv run sprout audit tail
uv run sprout audit verify
uv run sprout security check
```

## Storage

Sprout fans out across six storage lanes:

- SQLite for local relational state.
- JSONL for evidence and append-only records.
- Filesystem blobs for large payloads.
- Redis for cache-oriented lanes.
- Milvus for vector search.
- Neo4j for graph-oriented knowledge.

The file-backed lanes work without external services. Redis, Milvus, and Neo4j use the bundled Docker templates when enabled.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

`db init` creates configured lanes and required schemas. `db status` reports health per lane. Storage lifecycle details and Docker notes live in `~/.sprout/docker/README.md`.

## Configuration

User configuration lives at `~/.sprout/sprout.toml`. Keep one canonical user config file; use `SPROUT_CONFIG` only when you need to point at a different explicit path.

Example model configuration:

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"
base_url = "https://your-provider.example/v1"

[web]
host = "127.0.0.1"
port = 8000

[evolution]
approval_required = true
```

Secrets are read from environment variables, not from the configuration file.

## MCP Server

Run the MCP server over stdio:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

Inspect exposed tools, resources, and prompts:

```bash
uv run sprout mcp inspect
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "seam-sprout": {
      "command": "/Users/jason/SEAM_Sprout/.venv/bin/python",
      "args": ["-m", "Sprout.cli.app", "mcp", "serve"],
      "cwd": "/Users/jason/SEAM_Sprout"
    }
  }
}
```

Use `sprout-mcp` as the command when Sprout is installed on the target machine.
For repository-local development, the `.venv/bin/python -m Sprout.cli.app mcp serve`
form is more explicit and easier for other agents to inherit.

The MCP surface is intentionally conservative. It exposes safe operations such as sending messages, creating sessions, reading history, listing skills, and searching knowledge. High-risk writes, approval decisions, and growth publishing stay outside the MCP surface.

The stdio server starts protocol-first: it registers tools, resources, and prompts
without requiring Temporal, Docker, or writable storage during the initial MCP
handshake. Runtime and storage are assembled lazily when an operation actually
needs them.

## Temporal Orchestration

Task queues, scheduled work, evolution automation, web jobs, and gateway work can run on Temporal.

Start the bundled local Temporal stack:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Check connectivity:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## Development

```bash
uv run pytest
uv run ruff check .
```

Build the web frontend:

```bash
cd web/frontend
npm install
npm run build
```

See [guidance.md](guidance.md) for repository-specific development workflow, layering rules, and CLI/MCP exposure rules.

## Contributors

Thanks to everyone who has contributed to SEAM Sprout:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## License

This project is licensed under the [MIT License](LICENSE).

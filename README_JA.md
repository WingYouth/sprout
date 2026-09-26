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
  プロジェクト意図を検証可能・レビュー可能・追跡可能なソフトウェア変更へ変える、組み込み AI Engineering Runtime。
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## 概要

SEAM Sprout は、ソフトウェアプロジェクト内部に組み込む AI Engineering Runtime です。ユーザーの意図からコード編集、隔離実行、検証、approval、統合、traceability までをつなぎます。

Sprout は chat wrapper ではありません。プロジェクト側 runtime として、AI agent が repository evidence を読み、作業を計画し、git worktree sandbox でコードを変更し、checks を実行し、reviewable proposals を生成し、何が起きたかを記録できるようにします。Python API、CLI、web console、gateways、MCP server は同じ runtime を共有します。

考え方は単純です。AI 生成コードは model response から直接プロジェクトへ入るべきではありません。project context、risk controls、verification、human review、audit trail を通るべきです。

## Sprout が解決すること

Sprout は「モデルが答えを出した」と「プロジェクトに信頼できる変更が入った」の間にあるギャップを扱います。多くの AI coding workflow はここで壊れます。

| 実際の痛み | 難しい理由 | Sprout の答え |
|---|---|---|
| **AI answers, but engineering work is unfinished** | A snippet still has to land in the right files, fit architecture, pass tests, and survive conflicts. | Turns natural-language intent into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered** | Useful context lives across source, tests, docs, schemas, prior sessions, logs, and project preferences. | Builds context from scans, sessions, memory, knowledge, storage evidence, and task history. |
| **Generated code is plausible but unproven** | LLM output may look correct before running in the target environment. | Runs edits and checks inside a git worktree sandbox and attaches verification evidence. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network/database access, and git operations have different blast radii. | Routes sensitive operations through risk classification, policy, approvals, and brokers. |
| **Maintenance piles up** | Bugs, refactors, tests, docs, dependencies, and interfaces require ongoing work. | Supports tasks, proposals, approval flows, verification, and growth candidates. |
| **Learning does not compound** | Fixes and conventions disappear if they only live in chat history. | Persists memory, trajectories, task history, knowledge, and versioned skills. |
| **Entry points drift** | CLI, Web, API, gateway, and MCP can develop different behavior and permissions. | Sends every surface through `create_runtime()` with shared storage, security, events, and tools. |
| **Storage and infrastructure are hard to trust** | State may live across relational, append-only, blob, vector, graph, and cache stores. | Provides init, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## 中心ワークフロー

```text
ユーザーリクエスト
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
検証
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

Sprout は変更を inspectable に保ちます。人は何が変わったか、なぜ変わったか、どの checks が走ったか、apply すべきかを確認できます。

## プロダクト能力

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and executes operations through brokers.
- **隔離実行と検証**：git worktree sandbox で変更と checks を実行します。
- **Change proposals**：生成された作業と最終統合を分離し、review、approval、rejection、apply、rollback を扱います。
- **Project-level memory**: persists sessions, memory, knowledge, and task history.
- **Automatic growth**: learns from completed work and creates reviewable candidates.
- **統一された entry points**：Python API、CLI、React Web console、MCP server、gateways、remote RPC から同じ runtime を公開します。
- **再利用可能な skills**：safety scanning broker を通して versioned skills を import・管理します。

## アーキテクチャ

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

runtime はシステムの中心です。entry point は薄く保ち、transport input を runtime calls に変換します。context、authorization、tools、storage、tasks、proposals、audit は runtime が扱います。

## 安全境界

すべての risky action は authorization layer を通ります：hard floor、policy、approvals、broker checks。変更は git worktree sandbox に入ります。

That sandbox isolates **change visibility**, not **privileges**. Agent processes still share the host filesystem, OS user, network, and kernel. Sprout does not provide container, VM, or OS-level backend isolation.

現在 runtime が組み立てるのは file、process、apply brokers です。Network、database、git brokers は存在しますが、default agent execution path にはまだ接続されていません。

## 技術スタック

| 領域 | 技術 |
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

## リポジトリ構成

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

## インストール

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

デフォルト設定は local-first で offline-friendly です：`echo` provider、ローカル SQLite、外部 MCP client なし。

`aiyallm` を使う場合：

```bash
pip install aiyallm
```

## クイックスタート

```bash
uv run sprout --help
uv run sprout
uv run sprout chat "hello"
uv run sprout info

uv run sprout project workspace .
uv run sprout project analyze
uv run sprout project symbols
uv run sprout project knowledge "storage"

uv run sprout db init
uv run sprout db status
uv run sprout storage check
```

Web console を実行：

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

`http://127.0.0.1:8000` を開きます。

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

すべての entry point は唯一の assembly path として `create_runtime()` を使います。

## よく使うコマンド

```bash
uv run sprout --help
uv run sprout chat "hello"
uv run sprout run --workspace /path/to/project "fix the failing tests"
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

npm、`npx`、IDE task、background process から Sprout を起動する場合は、process
current directory に依存しないでください。プロジェクト root を明示的に渡します：

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout fans out across six storage lanes:

- SQLite：ローカル relational state。
- JSONL：evidence と append-only records。
- Filesystem blobs：大きな payload。
- Redis：cache-oriented lanes。
- Milvus：vector search。
- Neo4j：graph-oriented knowledge。

ファイルベースの lanes は外部サービスを必要としません。Redis、Milvus、Neo4j は有効化されたときに bundled Docker templates を使います。

`db init` creates configured lanes and required schemas. `db status` reports health per lane. Storage lifecycle and Docker notes live in `~/.sprout/docker/README.md`.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## 設定

ユーザー設定は `~/.sprout/sprout.toml` にあります。canonical config はひとつに保ち、明示的に別パスを指す場合だけ `SPROUT_CONFIG` を使います。

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

Secrets は設定ファイルではなく環境変数から読みます。

## MCP Server

stdio で MCP server を実行：

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

公開される tools、resources、prompts を確認：

```bash
uv run sprout mcp inspect
```

MCP client 設定例：

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

Sprout が対象マシンにインストール済みなら `sprout-mcp` を command として使えます。ローカル開発では `.venv/bin/python -m Sprout.cli.app mcp serve` の方が明示的で、他の agents に引き継ぎやすいです。

MCP surface は意図的に保守的です。messages、sessions、history、skills、knowledge search など安全な操作だけを公開します。high-risk writes、approval decisions、growth publishing は公開しません。

stdio server は protocol-first で起動します。初期 MCP handshake では tools、resources、prompts だけを登録し、Temporal、Docker、writable storage を要求しません。

## Temporal オーケストレーション

Task queues、scheduled work、evolution automation、web jobs、gateway work は Temporal で実行できます。

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## 開発

```bash
uv run pytest
uv run ruff check .
```

Frontend のビルド：

```bash
cd web/frontend
npm install
npm run build
```

開発 workflow、layering rules、CLI/MCP exposure rules は [guidance.md](guidance.md) を参照してください。

## コントリビューター

SEAM Sprout への貢献者に感謝します：

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## ライセンス

このプロジェクトは [MIT License](LICENSE) の下で提供されています。

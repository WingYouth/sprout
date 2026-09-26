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
  프로젝트 의도를 검증 가능하고 검토 가능하며 추적 가능한 소프트웨어 변경으로 바꾸는 내장 AI Engineering Runtime.
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## 개요

SEAM Sprout는 소프트웨어 프로젝트 내부에 내장되는 AI Engineering Runtime입니다. 사용자 의도에서 코드 편집, 격리 실행, 검증, approval, 통합, traceability까지 연결합니다.

Sprout는 chat wrapper가 아닙니다. 프로젝트 쪽 runtime으로서 AI agent가 repository evidence를 읽고, 작업을 계획하고, git worktree sandbox에서 코드를 수정하고, checks를 실행하고, reviewable proposals를 만들고, 발생한 일을 기록할 수 있게 합니다. Python API, CLI, web console, gateways, MCP server는 같은 runtime을 공유합니다.

핵심 아이디어는 단순합니다. AI generated code는 model response에서 프로젝트로 바로 들어가면 안 됩니다. project context, risk controls, verification, human review, audit trail을 거쳐야 합니다.

## Sprout가 해결하는 것

Sprout는 "모델이 답을 냈다"와 "프로젝트에 신뢰할 수 있는 변경이 들어갔다" 사이의 간극에 집중합니다. 많은 AI coding workflow가 바로 여기서 깨집니다.

| 실제 프로젝트 문제 | 어려운 이유 | Sprout의 답 |
|---|---|---|
| **AI answers, but engineering work is unfinished** | A snippet still has to land in the right files, fit architecture, pass tests, and survive conflicts. | Turns natural-language intent into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered** | Useful context lives across source, tests, docs, schemas, prior sessions, logs, and project preferences. | Builds context from scans, sessions, memory, knowledge, storage evidence, and task history. |
| **Generated code is plausible but unproven** | LLM output may look correct before running in the target environment. | Runs edits and checks inside a git worktree sandbox and attaches verification evidence. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network/database access, and git operations have different blast radii. | Routes sensitive operations through risk classification, policy, approvals, and brokers. |
| **Maintenance piles up** | Bugs, refactors, tests, docs, dependencies, and interfaces require ongoing work. | Supports tasks, proposals, approval flows, verification, and growth candidates. |
| **Learning does not compound** | Fixes and conventions disappear if they only live in chat history. | Persists memory, trajectories, task history, knowledge, and versioned skills. |
| **Entry points drift** | CLI, Web, API, gateway, and MCP can develop different behavior and permissions. | Sends every surface through `create_runtime()` with shared storage, security, events, and tools. |
| **Storage and infrastructure are hard to trust** | State may live across relational, append-only, blob, vector, graph, and cache stores. | Provides init, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## 핵심 워크플로

```text
사용자 요청
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
검증
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

Sprout는 변경을 inspectable하게 유지합니다. 사람은 무엇이 바뀌었는지, 왜 바뀌었는지, 어떤 checks가 실행됐는지, apply해야 하는지 확인할 수 있습니다.

## 제품 역량

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and executes operations through brokers.
- **격리 실행과 검증**: git worktree sandbox에서 변경과 checks를 실행합니다.
- **Change proposals**: 생성된 작업과 최종 통합을 분리하고 review, approval, rejection, apply, rollback을 다룹니다.
- **Project-level memory**: persists sessions, memory, knowledge, and task history.
- **Automatic growth**: learns from completed work and creates reviewable candidates.
- **통합 entry points**: Python API, CLI, React Web console, MCP server, gateways, remote RPC가 같은 runtime을 노출합니다.
- **재사용 가능한 skills**: safety scanning broker를 통해 versioned skills를 import하고 관리합니다.

## 아키텍처

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

runtime은 시스템의 중심입니다. entry point는 얇게 유지되어 transport input을 runtime calls로 바꿉니다. context, authorization, tools, storage, tasks, proposals, audit는 runtime이 처리합니다.

## 안전 경계

모든 risky action은 authorization layer를 통과합니다: hard floor, policy, approvals, broker checks. 변경은 git worktree sandbox에 들어갑니다.

That sandbox isolates **change visibility**, not **privileges**. Agent processes still share the host filesystem, OS user, network, and kernel. Sprout does not provide container, VM, or OS-level backend isolation.

현재 runtime은 file, process, apply brokers를 조립합니다. Network, database, git brokers는 존재하지만 아직 default agent execution path에는 연결되지 않았습니다.

## 기술 스택

| 영역 | 기술 |
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

## 저장소 구조

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

## 설치

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

기본 설정은 local-first이고 offline-friendly합니다: `echo` provider, 로컬 SQLite, 외부 MCP client 없음.

`aiyallm` 사용:

```bash
pip install aiyallm
```

## 빠른 시작

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

Web console 실행:

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

`http://127.0.0.1:8000`을 여세요.

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

모든 entry point는 유일한 assembly path로 `create_runtime()`을 사용합니다.

## 자주 쓰는 명령

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

- SQLite: 로컬 relational state.
- JSONL: evidence 및 append-only records.
- Filesystem blobs: 큰 payload.
- Redis: cache-oriented lanes.
- Milvus: vector search.
- Neo4j: graph-oriented knowledge.

파일 기반 lanes는 외부 서비스가 필요 없습니다. Redis, Milvus, Neo4j는 활성화되면 bundled Docker templates를 사용합니다.

`db init` creates configured lanes and required schemas. `db status` reports health per lane. Storage lifecycle and Docker notes live in `~/.sprout/docker/README.md`.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## 설정

사용자 설정은 `~/.sprout/sprout.toml`에 있습니다. canonical config는 하나로 유지하고, 명시적인 다른 경로가 필요할 때만 `SPROUT_CONFIG`를 사용하세요.

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

Secrets는 설정 파일이 아니라 환경 변수에서 읽습니다.

## MCP Server

stdio로 MCP server 실행:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

노출되는 tools, resources, prompts 확인:

```bash
uv run sprout mcp inspect
```

MCP client 설정 예시:

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

대상 머신에 Sprout가 설치되어 있으면 `sprout-mcp`를 command로 사용할 수 있습니다. 로컬 개발에서는 `.venv/bin/python -m Sprout.cli.app mcp serve`가 더 명시적이고 다른 agents가 이어받기 쉽습니다.

MCP surface는 의도적으로 보수적입니다. messages, sessions, history, skills, knowledge search 같은 안전한 작업만 노출합니다. high-risk writes, approval decisions, growth publishing은 제외됩니다.

stdio server는 protocol-first로 시작합니다. 초기 MCP handshake에서는 tools, resources, prompts만 등록하며 Temporal, Docker, writable storage를 요구하지 않습니다.

## Temporal 오케스트레이션

Task queues, scheduled work, evolution automation, web jobs, gateway work는 Temporal에서 실행할 수 있습니다.

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## 개발

```bash
uv run pytest
uv run ruff check .
```

Frontend 빌드:

```bash
cd web/frontend
npm install
npm run build
```

개발 workflow, layering rules, CLI/MCP exposure rules는 [guidance.md](guidance.md)를 참고하세요.

## 기여자

SEAM Sprout에 기여한 모든 분께 감사합니다:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 라이선스

이 프로젝트는 [MIT License](LICENSE)에 따라 라이선스됩니다.

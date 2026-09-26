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
  Встроенный AI Engineering Runtime, который превращает намерение проекта в проверяемые, рецензируемые и отслеживаемые изменения.
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## Обзор

SEAM Sprout — это AI Engineering Runtime, встроенный внутрь программного проекта. Он проводит изменение от намерения пользователя до правок кода, изолированного выполнения, проверки, approval, интеграции и трассируемости.

Sprout не является chat wrapper. Это runtime на стороне проекта: AI agent может читать evidence репозитория, планировать работу, менять код в git worktree sandbox, запускать checks, создавать reviewable proposals и записывать, что произошло. Python API, CLI, web console, gateways и MCP server используют один runtime.

Идея проста: код, сгенерированный ИИ, не должен напрямую попадать из ответа модели в проект. Он должен пройти через project context, risk controls, verification, human review и audit trail.

## Что решает Sprout

Sprout закрывает разрыв между "модель дала ответ" и "в проекте появилось надежное изменение". Именно там часто ломаются AI coding workflows.

| Реальная боль проекта | Почему это сложно | Ответ Sprout |
|---|---|---|
| **AI answers, but engineering work is unfinished** | A snippet still has to land in the right files, fit architecture, pass tests, and survive conflicts. | Turns natural-language intent into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered** | Useful context lives across source, tests, docs, schemas, prior sessions, logs, and project preferences. | Builds context from scans, sessions, memory, knowledge, storage evidence, and task history. |
| **Generated code is plausible but unproven** | LLM output may look correct before running in the target environment. | Runs edits and checks inside a git worktree sandbox and attaches verification evidence. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network/database access, and git operations have different blast radii. | Routes sensitive operations through risk classification, policy, approvals, and brokers. |
| **Maintenance piles up** | Bugs, refactors, tests, docs, dependencies, and interfaces require ongoing work. | Supports tasks, proposals, approval flows, verification, and growth candidates. |
| **Learning does not compound** | Fixes and conventions disappear if they only live in chat history. | Persists memory, trajectories, task history, knowledge, and versioned skills. |
| **Entry points drift** | CLI, Web, API, gateway, and MCP can develop different behavior and permissions. | Sends every surface through `create_runtime()` with shared storage, security, events, and tools. |
| **Storage and infrastructure are hard to trust** | State may live across relational, append-only, blob, vector, graph, and cache stores. | Provides init, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## Основной процесс

```text
Запрос пользователя
  |
  v
Данные проекта + memory
  |
  v
План + классификация риска
  |
  v
Sandboxed code edits
  |
  v
Проверка
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

Sprout делает изменения инспектируемыми: человек видит, что изменилось, почему, какие checks были запущены и стоит ли применять изменение.

## Возможности продукта

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and executes operations through brokers.
- **Изолированное выполнение и проверка**: запускает изменения и checks в git worktree sandbox.
- **Change proposals**: отделяет сгенерированную работу от финальной интеграции: review, approval, rejection, apply и rollback.
- **Project-level memory**: persists sessions, memory, knowledge, and task history.
- **Automatic growth**: learns from completed work and creates reviewable candidates.
- **Единые входы**: один runtime доступен через Python API, CLI, React Web console, MCP server, gateways и remote RPC.
- **Переиспользуемые skills**: импортирует и управляет versioned skills через broker для safety scanning.

## Архитектура

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

Runtime находится в центре системы. Входы остаются тонкими: они переводят transport input в вызовы runtime; runtime управляет context, authorization, tools, storage, tasks, proposals и audit.

## Граница безопасности

Каждое рискованное действие проходит слой авторизации: hard floor, policy, approvals и broker checks. Изменения попадают в git worktree sandbox.

That sandbox isolates **change visibility**, not **privileges**. Agent processes still share the host filesystem, OS user, network, and kernel. Sprout does not provide container, VM, or OS-level backend isolation.

Сегодня runtime собирает file, process и apply brokers. Network, database и git brokers существуют, но еще не подключены к agent execution path по умолчанию.

## Технологии

| Область | Технология |
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

## Структура репозитория

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

## Установка

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

Конфигурация по умолчанию local-first и удобна offline: provider `echo`, локальный SQLite и без внешних MCP clients.

Для `aiyallm`:

```bash
pip install aiyallm
```

## Быстрый старт

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

Запустить web console:

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Откройте `http://127.0.0.1:8000`.

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

Все входы используют `create_runtime()` как единственный путь сборки.

## Основные команды

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

Когда Sprout запускается из npm, `npx`, IDE task или background process, не
полагайтесь на process current directory. Передавайте корень проекта явно:

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout fans out across six storage lanes:

- SQLite для локального relational state.
- JSONL для evidence и append-only records.
- Filesystem blobs для больших payloads.
- Redis для cache-oriented lanes.
- Milvus для vector search.
- Neo4j для graph-oriented knowledge.

Файловые lanes не требуют внешних сервисов. Redis, Milvus и Neo4j используют bundled Docker templates, когда включены.

`db init` creates configured lanes and required schemas. `db status` reports health per lane. Storage lifecycle and Docker notes live in `~/.sprout/docker/README.md`.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## Конфигурация

Пользовательская конфигурация находится в `~/.sprout/sprout.toml`. Держите один canonical config; используйте `SPROUT_CONFIG` только для явного пути.

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

Secrets читаются из переменных окружения, а не из файла конфигурации.

## MCP Server

Запустите MCP server через stdio:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

Посмотреть exposed tools, resources и prompts:

```bash
uv run sprout mcp inspect
```

Пример конфигурации MCP client:

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

Используйте `sprout-mcp` как command, когда Sprout установлен на целевой машине. Для локальной разработки `.venv/bin/python -m Sprout.cli.app mcp serve` явнее и удобнее для других agents.

MCP surface намеренно консервативна: доступны безопасные операции вроде messages, sessions, history, skills и knowledge search. High-risk writes, approval decisions и growth publishing остаются вне MCP.

stdio server запускается protocol-first: регистрирует tools, resources и prompts без требования Temporal, Docker или writable storage на начальном MCP handshake.

## Оркестрация Temporal

Task queues, scheduled work, evolution automation, web jobs и gateway work могут работать в Temporal.

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## Разработка

```bash
uv run pytest
uv run ruff check .
```

Сборка frontend:

```bash
cd web/frontend
npm install
npm run build
```

См. [guidance.md](guidance.md) для workflow разработки, правил слоев и CLI/MCP exposure.

## Участники

Спасибо всем, кто внес вклад в SEAM Sprout:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Лицензия

Проект распространяется по [MIT License](LICENSE).

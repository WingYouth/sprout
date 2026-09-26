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
  Um AI Engineering Runtime embutido no projeto para transformar intenção em mudanças verificáveis, revisáveis e rastreáveis.
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## Visão geral

SEAM Sprout é um AI Engineering Runtime embutido dentro de um projeto de software. Ele leva uma mudança da intenção do usuário até edição de código, execução isolada, verificação, aprovação, integração e rastreabilidade.

Sprout não é um wrapper de chat. É o runtime do lado do projeto: permite que um AI agent leia evidências do repositório, planeje trabalho, modifique código em um git worktree sandbox, execute checks, produza proposals revisáveis e registre o que aconteceu. Python API, CLI, web console, gateways e MCP server compartilham o mesmo runtime.

A ideia central é simples: código gerado por IA não deve saltar direto da resposta do modelo para o projeto. Ele deve passar por contexto do projeto, controles de risco, verificação, revisão humana e audit trail.

## O que o Sprout resolve

Sprout foca na lacuna entre "o modelo deu uma resposta" e "o projeto tem uma mudança confiável". É aí que muitos fluxos de AI coding quebram.

| Dor real do projeto | Por que é difícil | Resposta do Sprout |
|---|---|---|
| **AI answers, but engineering work is unfinished** | A snippet still has to land in the right files, fit architecture, pass tests, and survive conflicts. | Turns natural-language intent into executable tasks with planning, patches, checks, proposals, and formal apply. |
| **Context is scattered** | Useful context lives across source, tests, docs, schemas, prior sessions, logs, and project preferences. | Builds context from scans, sessions, memory, knowledge, storage evidence, and task history. |
| **Generated code is plausible but unproven** | LLM output may look correct before running in the target environment. | Runs edits and checks inside a git worktree sandbox and attaches verification evidence. |
| **Risky actions need enforceable boundaries** | File writes, process execution, network/database access, and git operations have different blast radii. | Routes sensitive operations through risk classification, policy, approvals, and brokers. |
| **Maintenance piles up** | Bugs, refactors, tests, docs, dependencies, and interfaces require ongoing work. | Supports tasks, proposals, approval flows, verification, and growth candidates. |
| **Learning does not compound** | Fixes and conventions disappear if they only live in chat history. | Persists memory, trajectories, task history, knowledge, and versioned skills. |
| **Entry points drift** | CLI, Web, API, gateway, and MCP can develop different behavior and permissions. | Sends every surface through `create_runtime()` with shared storage, security, events, and tools. |
| **Storage and infrastructure are hard to trust** | State may live across relational, append-only, blob, vector, graph, and cache stores. | Provides init, status checks, and verifiable read/write paths across SQLite, JSONL, blobs, Redis, Milvus, and Neo4j. |

## Fluxo central

```text
Solicitação do usuário
  |
  v
Evidência do projeto + memory
  |
  v
Plano + classificação de risco
  |
  v
Sandboxed code edits
  |
  v
Verificação
  |
  v
Proposal revisável
  |
  v
Approval + apply
  |
  v
Trace + memory + audit
```

Sprout mantém mudanças inspecionáveis: uma pessoa pode ver o que mudou, por que mudou, quais checks rodaram e se a mudança deve ser aplicada.

## Capacidades do produto

- **Project evidence first**: reads repository structure, code context, sessions, memory, knowledge, and storage evidence before acting.
- **Reviewable planning**: turns scan suggestions or direct requests into evidence-backed implementation plans.
- **Controlled code generation**: creates real patches and executes operations through brokers.
- **Execução isolada e verificação**: executa mudanças e checks em um git worktree sandbox.
- **Change proposals**: separa o trabalho gerado da integração final com review, approval, rejection, apply e rollback.
- **Project-level memory**: persists sessions, memory, knowledge, and task history.
- **Automatic growth**: learns from completed work and creates reviewable candidates.
- **Entradas unificadas**: expõe um runtime por Python API, CLI, React Web console, MCP server, gateways e remote RPC.
- **Skills reutilizáveis**: importa e gerencia versioned skills com um broker de safety scanning.

## Arquitetura

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

O runtime é o centro do sistema. As entradas ficam leves: traduzem input de transporte em chamadas de runtime; o runtime cuida de contexto, autorização, tools, storage, tasks, proposals e audit.

## Limite de segurança

Toda ação de risco passa pela camada de autorização: hard floor, policy, approvals e broker checks. As mudanças ficam em um git worktree sandbox.

That sandbox isolates **change visibility**, not **privileges**. Agent processes still share the host filesystem, OS user, network, and kernel. Sprout does not provide container, VM, or OS-level backend isolation.

Hoje o runtime monta os brokers file, process e apply. Network, database e git brokers existem, mas ainda não estão ligados ao agent execution path padrão.

## Stack tecnológico

| Área | Tecnologia |
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

## Estrutura do repositório

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

## Instalação

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

A configuração padrão é local-first e amigável offline: provider `echo`, SQLite local e nenhum cliente MCP externo.

Para usar `aiyallm`:

```bash
pip install aiyallm
```

## Início rápido

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

Executar o web console:

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Abra `http://127.0.0.1:8000`.

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

Todas as entradas usam `create_runtime()` como caminho único de montagem.

## Comandos comuns

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

Quando Sprout for iniciado por npm, `npx`, uma tarefa de IDE ou um processo em
background, não dependa do current directory do processo. Passe a raiz do
projeto explicitamente:

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout fans out across six storage lanes:

- SQLite para estado relacional local.
- JSONL para evidência e registros append-only.
- Filesystem blobs para payloads grandes.
- Redis para lanes orientadas a cache.
- Milvus para vector search.
- Neo4j para graph-oriented knowledge.

As lanes baseadas em arquivos não precisam de serviços externos. Redis, Milvus e Neo4j usam os Docker templates incluídos quando habilitados.

`db init` creates configured lanes and required schemas. `db status` reports health per lane. Storage lifecycle and Docker notes live in `~/.sprout/docker/README.md`.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## Configuração

A configuração do usuário fica em `~/.sprout/sprout.toml`. Mantenha um único config canônico; use `SPROUT_CONFIG` apenas para apontar para um caminho explícito.

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

Secrets são lidos de variáveis de ambiente, não do arquivo de configuração.

## MCP Server

Execute o MCP server sobre stdio:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

Inspecione tools, resources e prompts expostos:

```bash
uv run sprout mcp inspect
```

Exemplo de configuração MCP client:

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

Use `sprout-mcp` como command quando Sprout estiver instalado na máquina alvo. Para desenvolvimento local, `.venv/bin/python -m Sprout.cli.app mcp serve` é mais explícito e fácil para outros agents herdarem.

A MCP surface é conservadora: expõe operações seguras como mensagens, sessions, history, skills e knowledge search. Escritas de alto risco, approval decisions e growth publishing ficam fora.

O server stdio inicia protocol-first: registra tools, resources e prompts sem exigir Temporal, Docker ou storage gravável durante o handshake inicial.

## Orquestração com Temporal

Task queues, scheduled work, evolution automation, web jobs e gateway work podem rodar no Temporal.

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## Desenvolvimento

```bash
uv run pytest
uv run ruff check .
```

Construir o frontend:

```bash
cd web/frontend
npm install
npm run build
```

Veja [guidance.md](guidance.md) para workflow de desenvolvimento, regras de camadas e exposição CLI/MCP.

## Contribuidores

Obrigado a todos que contribuíram para o SEAM Sprout:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Licença

Este projeto é licenciado sob a [MIT License](LICENSE).

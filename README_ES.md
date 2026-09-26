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
  Un AI Engineering Runtime integrado en el proyecto para convertir intención en cambios verificables, revisables y trazables.
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## Resumen

SEAM Sprout es un AI Engineering Runtime integrado dentro de un proyecto de software. Lleva un cambio desde la intención del usuario hasta ediciones de código, ejecución aislada, verificación, aprobación, integración y trazabilidad.

Sprout no es un wrapper de chat. Es el runtime del lado del proyecto: permite que un AI agent lea evidencia del repositorio, planifique trabajo, modifique código en un git worktree sandbox, ejecute checks, produzca proposals revisables y registre lo ocurrido. Python API, CLI, web console, gateways y MCP server comparten el mismo runtime.

La idea central es simple: el código generado por IA no debe saltar directo desde una respuesta del modelo al proyecto. Debe pasar por contexto del proyecto, controles de riesgo, verificación, revisión humana y audit trail.

## Qué resuelve Sprout

Sprout se enfoca en la brecha entre "el modelo dio una respuesta" y "el proyecto tiene un cambio confiable". Ahí es donde muchos flujos de AI coding se rompen.

| Dolor real del proyecto | Por qué es difícil | Respuesta de Sprout |
|---|---|---|
| **La IA responde, pero el trabajo de ingeniería no está terminado** | El snippet debe caer en los archivos correctos, encajar con la arquitectura, pasar tests y sobrevivir conflictos. | Convierte intención natural en tareas ejecutables con planning, patches, checks, proposals y formal apply. |
| **El contexto está disperso** | La información útil vive en código, tests, docs, storage schemas, sesiones previas, logs y preferencias del proyecto. | Construye contexto desde repository scans, sessions, memory, knowledge, storage evidence y task history. |
| **El código generado parece correcto, pero no está probado** | La salida del LLM suele revisarse antes de ejecutarse en el entorno real. | Ejecuta cambios y checks en un git worktree sandbox y adjunta evidencia de verificación al proposal. |
| **Las acciones riesgosas necesitan límites ejecutables** | File writes, process execution, network access, database access y git operations tienen distinto blast radius. | Gestiona acciones sensibles con risk classification, policy, approvals y brokers controlados. |
| **El mantenimiento se acumula** | Bugs, refactors, tests, docs, dependencias e interfaces requieren trabajo continuo. | Soporta project tasks, proposals, approval flows, verification y growth candidates. |
| **El aprendizaje no se acumula** | Fixes, convenciones y workflow knowledge se pierden si viven solo en el chat. | Persiste memory, trajectories, task history, knowledge y versioned skills. |
| **Las entradas se desalinean** | CLI, Web, API, gateway y MCP pueden divergir en comportamiento y permisos. | Todas pasan por `create_runtime()` y comparten storage, security, events y tools. |
| **Storage e infraestructura son difíciles de confiar** | Sessions, knowledge, audit, vectors, graph y cache pueden vivir en backends distintos. | Ofrece init, status checks y rutas verificables para SQLite, JSONL, blobs, Redis, Milvus y Neo4j. |

## Flujo central

```text
Solicitud del usuario
  |
  v
Evidencia del proyecto + memory
  |
  v
Plan + clasificación de riesgo
  |
  v
Sandboxed code edits
  |
  v
Verificación
  |
  v
Proposal revisable
  |
  v
Approval + apply
  |
  v
Trace + memory + audit
```

Sprout mantiene los cambios inspeccionables: una persona puede ver qué cambió, por qué cambió, qué checks corrieron y si el cambio debe aplicarse.

## Capacidades del producto

- **Evidencia primero**: lee estructura del repo, contexto de código, sessions, memory, knowledge y storage evidence antes de actuar.
- **Planning revisable**: convierte sugerencias de scan o solicitudes directas en planes respaldados por evidencia.
- **Code generation controlada**: crea patches reales y ejecuta operaciones mediante brokers.
- **Ejecución aislada y verificación**: corre cambios y checks en un git worktree sandbox.
- **Change proposals**: separa el trabajo generado de la integración final con review, approval, rejection, apply y rollback.
- **Memory de proyecto**: persiste sessions, memory, knowledge y task history.
- **Crecimiento automático**: aprende del trabajo completado y crea candidates revisables.
- **Entradas unificadas**: expone un runtime por Python API, CLI, React Web console, MCP server, gateways y remote RPC.
- **Skills reutilizables**: importa y gestiona versioned skills con un broker de safety scanning.

## Arquitectura

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

El runtime es el centro del sistema. Las entradas se mantienen delgadas: traducen input de transporte a llamadas de runtime; el runtime maneja contexto, autorización, tools, storage, tasks, proposals y audit.

## Límite de seguridad

Toda acción riesgosa pasa por la capa de autorización: hard floor, policy, approvals y broker checks. Los cambios aterrizan en un git worktree sandbox.

Ese sandbox aísla **visibilidad del cambio**, no **privilegios**. Los procesos del agent comparten filesystem, OS user, network y kernel del host. Sprout no ofrece aislamiento de container, VM ni backend a nivel de OS.

Hoy el runtime ensambla los brokers file, process y apply. Network, database y git brokers existen, pero aún no están conectados al agent execution path por defecto.

## Stack tecnológico

| Área | Tecnología |
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

## Estructura del repositorio

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

## Instalación

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

La configuración por defecto es local-first y amigable offline: provider `echo`, SQLite local y sin clientes MCP externos.

Para usar `aiyallm`:

```bash
pip install aiyallm
```

## Inicio rápido

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

Ejecutar la web console:

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Abre `http://127.0.0.1:8000`.

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

Todas las entradas usan `create_runtime()` como ruta única de ensamblaje.

## Comandos comunes

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

Cuando Sprout se lanza desde npm, `npx`, una tarea de IDE o un proceso en
background, no dependas del current directory del proceso. Pasa la raíz del
proyecto explícitamente:

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout se divide en seis storage lanes:

- SQLite para estado relacional local.
- JSONL para evidencia y registros append-only.
- Filesystem blobs para payloads grandes.
- Redis para lanes orientadas a cache.
- Milvus para vector search.
- Neo4j para graph-oriented knowledge.

Las lanes basadas en archivos no necesitan servicios externos. Redis, Milvus y Neo4j usan los Docker templates incluidos cuando están habilitados.

`db init` crea lanes configuradas y schemas requeridos. `db status` reporta salud por lane. Detalles en `~/.sprout/docker/README.md`.

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## Configuración

La configuración de usuario vive en `~/.sprout/sprout.toml`. Mantén un solo config canónico; usa `SPROUT_CONFIG` solo para apuntar a una ruta explícita.

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

Los secrets se leen desde variables de entorno, no desde el archivo de configuración.

## MCP Server

Ejecuta el MCP server sobre stdio:

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

Inspecciona tools, resources y prompts expuestos:

```bash
uv run sprout mcp inspect
```

Ejemplo de configuración MCP client:

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

Usa `sprout-mcp` como command cuando Sprout esté instalado en la máquina objetivo. Para desarrollo local, `.venv/bin/python -m Sprout.cli.app mcp serve` es más explícito y fácil de heredar por otros agents.

La MCP surface es conservadora: expone operaciones seguras como mensajes, sessions, history, skills y knowledge search. Escrituras de alto riesgo, approval decisions y growth publishing quedan fuera.

El server stdio arranca protocol-first: registra tools, resources y prompts sin requerir Temporal, Docker ni storage escribible durante el handshake inicial.

## Orquestación con Temporal

Task queues, scheduled work, evolution automation, web jobs y gateway work pueden ejecutarse en Temporal.

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## Desarrollo

```bash
uv run pytest
uv run ruff check .
```

Construir el frontend:

```bash
cd web/frontend
npm install
npm run build
```

Consulta [guidance.md](guidance.md) para workflow de desarrollo, reglas de capas y exposición CLI/MCP.

## Contribuidores

Gracias a todas las personas que han contribuido a SEAM Sprout:

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Licencia

Este proyecto está licenciado bajo [MIT License](LICENSE).

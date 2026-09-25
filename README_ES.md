# SEAM Sprout

SEAM Sprout es un agente de IA autoevolutivo para proyectos de software. Se conecta a una base de código, comprende su estructura y contexto, genera código, lo ejecuta en un entorno aislado, verifica el resultado y luego integra los cambios.

## Características principales

- Análisis preciso del proyecto: estructura del repositorio, contexto, sesiones, memoria y conocimiento.
- Generación de código: convierte la intención en cambios concretos.
- Ejecución aislada: ejecuta el código en un sandbox de git worktree.
- Verificación de código: prueba y comprueba cada cambio antes de integrarlo.
- Integración de código: aplica cambios verificados y conserva el historial.
- Crecimiento automático: aprende del trabajo completado y crea propuestas de mejora.

## Casos de uso comerciales

- Proyectos que necesitan un ingeniero de IA integrado, no otra herramienta de chat.
- Bases de código que requieren reparación, refactorización o nuevas funciones.
- Equipos que necesitan ejecutar, probar e integrar código generado de forma segura.
- Organizaciones que requieren memoria, evolución y auditoría a nivel de proyecto.
- Las acciones peligrosas pasan por el plano de autorización. El sandbox aísla la visibilidad del cambio, no los privilegios del proceso, el usuario del sistema o la red.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Persistencia | SQLite, JSONL, Blob, memoria, Milvus/Neo4j/Redis |
| Configuración | TOML + dataclasses tipados |
| Herramientas | uv, pytest, ruff |

## Instalación

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Consola web

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Abre `http://127.0.0.1:8000`. La consola incluye chat, tablero de tareas, gestión de tareas, tokens, almacenamiento, registros y ajustes.

API HTTP principal:

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/tasks` / `POST /api/tasks`
- `GET /api/tokens`
- `GET /api/logs`
- `GET /api/storage/status`
- `GET /api/storage/graph/status`
- `GET /api/health`

## CLI

```bash
uv run sprout --help
uv run sprout
uv run sprout chat "hello"
uv run sprout serve
uv run sprout stop serve
```

### Idioma de la CLI

```text
/language
/language ja
/language zh-Hant
```

Consulta los idiomas compatibles en `src/Sprout/cli/i18n_languages.md`.

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## Configuración

La configuración vive en `~/.sprout/sprout.toml`. No agregues un `sprout.toml` local duplicado en el proyecto.

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## Desarrollo

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## Estructura del proyecto

```text
src/Sprout/
├── runtime/       # Runtime, middleware, ciclo de vida, workspace
├── agent/         # Protocolo de agente y AgentLoop
├── session/       # Modelos de sesión y turno
├── memory/        # Memoria, presupuestos y snapshots
├── context/       # AgentContext y construcción de contexto
├── message/       # Mensajes unificados y conversión
├── llm/           # Proveedores de modelos
├── tools/         # ToolSpec y ejecutor seguro
├── skills/        # Skills versionados
├── security/      # Riesgo, política y aprobación
├── storage/       # Contratos de almacenamiento
├── evolution/     # Plano de crecimiento
├── execution/     # Aplicación de cambios
├── gateway/       # Gateways de runtime, RPC y tareas
├── orchestration/ # Compilador de grafos y worker Temporal
├── rootstock/     # Backends de persistencia de sesión
├── sandbox/       # Sandbox de git worktree
├── task/          # Modelos de tarea
├── trajectory/    # Persistencia de trayectoria
├── workspace/     # Helpers de workspace
├── config/        # Ajustes y TOML
├── cli/           # Línea de comandos sprout
└── mcp/           # Servidor y cliente MCP

web/
├── frontend/      # Consola Vite + React
└── webapi/        # Aplicación Starlette HTTP/WebSocket
```

## Seis bases de datos

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite, JSONL y Blob son archivos normales. Redis, Milvus y Neo4j pueden configurarse como contenedores. Consulta `~/.sprout/docker/README.md`.

## API del agente Python

```python
import asyncio
from Sprout.config.defaults import default_settings
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime

async def main():
    runtime = create_runtime(default_settings())
    async with runtime:
        reply = await runtime.handle(Message("hello", channel="python"))
        print(reply.content)

asyncio.run(main())
```

## MCP

```bash
uv run sprout mcp serve
# o
sprout-mcp
```

Herramientas expuestas:

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

## Configuración de un modelo real

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
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"

[evolution]
approval_required = true
```

## Contribuidores

| Contribuidor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Licencia

[MIT License](LICENSE)

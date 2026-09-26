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

SEAM Sprout es un AI Engineering Runtime integrado dentro de un proyecto de software. Lleva un cambio desde la intención del usuario hasta ediciones de código, ejecución aislada, verificación, aprobación, integración y trazabilidad, para que la IA no solo sugiera, sino que complete un ciclo de ingeniería controlado y revisable dentro del límite del proyecto.

El problema central que resuelve Sprout es que el trabajo real de software está lleno de cambios pequeños pero importantes, mientras el contexto está disperso, el riesgo es difícil de controlar, la verificación consume tiempo y el conocimiento ganado rara vez se reutiliza. Sprout reúne codebase, sesiones, memoria, conocimiento, herramientas, aprobaciones y audit trail en un solo runtime para que un proyecto pueda mantenerse, repararse y mejorar continuamente con las acciones peligrosas bajo control humano.

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Qué resuelve Sprout

Sprout está pensado para entrega de cambios a nivel de proyecto, no para preguntas aisladas sobre código. Coloca la IA dentro de una pipeline controlada: leer evidencia del proyecto, construir un plan, modificar código en un worktree aislado, ejecutar checks, producir una propuesta revisable y aplicar el resultado aprobado de vuelta al proyecto con trazabilidad.

| Dolor real del proyecto | Por qué es difícil | Respuesta de Sprout |
|---|---|---|
| **La IA da una respuesta, pero el trabajo de ingeniería sigue incompleto** | Un snippet debe aterrizar en los archivos correctos, encajar con el diseño existente, pasar pruebas y sobrevivir conflictos. | Convierte solicitudes en lenguaje natural en tareas ejecutables con planificación, patches, checks, propuestas y apply formal. |
| **El contexto está disperso entre código, datos, docs y conversaciones previas** | Las buenas decisiones dependen de la estructura del repo, interfaces, storage schema, decisiones históricas y el objetivo actual. | Combina project scans, sesiones, memoria, conocimiento y storage evidence dentro de un runtime. |
| **El código generado parece correcto, pero no está probado** | La salida del LLM suele revisarse antes de ejecutarse en el entorno objetivo. | Ejecuta cambios y checks en un git-worktree sandbox y adjunta la evidencia de verificación a la propuesta. |
| **Las acciones de riesgo necesitan límites exigibles** | File writes, process execution, network access y database access pueden romper sistemas, filtrar secretos o saltarse ownership. | Enruta acciones peligrosas por risk levels, policies, approvals y brokers controlados. |
| **El trabajo de mantenimiento se acumula** | Bugs pequeños, drift de documentación, desajustes de interfaces, refactors y pruebas faltantes importan, pero se posponen. | Escanea, repara y crea growth candidates revisables para mejoras futuras. |
| **El aprendizaje no se acumula entre tareas** | Arreglos, preferencias del proyecto y conocimiento de workflow se pierden en el historial de chat. | Persiste trayectorias, memoria, conocimiento y skills versionadas para mejorar trabajos futuros. |
| **Múltiples superficies se desalinean** | CLI, Web, MCP, Python API y gateways pueden terminar con comportamiento, permisos y auditoría diferentes. | Todas las superficies pasan por la misma ruta `create_runtime()`, con storage, authorization, events y audit compartidos. |
| **Storage e infraestructura son difíciles de confiar** | Sesiones, conocimiento, audit, vectores, grafo y caché pueden vivir en backends distintos. | Proporciona inicialización, status checks y rutas verificables de lectura/escritura para SQLite, JSONL, blobs, Redis, Milvus y Neo4j. |

## Capacidades del producto

- **Evidencia del proyecto primero**: lee estructura del repo, contexto de código, sesiones, memoria, conocimiento y storage evidence antes de actuar.
- **Planificación revisable**: convierte sugerencias de project scan o solicitudes directas en planes de implementación respaldados por evidencia.
- **Generación de código controlada**: crea patches reales y aplica operaciones de file, process y change mediante brokers.
- **Ejecución aislada y verificación**: ejecuta cambios y checks en un git-worktree sandbox antes de tocar el proyecto principal.
- **Integración y trazabilidad de cambios**: convierte trabajo verificado en proposals, espera approval, aplica cambios aceptados y registra el rastro completo.
- **Memoria a nivel de proyecto**: persiste sesiones, memoria, conocimiento e historial de tareas.
- **Crecimiento automático**: aprende del trabajo completado y crea candidates revisables para mejoras futuras.
- **Entradas unificadas**: expone un solo runtime mediante Python API, React web console, CLI interactiva, MCP server y gateways.
- **Skills reutilizables**: importa y gestiona skills versionadas mediante un broker de safety scanning.

## Casos de uso

- Proyectos que necesitan un AI Engineering Runtime embebido en lugar de un asistente de chat externo.
- Equipos que quieren que el código generado por IA pase por tests, approvals, audit e integración.
- Codebases con reparación continua, refactor, cobertura de tests, documentación y alineación de interfaces.
- Organizaciones que requieren memoria a nivel de proyecto, automatización trazable y capacidades reutilizables.

## Límite de seguridad

Cada acción de riesgo pasa por la authorization layer (hard floor → policy layers → approvals), y los cambios aterrizan en un git-worktree sandbox. Ese sandbox aísla la *visibilidad del cambio*, no los *privilegios*: los procesos del agente comparten filesystem, OS user, network y kernel del host, y no hay container ni OS-level backend. De los siete execution brokers, file, process y apply están ensamblados hoy en el runtime; network, database y git existen, pero aún no están conectados al agent path.

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Lenguaje | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Persistencia | SQLite, JSONL, blobs en el sistema de archivos, almacenes en memoria (Milvus, Neo4j, Redis reservados) |
| Configuración | TOML con dataclasses tipados |
| Herramientas | uv, pytest, pytest-asyncio, ruff |

## Estructura del proyecto

```text
src/Sprout/
├── runtime/       # Runtime, middleware, ciclo de vida, workspace, bloqueos, colas y ensamblado
├── agent/         # Protocolo del agente, AgentLoop, enrutado, planificación, ejecución
├── session/       # Modelos de sesión y turno
├── memory/        # Composición de memoria, presupuestos, snapshots y persistencia
├── context/       # AgentContext y construcción de contexto
├── message/       # Mensajes unificados, adjuntos y conversión
├── llm/           # Proveedores de modelos: echo, OpenAI-compatible, aiyallm
├── tools/         # ToolSpec, ejecutor con compuerta de seguridad, registro, herramientas del sistema
├── skills/        # Skills versionadas y repositorio de skills
├── security/      # Niveles de riesgo, políticas, aprobación
├── events/        # Bus de eventos en proceso
├── registry/      # Registros genéricos
├── storage/       # Contratos de almacenamiento e implementaciones locales
├── evolution/     # Capa de crecimiento, replay, mantenimiento y crecimiento de trayectoria
├── strategy/      # Descomposición de requisitos, análisis de impacto y planes de verificación
├── artifacts/     # Modelos de artefactos y metadatos
├── capability/    # Modelos de capacidades
├── execution/     # Aplicación de cambios y adaptadores de brokers
├── gateway/       # Gateways de runtime, RPC, tareas, daemon y transporte
├── orchestration/ # Compilador de grafos, terminal Temporal, worker y workflows
├── rootstock/     # Backends de persistencia de sesión/raíz
├── sandbox/       # Sandbox de git worktree
├── task/          # Modelos de tareas y ciclo de vida
├── trajectory/    # Persistencia de trayectoria
├── workspace/     # Helpers de workspace
├── config/        # Ajustes tipados y carga de TOML
├── scheduler/     # Soporte de tareas programadas
├── cli/           # Línea de comandos sprout
└── mcp/           # Servidor, cliente y adaptadores MCP

web/
├── frontend/      # Consola web Vite + React
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Aplicación Starlette HTTP/WebSocket, rutas y base de datos

assets/            # Logo compartido y recursos estáticos
~/.sprout/docker/  # Stack de seis bases de datos: archivo compose, imagen runner, bootstrap
```

## Estrategia de requisitos

`src/Sprout/strategy/` convierte una sugerencia del escaneo del proyecto o una petición directa del usuario en un plan de implementación revisable. Su `StrategyPipeline` es de solo lectura durante la etapa de planificación y produce la evidencia necesaria antes de cambiar cualquier código.

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

El análisis de impacto usa dos fuentes de evidencia:

- **Evidencia de base de datos**: acceso de solo lectura a través del broker de base de datos para comprobar esquemas, tablas, migraciones, registros persistidos e historial existente de interfaces o tareas.
- **Evidencia del proyecto**: un escaneo completo del workspace que localiza archivos fuente, interfaces, código relacionado con la base de datos y archivos de prueba, junto con relaciones del grafo del workspace cuando están disponibles.
- **Validación cruzada**: compara ambas fuentes y marca coincidencias, objetos solo de base de datos, objetos solo de código y conflictos sin resolver. Los conflictos se exponen para revisión humana en lugar de tratarse silenciosamente como permiso para editar.

La capa de estrategia es dueña de la toma de requisitos, el análisis de impacto, la selección del modo de cambio, los criterios de aceptación y la planificación de archivos de prueba. `workspace/` suministra evidencia del proyecto de solo lectura, `runtime/changes.py` es dueño de la aprobación de propuestas y del apply/rollback formal, y `execution/` es dueño de los brokers de patch, database, process y Git.

## Instalación

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

La configuración por defecto es completamente offline: el proveedor de modelo `echo`, bases de datos SQLite locales y sin clientes MCP externos.

Para el proveedor de modelo `aiyallm`, instala su distribución:

```bash
pip install aiyallm
```

### Seis bases de datos en dos comandos

El runtime se despliega en seis bases de datos. Tres son archivos simples — SQLite, el registro de evidencia JSONL y el almacén de blobs —, por lo que no necesitan instalación alguna; las otras tres (Redis, Milvus, Neo4j) son contenedores. Dos comandos cubren el ciclo de vida:

```powershell
sprout db init                    # crear/inicializar todas las lanes configuradas
sprout db status                  # informar healthy/failed por lane
sprout db backup <dir>            # respaldar las bases SQLite
sprout db restore <dir>           # restaurar las bases SQLite
```
```bash
sprout db init
sprout db status
```

`init` construye los cinco esquemas SQLite, los directorios JSONL y blob, las tres colecciones Milvus y las restricciones Neo4j — de forma idempotente y sin escribir filas. `test` escribe una sesión, dos turnos, un hecho de memoria y un snapshot de contexto sobredimensionado a través del paquete de almacenamiento normal, y luego lee de vuelta cada lane con el cliente de ese mismo lane, que es lo que convierte «las seis están arriba» en un hecho verificado y no en una afirmación. `sprout db init` inicializa todas las lanes configuradas y `sprout db status` las comprueba una a una. Con Docker, `init` también descarga las tres imágenes de servicio (con un respaldo de espejo para Docker Hub bloqueado), construye la imagen runner, arranca las lanes y las prueba.

Puertos, configuración, las tres capas de pruebas, el perfil sin Docker y la resolución de problemas viven en `~/.sprout/docker/README.md`.

## Uso

### Agent

La API de Python es la superficie de uso principal. Construye un runtime y envía un `Message`:

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

Todos los puntos de entrada usan `create_runtime()` como única ruta de ensamblado.

### Web

La consola web es una aplicación React basada en componentes construida con Vite.

Construye el frontend una vez:

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

Luego arranca la consola web:

```bash
uv run sprout serve
```

Abre `http://127.0.0.1:8000`. La aplicación web ofrece chat, un tablero de tareas, gestión de tareas y ajustes de configuración.

Para desarrollo del frontend con recarga en caliente:

```bash
cd web/frontend
npm run dev
```

Los endpoints HTTP disponibles incluyen:

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

El endpoint WebSocket está disponible en `ws://127.0.0.1:8000/ws/chat`.

### CLI

```bash
uv run sprout --help
uv run sprout                     # chat interactivo
uv run sprout chat "hello"        # mensaje de un solo disparo
uv run sprout info                # snapshot de runtime y configuración
uv run sprout project workspace <path>   # abrir un workspace local
uv run sprout remote workspace-list      # operar un servicio SEMA remoto
uv run sprout db init             # inicializar todas las lanes configuradas
uv run sprout db status           # informar healthy/failed
uv run sprout db backup ./backup  # respaldar bases locales
uv run sprout mcp inspect         # inspeccionar definiciones MCP
uv run sprout evolution candidates  # capa de crecimiento: lo que produjo el pipeline
uv run sprout skills import ~/code/my-skills   # importar skills desde un directorio local
uv run sprout skills list         # qué hay instalado
uv run sprout skills index --rebuild   # sincronizar el snapshot, informar divergencia registro/disco
uv run sprout skills forget <name>     # eliminar una fila del registro, conservar los archivos
uv run sprout serve               # consola web y API
uv run sprout stop serve          # detener la consola web
```

`skills import` recorre un directorio de forma recursiva y trata una carpeta que contiene un `SKILL.md` como una skill, y los archivos `*.toml` de archivo único como entradas propias. Encuentra diseños anidados (`skills/writing/docs/SKILL.md`), omite directorios de proveedores e instala cada skill a través del mismo broker que usa el resto del subsistema: primero escanea contenido inseguro y luego decide el motor de políticas. Como una ruta local es una fuente de primera parte, nada requiere aprobación; el suelo de hallazgos fatales del escáner sigue aplicándose y no puede superarse con una aprobación.

### Idioma de la CLI

La CLI interactiva puede cambiar el idioma del menú sin reiniciar:

```text
/language
/language ja
/language zh-Hant
```

Los idiomas admitidos están listados en [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md). La selección se guarda en `~/.sprout/settings.json` y se reutiliza en la siguiente sesión.

### Temporal

La orquestación de tareas, colas, programaciones, automatización de evolución, trabajos web y trabajo de gateways pueden ejecutarse sobre Temporal.

Arranca un servidor Temporal local con el stack Compose incluido:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Luego comprueba que es accesible sin instalar la CLI de Temporal:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` informa de la accesibilidad del servidor, la versión del servidor, la presencia del namespace y la cantidad de workers sondeando la cola de tareas configurada.

### MCP

Ejecuta el servidor MCP sobre stdio:

```bash
uv run sprout mcp serve
# o
sprout-mcp
```

El servidor expone solo operaciones seguras: enviar mensajes, crear sesiones, leer el historial de sesiones, listar skills y buscar conocimiento. Las escrituras de alto riesgo, las aprobaciones y la publicación de crecimiento permanecen fuera de la superficie MCP.

Inspecciona las herramientas, recursos y prompts expuestos:

```bash
uv run sprout mcp inspect
```

## Configuración

La configuración del usuario vive en `~/.sprout/sprout.toml`. Mantén la configuración en ese único archivo; no añadas un `sprout.toml` local duplicado en el proyecto. Usa `SPROUT_CONFIG` solo para apuntar a otra ruta explícita cuando sea necesario.

Herramientas MCP de Project Runtime:

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

Edita `~/.sprout/sprout.toml` para usar DeepSeek u otro proveedor:

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
# Authorities del runtime Sprout: sqlite | jsonl | blobstore para conversation;
# Milvus/Neo4j/Redis permanecen como capas derivadas y nunca son authorities.
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

Los secretos se leen de variables de entorno y nunca se escriben en el archivo de configuración.

## Desarrollo

```bash
uv run pytest
uv run ruff check .
```

Consulta [guidance.md](guidance.md) para el flujo de desarrollo y las reglas de exposición de CLI/MCP.

## Contribuidores

Gracias a todos los que han contribuido a SEAM Sprout:

| Contribuidor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Licencia

Este proyecto está licenciado bajo la [Licencia MIT](LICENSE).

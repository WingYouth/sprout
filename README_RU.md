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

SEAM Sprout — это AI Engineering Runtime, встроенный внутрь программного проекта. Он проводит изменение от намерения пользователя к правкам кода, изолированному выполнению, проверке, одобрению, интеграции и трассируемости, чтобы ИИ не только предлагал, но и завершал контролируемый, проверяемый engineering loop внутри границ проекта.

Главная проблема, которую решает Sprout: реальная разработка полна небольших, но важных изменений, при этом контекст разбросан, риск трудно контролировать, проверка утомительна, а накопленные знания редко переиспользуются. Sprout собирает codebase, sessions, memory, knowledge, tools, approvals и audit trail в одном runtime, чтобы проект можно было постоянно поддерживать, чинить и улучшать, оставляя опасные действия под контролем человека.

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Что решает Sprout

Sprout создан для доставки изменений на уровне проекта, а не для разовых вопросов о коде. Он помещает ИИ в контролируемую pipeline: читает evidence проекта, строит план, меняет код в изолированном worktree, запускает checks, создаёт проверяемый proposal и применяет одобренный результат обратно в проект с трассируемостью.

| Реальная боль проекта | Почему это сложно | Ответ Sprout |
|---|---|---|
| **ИИ даёт ответ, но инженерная работа не завершена** | Snippet должен попасть в правильные файлы, вписаться в существующий дизайн, пройти tests и пережить conflicts. | Превращает запросы на естественном языке в executable tasks с planning, patches, checks, proposals и formal apply. |
| **Контекст разбросан по code, data, docs и прошлым диалогам** | Хорошие решения требуют структуры repo, interfaces, storage schema, прошлых решений и текущей цели. | Объединяет project scans, sessions, memory, knowledge и storage evidence внутри одного runtime. |
| **Сгенерированный код выглядит правдоподобно, но не доказан** | LLM output часто проверяют глазами до запуска в целевой среде. | Выполняет изменения и checks в git-worktree sandbox и прикладывает verification evidence к proposal. |
| **Рискованным действиям нужны enforceable boundaries** | File writes, process execution, network access и database access могут ломать системы, раскрывать secrets или обходить ownership. | Проводит опасные действия через risk levels, policies, approvals и controlled brokers. |
| **Maintenance work копится** | Малые bugs, documentation drift, interface mismatches, refactors и missing tests важны, но легко откладываются. | Постоянно сканирует, чинит и создаёт reviewable growth candidates для будущих улучшений. |
| **Обучение не накапливается между задачами** | Исправления, предпочтения проекта и workflow knowledge исчезают в chat history. | Сохраняет trajectories, memory, knowledge и versioned skills, чтобы завершённая работа улучшала следующую. |
| **Несколько surfaces расходятся** | CLI, Web, MCP, Python API и gateways могут получить разные behavior, permissions и audit paths. | Проводит все surfaces через один путь `create_runtime()` с общими storage, authorization, events и audit. |
| **Storage и infrastructure трудно доверять** | Sessions, knowledge, audit, vectors, graph и cache могут жить в разных backends. | Даёт initialization, status checks и проверяемые read/write paths для SQLite, JSONL, blobs, Redis, Milvus и Neo4j. |

## Возможности продукта

- **Сначала evidence проекта**: читает структуру repo, context кода, sessions, memory, knowledge и storage evidence перед действием.
- **Проверяемое planning**: превращает project-scan suggestions или прямые запросы в evidence-backed implementation plans.
- **Контролируемая code generation**: создаёт реальные patches и применяет file, process и change operations через brokers.
- **Изолированное выполнение и проверка**: запускает изменения и checks в git-worktree sandbox до касания основного проекта.
- **Интеграция изменений и traceability**: превращает проверенную работу в proposals, ждёт approval, применяет accepted changes и пишет полный trace.
- **Memory на уровне проекта**: сохраняет sessions, memory, knowledge и task history.
- **Автоматический рост**: учится на завершённой работе и создаёт reviewable candidates для будущих улучшений.
- **Единые entry points**: один runtime доступен через Python API, React web console, interactive CLI, MCP server и gateways.
- **Переиспользуемые skills**: импортирует и управляет versioned skills через safety-scanning broker.

## Сценарии использования

- Проекты, которым нужен встроенный AI Engineering Runtime вместо внешнего chat assistant.
- Команды, которые хотят проводить AI-generated code через tests, approvals, audit и integration.
- Codebases с постоянным repair, refactor, test coverage, docs и interface alignment.
- Организации, которым нужны project-level memory, traceable automation и reusable engineering capabilities.

## Граница безопасности

Каждое рискованное действие проходит через authorization layer (hard floor → policy layers → approvals), а изменения попадают в git-worktree sandbox. Этот sandbox изолирует *видимость изменений*, а не *привилегии*: agent processes разделяют host filesystem, OS user, network и kernel, а container или OS-level backend отсутствуют. Из семи execution brokers сейчас в runtime собраны file, process и apply; network, database и git существуют, но ещё не подключены к agent path.

## Технологии

| Уровень | Технология |
|---|---|
| Язык | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Хранение | SQLite, JSONL, blob в файловой системе, хранилища в памяти (Milvus, Neo4j, Redis зарезервированы) |
| Конфигурация | TOML с типизированными dataclass-настройками |
| Инструменты | uv, pytest, pytest-asyncio, ruff |

## Структура проекта

```text
src/Sprout/
├── runtime/       # Runtime, промежуточные слои, жизненный цикл, рабочая область, блокировки, очереди, сборка
├── agent/         # Протокол агента, AgentLoop, маршрутизация, планирование, выполнение
├── session/       # Модели сессий и ходов
├── memory/        # Композиция памяти, бюджеты, снимки и персистентность
├── context/       # AgentContext и построение контекста
├── message/       # Унифицированные сообщения, вложения и преобразование
├── llm/           # Провайдеры моделей: echo, OpenAI-compatible, aiyallm
├── tools/         # ToolSpec, защищённый исполнитель, реестр, системные инструменты
├── skills/        # Версионированные навыки и репозиторий навыков
├── security/      # Уровни риска, политика, одобрение
├── events/        # Внутрипроцессная шина событий
├── registry/      # Универсальные реестры
├── storage/       # Контракты хранения и локальные реализации
├── evolution/     # Слой роста, воспроизведение, обслуживание и рост траектории
├── strategy/      # Декомпозиция требований, анализ влияния и планы проверки
├── artifacts/     # Модели артефактов и метаданные
├── capability/    # Модели возможностей
├── execution/     # Применение изменений и адаптеры брокеров
├── gateway/       # Шлюзы runtime, RPC, задач, демона и транспорта
├── orchestration/ # Компилятор графов, Temporal terminal, воркер и workflows
├── rootstock/     # Бэкенды персистентности сессий/корня
├── sandbox/       # Песочница git worktree
├── task/          # Модели задач и жизненный цикл
├── trajectory/    # Персистентность траектории
├── workspace/     # Вспомогательные средства рабочей области
├── config/        # Типизированные настройки и загрузка TOML
├── scheduler/     # Поддержка отложенных задач
├── cli/           # Командная строка sprout
└── mcp/           # Сервер, клиент и адаптеры MCP

web/
├── frontend/      # Веб-консоль Vite + React
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Приложение Starlette HTTP/WebSocket, маршруты и база данных

assets/            # Общий логотип и статические ресурсы
~/.sprout/docker/  # Стек шести баз данных: compose-файл, образ раннера, начальная настройка
```

## Стратегия требований

`src/Sprout/strategy/` превращает предложение от сканирования проекта или прямой запрос пользователя в проверяемый план реализации. Его `StrategyPipeline` на этапе планирования работает только на чтение и собирает доказательства до изменения любого кода.

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

Анализ влияния использует два источника доказательств:

- **Доказательства из базы данных**: доступ только на чтение через брокер базы данных для проверки схем, таблиц, миграций, сохранённых записей и существующей истории интерфейсов или задач.
- **Доказательства из проекта**: полное сканирование рабочей области, которое находит исходные файлы, интерфейсы, код, связанный с базой данных, и тестовые файлы, а при наличии — связи графа рабочей области.
- **Перекрёстная проверка**: сравнение обоих источников с пометкой совпадений, объектов только в базе, объектов только в коде и нерешённых конфликтов. Конфликты выносятся на рассмотрение человека, а не молча трактуются как разрешение на правку.

Слой стратегии отвечает за приём требований, анализ влияния, выбор режима изменений, критерии приёмки и планирование тестовых файлов. `workspace/` предоставляет доказательства проекта только на чтение, `runtime/changes.py` отвечает за одобрение предложений и формальное apply/rollback, а `execution/` — за брокеры patch, database, process и Git.

## Установка

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

Конфигурация по умолчанию полностью офлайн: провайдер модели `echo`, локальные базы SQLite и отсутствие внешних MCP-клиентов.

Для провайдера модели `aiyallm` установите его дистрибутив:

```bash
pip install aiyallm
```

### Шесть баз данных двумя командами

Runtime расходится по шести базам данных. Три из них — обычные файлы (SQLite, JSONL-журнал доказательств и blob-хранилище), поэтому установка им вообще не нужна; остальные три (Redis, Milvus, Neo4j) — контейнеры. Весь жизненный цикл покрывается двумя командами:

```powershell
sprout db init                    # создать/инициализировать все настроенные lane
sprout db status                  # сообщить healthy/failed по каждому lane
sprout db backup <dir>            # сделать резервную копию баз SQLite
sprout db restore <dir>           # восстановить базы SQLite
```
```bash
sprout db init
sprout db status
```

`init` строит пять схем SQLite, каталоги JSONL и blob, три коллекции Milvus и ограничения Neo4j — идемпотентно и без записи строк. `test` записывает через обычный пакет хранения сессию, два хода, факт памяти и слишком большой снимок контекста, а затем читает каждый lane обратно клиентом этого же lane — именно это делает «все шесть работают» проверенным фактом, а не заявлением. `sprout db init` инициализирует все настроенные lane, а `sprout db status` проверяет их по одному. При использовании Docker `init` также вытягивает три служебных образа (с зеркальным запасным вариантом для заблокированного Docker Hub), собирает образ раннера, запускает lane и проверяет их.

Порты, конфигурация, три слоя тестирования, профиль без Docker и устранение неполадок описаны в `~/.sprout/docker/README.md`.

## Использование

### Agent

Python API — основная поверхность использования. Соберите runtime и отправьте `Message`:

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

Все точки входа используют `create_runtime()` как единый путь сборки.

### Web

Веб-консоль — это компонентное React-приложение, собираемое с помощью Vite.

Сначала соберите фронтенд:

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

Затем запустите веб-консоль:

```bash
uv run sprout serve
```

Откройте `http://127.0.0.1:8000`. Веб-приложение предоставляет чат, доску задач, управление задачами и настройки.

Разработка фронтенда с горячей перезагрузкой:

```bash
cd web/frontend
npm run dev
```

Доступные HTTP-эндпоинты:

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

WebSocket-эндпоинт доступен по адресу `ws://127.0.0.1:8000/ws/chat`.

### CLI

```bash
uv run sprout --help
uv run sprout                     # интерактивный чат
uv run sprout chat "hello"        # одноразовое сообщение
uv run sprout info                # снимок runtime и конфигурации
uv run sprout project workspace <path>   # открыть локальную рабочую область
uv run sprout remote workspace-list      # управлять удалённым сервисом SEMA
uv run sprout db init             # инициализировать все настроенные lane
uv run sprout db status           # сообщить healthy/failed
uv run sprout db backup ./backup  # резервная копия локальных баз
uv run sprout mcp inspect         # изучить определения MCP
uv run sprout evolution candidates  # слой роста: что произвёл пайплайн
uv run sprout skills import ~/code/my-skills   # импортировать навыки из локальной папки
uv run sprout skills list         # что установлено
uv run sprout skills index --rebuild   # синхронизировать снимок, сообщить расхождение реестра и диска
uv run sprout skills forget <name>     # удалить строку реестра, оставить файлы
uv run sprout serve               # веб-консоль и API
uv run sprout stop serve          # остановить веб-консоль
```

`skills import` рекурсивно обходит каталог: папка, содержащая `SKILL.md`, считается одним навыком, а одиночные файлы `*.toml` — отдельными записями. Он находит вложенные структуры (`skills/writing/docs/SKILL.md`), пропускает вендорные каталоги и устанавливает каждый навык через тот же брокер, что и остальная подсистема: сначала сканирование на небезопасное содержимое, затем решение движка политик. Поскольку локальный путь — это первосторонний источник, одобрение не требуется; нижний предел фатальных находок сканера всё равно действует и не может быть обойдён одобрением.

### Язык CLI

Интерактивный CLI может менять язык меню без перезапуска:

```text
/language
/language ja
/language zh-Hant
```

Поддерживаемые языки перечислены в [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md). Выбор сохраняется в `~/.sprout/settings.json` и используется в следующей сессии.

### Temporal

Оркестрация задач, очереди, расписания, автоматизация роста, веб-задачи и работа шлюзов могут выполняться на Temporal.

Запустите локальный сервер Temporal с помощью входящего в комплект Compose-стека:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Проверьте доступность без установки Temporal CLI:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` сообщает о доступности сервера, его версии, наличии пространства имён и количестве воркеров, опрашивающих настроенную очередь задач.

### MCP

Запустите MCP-сервер через stdio:

```bash
uv run sprout mcp serve
# или
sprout-mcp
```

Сервер предоставляет только безопасные операции: отправку сообщений, создание сессий, чтение истории сессий, перечисление навыков и поиск знаний. Высокорисковые записи, одобрения и публикация роста остаются за пределами MCP.

Изучите предоставляемые инструменты, ресурсы и подсказки:

```bash
uv run sprout mcp inspect
```

## Конфигурация

Конфигурация пользователя находится в `~/.sprout/sprout.toml`. Держите конфигурацию в этом единственном файле и не добавляйте дублирующий локальный `sprout.toml` в корень проекта. Используйте `SPROUT_CONFIG` только для указания на другой явный путь, когда это необходимо.

Инструменты Project Runtime MCP:

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

## Настройка реальной модели

Отредактируйте `~/.sprout/sprout.toml`, чтобы использовать DeepSeek или другого провайдера:

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
# Authority runtime Sprout: conversation поддерживает sqlite | jsonl | blobstore;
# Milvus/Neo4j/Redis остаются лишь восстанавливаемыми производными слоями.
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

Секреты читаются из переменных окружения и никогда не записываются в файл конфигурации.

## Разработка

```bash
uv run pytest
uv run ruff check .
```

О рабочем процессе разработки и правилах доступа CLI/MCP см. [guidance.md](guidance.md).

## Участники

Спасибо всем, кто внёс вклад в SEAM Sprout:

| Участник | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Лицензия

Проект распространяется по лицензии [MIT License](LICENSE).

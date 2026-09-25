# SEAM Sprout

SEAM Sprout — саморазвивающийся AI-агент для программных проектов. Он подключается к кодовой базе, понимает структуру и контекст, генерирует код, выполняет его в изолированной среде, проверяет результат и затем интегрирует изменения.

## Ключевые возможности

- Точный анализ проекта: структура репозитория, контекст кода, сессии, память и знания.
- Генерация кода: превращает намерение в конкретное изменение.
- Изолированное выполнение: запускает код в git worktree-песочнице.
- Проверка кода: тестирует изменение до интеграции.
- Интеграция кода: применяет проверенные изменения и сохраняет трассировку.
- Автоматический рост: извлекает опыт и создаёт предложения по улучшению.

## Бизнес-сценарии

- Проекты, которым нужен встроенный AI-инженер, а не отдельный чат.
- Кодовые базы, требующие постоянного ремонта, рефакторинга и доработки.
- Команды, которым нужно безопасно запускать, тестировать и интегрировать код.
- Организации, которым нужны память, эволюция и аудит на уровне проекта.
- Опасные действия проходят через слой авторизации. Песочница изолирует видимость изменений, но не привилегии процесса, пользователя ОС или сеть.

## Технологии

| Слой | Технология |
|---|---|
| Язык | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Хранилище | SQLite, JSONL, Blob, память, Milvus/Neo4j/Redis |
| Конфигурация | TOML + типизированные dataclass |
| Инструменты | uv, pytest, ruff |

## Установка

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Веб-консоль

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Откройте `http://127.0.0.1:8000`. В веб-консоли доступны чат, доска задач, управление задачами, токены, хранилище, логи и настройки.

Основные HTTP API:

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

### Язык CLI

```text
/language
/language ja
/language zh-Hant
```

Поддерживаемые языки и инструкции по добавлению: `src/Sprout/cli/i18n_languages.md`.

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## Конфигурация

Конфигурация хранится в `~/.sprout/sprout.toml`. Не добавляйте дублирующий локальный `sprout.toml` в проект.

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## Разработка

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## Структура проекта

```text
src/Sprout/
├── runtime/       # Среда выполнения, middleware, жизненный цикл
├── agent/         # Протокол агента и AgentLoop
├── session/       # Модели сессий и реплик
├── memory/        # Память, бюджеты, снимки
├── context/       # AgentContext и контекст
├── message/       # Унифицированные сообщения
├── llm/           # Провайдеры моделей
├── tools/         # ToolSpec и безопасный исполнитель
├── skills/        # Версионированные навыки
├── security/      # Риски, политики, согласования
├── storage/       # Контракты хранилища
├── evolution/     # Плоскость роста
├── execution/     # Применение изменений
├── gateway/       # Шлюзы runtime, RPC, задач
├── orchestration/ # Компилятор графа и Temporal worker
├── rootstock/     # Хранилища сессий
├── sandbox/       # Git worktree sandbox
├── task/          # Модели задач
├── trajectory/    # Траектории
├── workspace/     # Вспомогательный код workspace
├── config/        # Настройки и TOML
├── cli/           # Команда sprout
└── mcp/           # MCP сервер и клиент

web/
├── frontend/      # Vite + React Web консоль
└── webapi/        # Starlette HTTP/WebSocket приложение
```

## Шесть баз данных

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite, JSONL и Blob являются обычными файлами. Redis, Milvus и Neo4j можно настроить как контейнеры. Подробнее: `~/.sprout/docker/README.md`.

## Python Agent API

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
# или
sprout-mcp
```

Доступные инструменты:

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

## Участники

| Участник | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Лицензия

[MIT License](LICENSE)

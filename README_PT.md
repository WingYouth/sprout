# SEAM Sprout

O SEAM Sprout é um agente de IA autoevolutivo para projetos de software. Ele se conecta a uma base de código, entende sua estrutura e contexto, gera código, executa em um ambiente isolado, verifica o resultado e depois integra as alterações.

## Principais recursos

- Análise precisa do projeto: estrutura do repositório, contexto, sessões, memória e conhecimento.
- Geração de código: converte a intenção em mudanças concretas.
- Execução isolada: executa o código em um sandbox de git worktree.
- Verificação de código: testa e confere cada alteração antes da integração.
- Integração de código: aplica mudanças verificadas e mantém o histórico.
- Crescimento automático: aprende com o trabalho concluído e cria propostas de melhoria.

## Casos de uso comerciais

- Projetos que precisam de um engenheiro de IA integrado, não de outra ferramenta de chat.
- Bases de código que precisam de reparo, refatoração ou novas funcionalidades.
- Equipes que precisam executar, testar e integrar código gerado com segurança.
- Organizações que exigem memória, evolução e auditoria por projeto.
- Ações perigosas passam pelo plano de autorização. O sandbox isola a visibilidade da alteração, não os privilégios do processo, usuário do SO ou rede.

## Stack tecnológico

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Persistência | SQLite, JSONL, Blob, memória, Milvus/Neo4j/Redis |
| Configuração | TOML + dataclasses tipadas |
| Ferramentas | uv, pytest, ruff |

## Instalação

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Console web

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

Abra `http://127.0.0.1:8000`. O console inclui chat, quadro de tarefas, gerenciamento de tarefas, tokens, armazenamento, logs e configurações.

Principais APIs HTTP:

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

### Idioma da CLI

```text
/language
/language ja
/language zh-Hant
```

Consulte os idiomas compatíveis em `src/Sprout/cli/i18n_languages.md`.

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## Configuração

A configuração fica em `~/.sprout/sprout.toml`. Não adicione um `sprout.toml` local duplicado no projeto.

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## Desenvolvimento

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## Estrutura do projeto

```text
src/Sprout/
├── runtime/       # Runtime, middleware, ciclo de vida, workspace
├── agent/         # Protocolo de agente e AgentLoop
├── session/       # Modelos de sessão e turno
├── memory/        # Memória, orçamentos e snapshots
├── context/       # AgentContext e construção de contexto
├── message/       # Mensagens unificadas e conversão
├── llm/           # Provedores de modelo
├── tools/         # ToolSpec e executor seguro
├── skills/        # Skills versionadas
├── security/      # Risco, política e aprovação
├── storage/       # Contratos de armazenamento
├── evolution/     # Plano de crescimento
├── execution/     # Aplicação de mudanças
├── gateway/       # Gateways de runtime, RPC e tarefas
├── orchestration/ # Compilador de grafo e worker Temporal
├── rootstock/     # Backends de persistência de sessão
├── sandbox/       # Sandbox de git worktree
├── task/          # Modelos de tarefa
├── trajectory/    # Persistência de trajetória
├── workspace/     # Helpers de workspace
├── config/        # Ajustes e TOML
├── cli/           # Linha de comando sprout
└── mcp/           # Servidor e cliente MCP

web/
├── frontend/      # Console Vite + React
└── webapi/        # Aplicação Starlette HTTP/WebSocket
```

## Seis bancos de dados

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite, JSONL e Blob são arquivos normais. Redis, Milvus e Neo4j podem ser configurados como contêineres. Consulte `~/.sprout/docker/README.md`.

## API do agente Python

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
# ou
sprout-mcp
```

Ferramentas expostas:

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

## Configuração de um modelo real

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

## Licença

[MIT License](LICENSE)

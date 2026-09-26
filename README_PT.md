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

O SEAM Sprout é um AI Engineering Runtime embutido em um projeto de software. Ele leva uma mudança da intenção do usuário para edições de código, execução isolada, verificação, aprovação, integração e rastreabilidade, para que a IA não apenas sugira, mas complete um ciclo de engenharia controlado e revisável dentro do limite do projeto.

O problema central que o Sprout resolve é que o trabalho real de software tem muitas mudanças pequenas, mas importantes, enquanto o contexto fica espalhado, o risco é difícil de controlar, a verificação é trabalhosa e o conhecimento acumulado raramente é reutilizado. O Sprout reúne codebase, sessões, memória, conhecimento, ferramentas, aprovações e audit trail em um único runtime para que um projeto possa ser mantido, reparado e melhorado continuamente, com ações perigosas sob controle humano.

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## O que o Sprout resolve

O Sprout foi feito para entrega de mudanças no nível do projeto, não para Q&A pontual de código. Ele coloca a IA dentro de uma pipeline controlada: lê evidências do projeto, cria um plano, modifica código em um worktree isolado, executa checks, produz uma proposta revisável e aplica o resultado aprovado de volta ao projeto com rastreabilidade.

| Dor real do projeto | Por que é difícil | Resposta do Sprout |
|---|---|---|
| **A IA dá uma resposta, mas o trabalho de engenharia ainda não acabou** | Um snippet precisa cair nos arquivos certos, encaixar no design existente, passar em testes e sobreviver a conflitos. | Converte pedidos em linguagem natural em tasks executáveis com planejamento, patches, checks, propostas e apply formal. |
| **O contexto fica espalhado entre código, dados, docs e conversas anteriores** | Boas decisões dependem da estrutura do repo, interfaces, storage schema, decisões históricas e objetivo atual. | Combina project scans, sessões, memória, conhecimento e storage evidence dentro de um runtime. |
| **O código gerado parece plausível, mas não foi provado** | A saída do LLM costuma ser revisada antes de rodar no ambiente alvo. | Executa mudanças e checks em um git-worktree sandbox e anexa a evidência de verificação à proposta. |
| **Ações arriscadas precisam de limites aplicáveis** | File writes, process execution, network access e database access podem quebrar sistemas, vazar segredos ou contornar ownership. | Encaminha ações perigosas por risk levels, policies, approvals e brokers controlados. |
| **O trabalho de manutenção se acumula** | Pequenos bugs, documentation drift, interface mismatch, refactors e testes ausentes importam, mas são fáceis de adiar. | Escaneia, repara e cria growth candidates revisáveis para melhorias futuras. |
| **O aprendizado não se acumula entre tarefas** | Correções, preferências do projeto e workflow knowledge desaparecem no histórico do chat. | Persiste trajectories, memória, conhecimento e skills versionadas para melhorar trabalhos futuros. |
| **Múltiplas superfícies se desalinhavam** | CLI, Web, MCP, Python API e gateways podem acabar com comportamento, permissões e auditoria diferentes. | Envia todas as superfícies pela mesma rota `create_runtime()`, com storage, authorization, events e audit compartilhados. |
| **Storage e infraestrutura são difíceis de confiar** | Sessões, conhecimento, audit, vetores, grafo e cache podem viver em backends diferentes. | Fornece inicialização, status checks e caminhos verificáveis de leitura/escrita para SQLite, JSONL, blobs, Redis, Milvus e Neo4j. |

## Capacidades do produto

- **Evidência do projeto primeiro**: lê estrutura do repo, contexto de código, sessões, memória, conhecimento e storage evidence antes de agir.
- **Planejamento revisável**: transforma sugestões de project scan ou pedidos diretos em planos de implementação respaldados por evidência.
- **Geração de código controlada**: cria patches reais e aplica operações de file, process e change por meio de brokers.
- **Execução isolada e verificação**: executa mudanças e checks em um git-worktree sandbox antes de tocar no projeto principal.
- **Integração e rastreabilidade de mudanças**: transforma trabalho verificado em proposals, aguarda approval, aplica mudanças aceitas e registra o rastro completo.
- **Memória no nível do projeto**: persiste sessões, memória, conhecimento e histórico de tasks.
- **Crescimento automático**: aprende com o trabalho concluído e cria candidates revisáveis para melhorias futuras.
- **Entradas unificadas**: expõe um único runtime por Python API, React web console, CLI interativa, MCP server e gateways.
- **Skills reutilizáveis**: importa e gerencia skills versionadas por meio de um broker de safety scanning.

## Casos de uso

- Projetos que precisam de um AI Engineering Runtime embutido em vez de um assistente de chat externo.
- Equipes que querem que código gerado por IA passe por tests, approvals, audit e integração.
- Codebases com repair contínuo, refactor, test coverage, docs e interface alignment.
- Organizações que exigem memória no nível do projeto, automação rastreável e capacidades reutilizáveis.

## Limite de segurança

Toda ação arriscada passa pela authorization layer (hard floor → policy layers → approvals), e as mudanças entram em um git-worktree sandbox. Esse sandbox isola a *visibilidade da mudança*, não os *privilégios*: os processos do agente compartilham filesystem, OS user, network e kernel do host, e não há container nem OS-level backend. Dos sete execution brokers, file, process e apply estão montados hoje no runtime; network, database e git existem, mas ainda não estão conectados ao agent path.

## Stack tecnológico

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| Persistência | SQLite, JSONL, blobs no sistema de arquivos, armazenamentos em memória (Milvus, Neo4j, Redis reservados) |
| Configuração | TOML com dataclasses tipados |
| Ferramentas | uv, pytest, pytest-asyncio, ruff |

## Estrutura do projeto

```text
src/Sprout/
├── runtime/       # Runtime, middleware, ciclo de vida, workspace, bloqueios, filas e montagem
├── agent/         # Protocolo do agente, AgentLoop, roteamento, planejamento, execução
├── session/       # Modelos de sessão e turno
├── memory/        # Composição de memória, orçamentos, snapshots e persistência
├── context/       # AgentContext e construção de contexto
├── message/       # Mensagens unificadas, anexos e conversão
├── llm/           # Provedores de modelo: echo, OpenAI-compatible, aiyallm
├── tools/         # ToolSpec, executor com porta de segurança, registro, ferramentas do sistema
├── skills/        # Skills versionadas e repositório de skills
├── security/      # Níveis de risco, políticas, aprovação
├── events/        # Barramento de eventos em processo
├── registry/      # Registros genéricos
├── storage/       # Contratos de armazenamento e implementações locais
├── evolution/     # Camada de crescimento, replay, manutenção e crescimento de trajetória
├── strategy/      # Decomposição de requisitos, análise de impacto e planos de verificação
├── artifacts/     # Modelos de artefatos e metadados
├── capability/    # Modelos de capacidades
├── execution/     # Aplicação de mudanças e adaptadores de brokers
├── gateway/       # Gateways de runtime, RPC, tarefas, daemon e transporte
├── orchestration/ # Compilador de grafos, terminal Temporal, worker e workflows
├── rootstock/     # Backends de persistência de sessão/raiz
├── sandbox/       # Sandbox de git worktree
├── task/          # Modelos de tarefa e ciclo de vida
├── trajectory/    # Persistência de trajetória
├── workspace/     # Helpers de workspace
├── config/        # Configurações tipadas e carregamento de TOML
├── scheduler/     # Suporte a tarefas agendadas
├── cli/           # Linha de comando sprout
└── mcp/           # Servidor, cliente e adaptadores MCP

web/
├── frontend/      # Console web Vite + React
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Aplicação Starlette HTTP/WebSocket, rotas e banco de dados

assets/            # Logo compartilhado e recursos estáticos
~/.sprout/docker/  # Stack de seis bancos de dados: arquivo compose, imagem runner, bootstrap
```

## Estratégia de requisitos

`src/Sprout/strategy/` transforma uma sugestão da varredura do projeto ou uma solicitação direta do usuário em um plano de implementação revisável. Seu `StrategyPipeline` é somente leitura na etapa de planejamento e produz a evidência necessária antes de qualquer código ser alterado.

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

A análise de impacto usa duas fontes de evidência:

- **Evidência de banco de dados**: acesso somente leitura pelo broker de banco de dados para verificar esquemas, tabelas, migrações, registros persistidos e histórico existente de interfaces ou tarefas.
- **Evidência do projeto**: uma varredura completa do workspace que localiza arquivos-fonte, interfaces, código relacionado a banco de dados e arquivos de teste, além de relacionamentos do grafo do workspace quando disponíveis.
- **Validação cruzada**: compara as duas fontes e marca correspondências, objetos só de banco, objetos só de código e conflitos não resolvidos. Os conflitos são expostos para revisão humana em vez de serem tratados silenciosamente como permissão para editar.

A camada de estratégia é responsável pela captura de requisitos, análise de impacto, seleção do modo de mudança, critérios de aceitação e planejamento de arquivos de teste. `workspace/` fornece evidência de projeto somente leitura, `runtime/changes.py` cuida da aprovação de propostas e do apply/rollback formal, e `execution/` cuida dos brokers de patch, database, process e Git.

## Instalação

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

A configuração padrão é totalmente offline: o provedor de modelo `echo`, bancos SQLite locais e nenhum cliente MCP externo.

Para o provedor de modelo `aiyallm`, instale sua distribuição:

```bash
pip install aiyallm
```

### Seis bancos de dados em dois comandos

O runtime se desdobra em seis bancos de dados. Três são arquivos simples — SQLite, o log de evidências JSONL e o armazenamento de blobs —, então não exigem instalação alguma; os outros três (Redis, Milvus, Neo4j) são contêineres. Dois comandos cobrem o ciclo de vida:

```powershell
sprout db init                    # criar/inicializar todas as lanes configuradas
sprout db status                  # informar healthy/failed por lane
sprout db backup <dir>            # fazer backup dos bancos SQLite
sprout db restore <dir>           # restaurar os bancos SQLite
```
```bash
sprout db init
sprout db status
```

`init` constrói os cinco esquemas SQLite, os diretórios JSONL e blob, as três coleções Milvus e as restrições Neo4j — de forma idempotente e sem gravar linhas. `test` grava uma sessão, dois turnos, um fato de memória e um snapshot de contexto superdimensionado por meio do pacote de armazenamento normal, e então lê cada lane de volta com o cliente da própria lane, o que torna «todas as seis estão de pé» um fato verificado e não uma alegação. `sprout db init` inicializa todas as lanes configuradas e `sprout db status` as verifica uma a uma. Com Docker, `init` também baixa as três imagens de serviço (com fallback de espelho para Docker Hub bloqueado), constrói a imagem runner, inicia as lanes e as prova.

Portas, configuração, as três camadas de teste, o perfil sem Docker e a solução de problemas ficam em `~/.sprout/docker/README.md`.

## Uso

### Agent

A API Python é a superfície de uso principal. Construa um runtime e envie uma `Message`:

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

Todos os pontos de entrada usam `create_runtime()` como o único caminho de montagem.

### Web

O console web é uma aplicação React baseada em componentes, construída com Vite.

Construa o frontend uma vez:

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

Depois inicie o console web:

```bash
uv run sprout serve
```

Abra `http://127.0.0.1:8000`. A aplicação web oferece chat, um quadro de tarefas, gerenciamento de tarefas e configurações.

Para desenvolvimento do frontend com recarga a quente:

```bash
cd web/frontend
npm run dev
```

Os endpoints HTTP disponíveis incluem:

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

O endpoint WebSocket está disponível em `ws://127.0.0.1:8000/ws/chat`.

### CLI

```bash
uv run sprout --help
uv run sprout                     # chat interativo
uv run sprout chat "hello"        # mensagem de disparo único
uv run sprout info                # snapshot de runtime e configuração
uv run sprout project workspace <path>   # abrir um workspace local
uv run sprout remote workspace-list      # operar um serviço SEMA remoto
uv run sprout db init             # inicializar todas as lanes configuradas
uv run sprout db status           # informar healthy/failed
uv run sprout db backup ./backup  # fazer backup dos bancos locais
uv run sprout mcp inspect         # inspecionar definições MCP
uv run sprout evolution candidates  # camada de crescimento: o que o pipeline produziu
uv run sprout skills import ~/code/my-skills   # importar skills de um diretório local
uv run sprout skills list         # o que está instalado
uv run sprout skills index --rebuild   # sincronizar o snapshot, informar divergência registro/disco
uv run sprout skills forget <name>     # remover uma linha do registro, manter os arquivos
uv run sprout serve               # console web e API
uv run sprout stop serve          # parar o console web
```

`skills import` percorre um diretório recursivamente, tratando uma pasta que contém um `SKILL.md` como uma skill e arquivos `*.toml` de arquivo único como entradas próprias. Ele encontra layouts aninhados (`skills/writing/docs/SKILL.md`), pula diretórios de fornecedores e instala cada skill pelo mesmo broker que o restante do subsistema usa: primeiro escaneia conteúdo inseguro e depois o mecanismo de políticas decide. Como um caminho local é uma fonte de primeira parte, nada precisa de aprovação; o piso de achados fatais do scanner ainda se aplica e não pode ser superado por aprovação.

### Idioma da CLI

A CLI interativa pode trocar o idioma do menu sem reiniciar:

```text
/language
/language ja
/language zh-Hant
```

Os idiomas suportados estão listados em [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md). A seleção é salva em `~/.sprout/settings.json` e reutilizada na próxima sessão.

### Temporal

Orquestração de tarefas, filas, agendamentos, automação de evolução, trabalhos web e trabalho de gateways podem rodar no Temporal.

Inicie um servidor Temporal local com o stack Compose incluído:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Depois verifique se ele está acessível sem instalar a CLI do Temporal:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` informa a acessibilidade do servidor, a versão do servidor, a presença do namespace e o número de workers consultando a fila de tarefas configurada.

### MCP

Execute o servidor MCP via stdio:

```bash
uv run sprout mcp serve
# ou
sprout-mcp
```

O servidor expõe apenas operações seguras: enviar mensagens, criar sessões, ler o histórico de sessões, listar skills e buscar conhecimento. Gravações de alto risco, aprovações e publicação de crescimento permanecem fora da superfície MCP.

Inspecione as ferramentas, recursos e prompts expostos:

```bash
uv run sprout mcp inspect
```

## Configuração

A configuração do usuário fica em `~/.sprout/sprout.toml`. Mantenha a configuração nesse único arquivo; não adicione um `sprout.toml` local duplicado no projeto. Use `SPROUT_CONFIG` apenas para apontar para outro caminho explícito quando necessário.

Ferramentas MCP do Project Runtime:

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

Edite `~/.sprout/sprout.toml` para usar o DeepSeek ou outro provedor:

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
# Authorities do runtime Sprout: sqlite | jsonl | blobstore para conversation;
# Milvus/Neo4j/Redis permanecem como camadas derivadas e nunca são authorities.
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

Os segredos são lidos de variáveis de ambiente e nunca são gravados no arquivo de configuração.

## Desenvolvimento

```bash
uv run pytest
uv run ruff check .
```

Consulte [guidance.md](guidance.md) para o fluxo de desenvolvimento e as regras de exposição de CLI/MCP.

## Contribuidores

Obrigado a todos que contribuíram com o SEAM Sprout:

| Contribuidor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## Licença

Este projeto está licenciado sob a [Licença MIT](LICENSE).

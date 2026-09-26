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
  一个嵌入项目内部的 AI Engineering Runtime，把项目意图变成可验证、可审核、可追踪的软件变更。
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## 概览

SEAM Sprout 是嵌入软件项目内部的 AI Engineering Runtime。它把一次变更从用户意图推进到代码改动、隔离执行、验证、审批、集成与追踪。

Sprout 不是聊天包装器。它是项目侧 runtime，让 AI agent 能读取仓库证据、规划工作、在 git worktree sandbox 中修改代码、运行检查、生成可审核 proposal，并记录发生过的一切。Python API、CLI、Web console、gateway 和 MCP server 都共享同一套 runtime。

核心思想很简单：AI 生成的代码不应该从模型回答直接跳进项目。它应该经过项目上下文、风险控制、验证、人类审核和 audit trail。

## Sprout 解决什么

Sprout 聚焦的是“模型给了答案”和“项目里出现可信变更”之间的断层。多数 AI 编码流程真正失效的地方，就在这段距离里。

| 项目真实痛点 | 为什么难 | Sprout 的回答 |
|---|---|---|
| **AI 给了答案，但工程还没完成** | 代码片段还要落到正确文件、适配现有架构、通过测试并处理冲突。 | 把自然语言意图转成可执行任务，经过规划、patch、检查、proposal 和正式 apply。 |
| **上下文分散** | 有用信息散在源码、测试、文档、storage schema、历史会话、日志和项目偏好里。 | 从仓库扫描、会话、memory、knowledge、storage evidence 和任务历史中构建上下文。 |
| **生成代码看似合理，但没有证明** | LLM 输出常常在目标环境中运行前就被拿去 review。 | 在 git worktree sandbox 中执行修改和检查，并把验证证据附到 proposal。 |
| **高风险动作需要可执行边界** | 写文件、跑进程、访问网络、访问数据库和 git 操作的影响范围不同。 | 用风险分级、policy、approval 和受控 broker 管理敏感动作。 |
| **维护工作持续堆积** | bug 修复、refactor、补测试、文档、依赖清理和接口对齐是长期工作。 | 支持 project task、proposal、approval、verification 和 growth candidate。 |
| **经验无法跨任务积累** | 修复经验、项目约定和工作流知识如果只在聊天记录里，很快就会丢失。 | 持久化 memory、trajectory、task history、knowledge 和 versioned skill。 |
| **入口容易漂移** | CLI、Web、API、gateway 和 MCP 可能发展出不同的行为和权限。 | 所有入口都通过同一个 `create_runtime()` 组装路径，共享 storage、security、events 和 tools。 |
| **存储和基础设施难以信任** | session、knowledge、audit、vector、graph 和 cache 可能分散在不同后端。 | 提供 SQLite、JSONL、blob、Redis、Milvus、Neo4j 的初始化、状态检查和可验证读写路径。 |

## 核心流程

```text
用户请求
  |
  v
项目证据 + memory
  |
  v
计划 + 风险分级
  |
  v
Sandboxed code edits
  |
  v
验证
  |
  v
可审核 proposal
  |
  v
Approval + apply
  |
  v
Trace + memory + audit
```

Sprout 的设计目标是让项目变更始终可检查：人可以看到改了什么、为什么改、跑了哪些检查，以及这次变更是否应该 apply。

## 产品能力

- **项目证据优先**：行动前读取仓库结构、代码上下文、会话、memory、knowledge 和 storage evidence。
- **可审核规划**：把项目扫描建议或直接请求转成有证据支撑的实现计划。
- **可控代码生成**：创建真实 patch，并通过 broker 执行文件、进程和变更操作。
- **隔离执行与验证**：在 git worktree sandbox 中运行改动和检查，再触碰主项目。
- **变更 proposal**：把生成结果和最终集成分开，支持 review、approval、reject、apply 和 rollback。
- **项目级 memory**：持久化 session、memory、knowledge 和 task history，让后续任务继承上下文。
- **自动成长**：从完成的工作中学习，并产出可审核的后续改进候选。
- **统一入口**：通过 Python API、CLI、React Web console、MCP server、gateway 和 remote RPC 暴露同一 runtime。
- **可复用 skill**：通过安全扫描 broker 导入和管理版本化 skill。

## 架构

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

runtime 是系统中心。入口层保持轻薄：把各自 transport 的输入转换成 runtime 调用，然后让 runtime 处理上下文、授权、工具、存储、任务、proposal 和 audit。

## 安全边界

每个高风险动作都会经过授权层：hard floor、policy、approval 和 broker 检查。变更落在 git worktree sandbox 中。

这个 sandbox 隔离的是**变更可见性**，不是**权限**。Agent 进程仍然共享宿主 filesystem、OS user、network 和 kernel。Sprout 不提供 container、VM 或 OS-level backend isolation。请按这个边界处理不可信代码。

当前 runtime 默认装配 file、process 和 apply broker。Network、database 和 git broker 已存在，但尚未接入默认 agent execution path。

## 技术栈

| 领域 | 技术 |
|---|---|
| 核心语言 | Python 3.12+ |
| 前端 | React、Vite、Node.js 20+ |
| Web server | Starlette、Uvicorn |
| CLI | Typer |
| LLM providers | echo、OpenAI-compatible、`aiyallm` |
| MCP | MCP Python SDK |
| 编排 | Temporal SDK |
| 本地持久化 | SQLite、JSONL、filesystem blobs |
| 可选 lanes | Redis、Milvus、Neo4j |
| 测试 | pytest、pytest-asyncio |
| Lint | Ruff |
| 打包 | uv、hatchling |

## 仓库结构

```text
src/Sprout/
├── runtime/       # Runtime、middleware、lifecycle、workspace、locks、queues、assembly
├── agent/         # Agent protocol、AgentLoop、routing、planning、execution
├── context/       # AgentContext 与上下文构建
├── memory/        # Memory 组合、预算、快照、持久化
├── session/       # Sessions 与 turns
├── message/       # 统一消息、附件、转换
├── llm/           # Model providers
├── tools/         # ToolSpec、gated executor、registry、system tools
├── security/      # Risk levels、policy、approvals
├── execution/     # Change application 与 broker adapters
├── sandbox/       # Git worktree sandbox
├── storage/       # Storage contracts 与本地实现
├── rootstock/     # Session/root persistence backends
├── strategy/      # Requirement intake、impact analysis、verification plans
├── evolution/     # Growth layer、replay、maintenance、trajectory growth
├── skills/        # Versioned skills 与 skill repository
├── gateway/       # Runtime、RPC、task、daemon、transport gateways
├── orchestration/ # Temporal terminal、worker、workflows
├── cli/           # sprout command line
└── mcp/           # MCP server、client、adapters

web/
├── frontend/      # Vite + React Web console
└── webapi/        # Starlette HTTP/WebSocket application

assets/            # Logo 与共享静态资源
```

## 安装

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

默认配置是 local-first 且方便离线开发：`echo` model provider、本地 SQLite 数据库、没有外部 MCP client。

使用 `aiyallm` provider：

```bash
pip install aiyallm
```

## 快速开始

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

运行 Web console：

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

打开 `http://127.0.0.1:8000`。

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

所有入口都使用 `create_runtime()` 作为唯一组装路径。

## 常用命令

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

从 npm、`npx`、IDE task 或后台进程启动 Sprout 时，不要依赖进程当前目录。请显式传入项目根目录：

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout 会扇出到六条 storage lanes：

- SQLite：本地关系型状态。
- JSONL：证据和 append-only records。
- Filesystem blobs：大 payload。
- Redis：cache-oriented lanes。
- Milvus：vector search。
- Neo4j：graph-oriented knowledge。

文件型 lanes 不需要外部服务。启用 Redis、Milvus、Neo4j 时，会使用内置 Docker templates。

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

`db init` 创建已配置 lanes 和必要 schema。`db status` 按 lane 报告健康状态。Storage lifecycle 和 Docker 说明见 `~/.sprout/docker/README.md`。

## 配置

用户配置位于 `~/.sprout/sprout.toml`。保持一个 canonical user config；只有需要显式指定其他路径时才使用 `SPROUT_CONFIG`。

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

Secrets 从环境变量读取，不写进配置文件。

## MCP Server

通过 stdio 运行 MCP server：

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

查看暴露的 tools、resources 和 prompts：

```bash
uv run sprout mcp inspect
```

MCP client 配置示例：

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

Sprout 安装到目标机器后，可以直接用 `sprout-mcp` 作为 command。仓库本地开发时，`.venv/bin/python -m Sprout.cli.app mcp serve` 更明确，也更适合交给其他 agent 继承。

MCP surface 有意保持保守：暴露发送消息、创建 session、读取 history、列出 skills、搜索 knowledge 等安全操作。高风险写入、approval decisions 和 growth publishing 不进入 MCP surface。

stdio server protocol-first 启动：初始 MCP handshake 只注册 tools、resources 和 prompts，不要求 Temporal、Docker 或可写 storage。runtime 和 storage 会在具体操作真正需要时 lazy 组装。

## Temporal 编排

Task queues、scheduled work、evolution automation、web jobs 和 gateway work 可以运行在 Temporal 上。

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## 开发

```bash
uv run pytest
uv run ruff check .
```

构建 Web frontend：

```bash
cd web/frontend
npm install
npm run build
```

仓库开发流程、分层规则和 CLI/MCP 暴露规则见 [guidance.md](guidance.md)。

## 贡献者

感谢所有为 SEAM Sprout 做出贡献的人：

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## License

本项目使用 [MIT License](LICENSE)。

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

SEAM Sprout 是嵌入软件项目内部的 AI Engineering Runtime。它把一次变更从「用户意图」推进到「代码改动、隔离执行、验证、审批、集成与追踪」，让 AI 不只是给建议，而是能在项目边界内完成可控、可复查的工程闭环。

它解决的核心问题是：软件项目每天都有大量小而真实的改动需求，但上下文分散、风险难控、验证繁琐、历史经验难复用，导致 AI 生成的代码很难安全地变成项目里的可信变更。Sprout 把代码库、会话、记忆、知识、工具、审批和审计放进同一套 runtime，让项目可以持续被维护、修复和成长，同时把危险动作留在人类控制之下。

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Sprout 解决什么

Sprout 面向的不是一次性的代码问答，而是项目级的变更交付。它把 AI 放到一条受控 pipeline 里：先读项目证据，再形成计划，随后在隔离 worktree 中执行修改，运行检查，生成可审批的变更提案，最后把通过的结果合入项目并留下轨迹。

| 项目里的真实痛点 | 为什么难处理 | Sprout 的回答 |
|---|---|---|
| **AI 给了答案，工程还没完成** | 代码片段需要落到正确文件、适配现有结构、跑测试、处理失败和冲突。 | 把自然语言请求转成可执行任务，经过规划、补丁、测试、提案和正式应用，而不是停在建议层。 |
| **上下文散落在代码、数据库、文档和历史对话里** | 工程判断依赖仓库结构、接口约定、存储 schema、历史决策和本轮目标，聊天窗口很难长期持有这些信息。 | 在 runtime 中组合项目扫描、会话、记忆、知识和存储证据，让下一次任务继承已有上下文。 |
| **生成代码看起来对，但没人证明它真的能跑** | LLM 输出缺少同环境验证；复制粘贴后才发现构建失败、测试漏跑或接口不匹配。 | 在 git worktree sandbox 中执行变更和检查，把验证结果作为变更提案的一部分。 |
| **高风险操作没有清晰边界** | 写文件、跑进程、接触网络或数据库都可能带来破坏、泄密和越权。 | 用 risk levels、policy、approvals 和受控 broker 管理动作；危险变更先停下等待人类确认。 |
| **维护型工作长期堆积** | 小 bug、文档漂移、接口不一致、refactor 和补测试都重要，但经常因为琐碎被延后。 | 让项目可以被持续扫描、修复和提出增长候选，形成可审核的自动成长循环。 |
| **一次任务的经验无法沉淀** | 修过的问题、踩过的坑和项目偏好如果只留在聊天记录里，下一次仍要重来。 | 把轨迹、记忆、知识和技能版本化管理，让完成的工作反哺后续任务。 |
| **入口很多，runtime 不统一** | CLI、Web、MCP、Python API 和外部 gateway 如果各做各的，行为、权限和审计会漂移。 | 所有入口都走同一套 `create_runtime()` 组装路径，共享 storage、authorization、events 和 audit。 |
| **底层存储难搭、难检查、难信任** | 会话、知识、审计、向量、图谱和缓存分别落在不同后端，健康状态很难靠口头保证。 | 提供 SQLite、JSONL、blob 与 Redis、Milvus、Neo4j 的初始化、状态检查和可验证读写链路。 |

## 产品能力

- **项目证据优先**：行动前读取仓库结构、代码上下文、会话、记忆、知识和存储证据。
- **可审核规划**：把项目扫描建议或用户请求转成有证据支撑的实现计划。
- **可控代码生成**：生成真实补丁，并通过 broker 控制文件、进程和应用行为。
- **隔离执行与验证**：在 git worktree sandbox 中运行改动和检查，再决定是否进入主项目。
- **变更集成与追踪**：把验证通过的改动形成 proposal、等待 approval、正式 apply，并保留完整轨迹。
- **项目级记忆**：持久化会话、记忆、知识和任务历史，让每次工作建立在积累之上。
- **自动成长**：从完成任务中发现后续改进点，产出可审核的增长候选。
- **统一入口**：同一 runtime 可通过 Python API、React Web console、交互式 CLI、MCP server 和 gateway 访问。
- **可复用技能**：通过安全扫描 broker 导入和管理版本化技能，扩展 agent 能力。

## 适用场景

- 项目希望拥有一个内嵌 AI Engineering Runtime，而不是外置聊天助手。
- 团队需要把 AI 生成的代码纳入测试、审批、审计和集成流程。
- 代码库存在持续修复、重构、补测试、补文档和接口对齐需求。
- 组织需要项目级记忆、可追踪的自动化变更和可复用工程能力。

## 安全边界

每个高危动作都要先经过 authorization layer（hard floor → policy → approvals），变更落在 git worktree sandbox 里。该 sandbox 隔离的是*变更可见性*，不是*权限*：agent 进程与宿主共享 filesystem、OS user、network 和 kernel，没有 container 或 OS-level backend。七个 execution broker 里，当前装配进 runtime 的是 file、process、apply 三个；network、database、git 三个 broker 已实现但尚未接进 agent path。

## 采用技术

| 层级 | 技术 |
|---|---|
| 语言 | Python 3.12+、Node.js 20+ |
| CLI | Typer |
| Web | Starlette、Uvicorn、React、Vite |
| LLM | echo、OpenAI-compatible、aiyallm |
| MCP | MCP Python SDK |
| 持久化 | SQLite、JSONL、文件系统 blob、内存存储（预留 Milvus、Neo4j、Redis） |
| 配置 | TOML 与类型化 dataclass 设置 |
| 工程工具 | uv、pytest、pytest-asyncio、ruff |

## 项目结构

```text
src/Sprout/
├── runtime/       # Runtime、middleware、lifecycle、workspace、locks、queues 与 assembly
├── agent/         # Agent 协议、AgentLoop、路由、规划、执行
├── session/       # 会话与轮次模型
├── memory/        # 记忆组合、预算、快照与持久化
├── context/       # AgentContext 与上下文构建
├── message/       # 统一消息、附件与转换
├── llm/           # Model providers：echo、OpenAI-compatible、aiyallm
├── tools/         # ToolSpec、安全门控执行器、注册表、系统工具
├── skills/        # 版本化技能与技能仓储
├── security/      # 风险分级、策略、审批
├── events/        # 进程内事件总线
├── registry/      # 通用注册表
├── storage/       # 存储契约与本地实现
├── evolution/     # 成长平面、回放、维护与轨迹成长
├── strategy/      # 需求分解、影响分析与验证计划
├── artifacts/     # 产物模型与元数据
├── capability/    # 能力模型
├── execution/     # 变更应用与 Broker 适配器
├── gateway/       # Runtime、RPC、Task、Daemon 与 transport gateways
├── orchestration/ # 图编译器、Temporal terminal、worker 与 workflows
├── rootstock/     # 会话/根持久化后台
├── sandbox/       # Git worktree sandbox
├── task/          # 任务模型与生命周期
├── trajectory/    # 轨迹持久化
├── workspace/     # Workspace helpers
├── config/        # 类型化设置与 TOML 加载
├── scheduler/     # 定时任务支持
├── cli/           # sprout 命令行
└── mcp/           # MCP server、client 与 adapters

web/
├── frontend/      # Vite + React Web 控制台
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Starlette HTTP/WebSocket 应用、路由与数据库

assets/            # 共享 Logo 与静态资源
~/.sprout/docker/  # 六库栈：compose 文件、运行器镜像、引导脚本
```

## 需求策略

`src/Sprout/strategy/` 会把「项目扫描建议」或「用户直接请求」转化为一份可审核的实现计划。它的 `StrategyPipeline` 在规划阶段是只读的，只在改动任何代码之前产出所需证据。

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

影响分析使用两类证据来源：

- **数据库证据**：通过 database broker 对 schema、表、迁移、持久化记录，以及已有接口或任务历史做只读检查。
- **项目证据**：一次全量 workspace scan，定位源文件、接口、数据库相关代码和测试文件，并在可用时带上 workspace graph 关系。
- **交叉验证**：对比两类来源，标记匹配项、仅数据库存在、仅代码存在以及未解决的冲突。冲突会浮出水面交由人工审核，而不是被默认为编辑许可。

策略层负责需求受理、影响分析、变更模式选择、验收标准和测试文件规划。`workspace/` 提供只读的项目证据，`runtime/changes.py` 负责提案审批与正式 apply/rollback，`execution/` 负责 patch、database、process 与 Git broker。

## 安装

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

默认配置完全离线：使用 `echo` model provider、本地 SQLite 数据库，不连接外部 MCP client。

使用 `aiyallm` model provider 时，先安装对应发行版：

```bash
pip install aiyallm
```

### 六个数据库，两条命令

runtime 会在六个数据库间扇出。其中三个是普通文件：SQLite、JSONL evidence log、blob store，完全不需要安装；另外三个（Redis、Milvus、Neo4j）以 container 形式运行。两条命令覆盖整个生命周期：

```powershell
sprout db init                    # 创建/初始化所有已配置 lane
sprout db status                  # 逐个报告 healthy/failed
sprout db backup <dir>            # 备份 SQLite 数据库
sprout db restore <dir>           # 恢复 SQLite 数据库
```
```bash
sprout db init
sprout db status
```

`init` 会构建五个 SQLite schema、JSONL 与 blob 目录、三个 Milvus collection 以及 Neo4j constraints——幂等，且不写入任何行。`test` 通过常规 storage bundle 写入一个 session、两个 turns、一条 memory fact 和一份超大的 context snapshot，然后用每条 lane 自己的 client 把它们读回来，这才是「六个库都正常」这一可验证事实、而非一句声明。`sprout db init` 会初始化所有已配置 lane，`sprout db status` 会逐个检查。使用 Docker 时，`init` 还会拉取三个 service images（被墙的 Docker Hub 有 mirror fallback），构建 runner image，启动各 lane 并完成验证。

端口、配置、三层测试、无 Docker 配置与排障见 `~/.sprout/docker/README.md`。

## 使用方式

### Agent

Python API 是核心使用入口。构建一个 runtime 并发送 `Message`：

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

所有入口都通过 `create_runtime()` 走同一条组装路径。

### Web

Web 控制台是一个基于组件的 React 应用，使用 Vite 构建。

先构建一次前端：

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

然后启动 Web 控制台：

```bash
uv run sprout serve
```

打开 `http://127.0.0.1:8000`。Web 应用提供聊天、任务看板、任务管理与配置设置。

前端开发热更新：

```bash
cd web/frontend
npm run dev
```

可用的 HTTP 端点包括：

- `POST /api/chat`
- `POST /api/chat/stream`
- `GET /api/sessions/{session_id}/history`
- `GET /api/tasks`、`POST /api/tasks`
- `PATCH /api/tasks/{task_id}`、`DELETE /api/tasks/{task_id}`
- `GET /api/settings`、`PUT /api/preferences`
- `GET /api/tokens`
- `GET /api/logs`
- `GET /api/storage/status`、`GET /api/storage/plan`
- `GET /api/storage/graph/status`、`GET /api/storage/vectors/count`
- `GET /api/health`

WebSocket 地址为 `ws://127.0.0.1:8000/ws/chat`。

### CLI

```bash
uv run sprout --help
uv run sprout                     # 交互式聊天
uv run sprout chat "hello"        # 单发消息
uv run sprout info                # 查看 runtime 与配置快照
uv run sprout project workspace <path>   # 本地打开 workspace
uv run sprout remote workspace-list      # 操作远程 SEMA 服务
uv run sprout db init             # 初始化所有已配置 lane
uv run sprout db status           # 报告 healthy/failed
uv run sprout db backup ./backup  # 备份本地数据库
uv run sprout mcp inspect         # 查看 MCP 定义
uv run sprout evolution candidates  # 成长层：流水线已产出的候选
uv run sprout skills import ~/code/my-skills   # 从本机目录导入技能
uv run sprout skills list         # 查看已装技能
uv run sprout skills index --rebuild   # 同步快照，报告注册表与磁盘的分歧
uv run sprout skills forget <name>     # 删除注册表记录，保留文件
uv run sprout serve               # 启动 Web 控制台与 API
uv run sprout stop serve          # 停止 Web 控制台
```

`skills import` 会递归扫描目录：含 `SKILL.md` 的文件夹算作一个技能，独立的 `*.toml` 单文件也算一条。嵌套布局（`skills/writing/docs/SKILL.md`）同样能找到，依赖目录会被跳过；每个技能都走子系统统一的 broker —— 先做安全扫描，再由策略引擎裁决。本机路径属于首方来源，因此无需审批；扫描器的致命项底线依旧生效，且无法被审批越过。

### CLI 语言

交互式 CLI 可以在不重启的情况下切换菜单语言：

```text
/language
/language ja
/language zh-Hant
```

支持的语言见 [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md)。选择结果保存在 `~/.sprout/settings.json`，下一次启动会继续使用。

### Temporal

任务编排、队列、定时任务、成长自动化、Web 任务和 Gateway 工作都可以运行在 Temporal 上。

用仓库内置的 Compose stack 启动本地 Temporal server：

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

无需安装 Temporal CLI 即可检查连通性：

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` 会报告 server 可达性、server version、namespace 是否存在，以及配置的 task queue 上正在 polling 的 worker 数量。

### MCP

通过 stdio 运行 MCP server：

```bash
uv run sprout mcp serve
# 或
sprout-mcp
```

MCP server 只暴露安全操作：发送消息、创建 session、读取 session history、列出 skills 和搜索 knowledge。高危写入、approvals 和 growth publishing 不在 MCP 暴露范围内。

查看对外暴露的工具、资源和提示词：

```bash
uv run sprout mcp inspect
```

## 配置

用户配置位于 `~/.sprout/sprout.toml`。请只保留这一份配置，不要在项目根目录重复添加 `sprout.toml`；仅在必要时用 `SPROUT_CONFIG` 指向其他显式路径。

Project Runtime MCP 工具包括：

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

## 真实模型配置

编辑 `~/.sprout/sprout.toml` 以使用 DeepSeek 或其他提供方：

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
# Sprout runtime authority：conversation 支持 sqlite | jsonl | blobstore；
# Milvus/Neo4j/Redis 永远只是可重建的派生层。
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

密钥只从环境变量读取，不会写入配置文件。

## 开发

```bash
uv run pytest
uv run ruff check .
```

开发流程与 CLI/MCP 暴露规则见 [guidance.md](guidance.md)。

## 贡献者

感谢所有为 SEAM Sprout 做出贡献的人：

| 贡献者 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## License

本项目使用 [MIT License](LICENSE)。

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
  一個嵌入專案內部的 AI Engineering Runtime，把專案意圖變成可驗證、可審核、可追蹤的軟體變更。
</p>

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776ab" alt="Python 3.12+" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" alt="Node.js 20+" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=4f46e5" alt="aiyallm on PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" alt="MIT License" /></a>
</div>

## 概覽

SEAM Sprout 是嵌入軟體專案內部的 AI Engineering Runtime。它把一次變更從使用者意圖推進到程式碼改動、隔離執行、驗證、審批、整合與追蹤。

Sprout 不是聊天包裝器。它是專案側 runtime，讓 AI agent 能讀取倉庫證據、規劃工作、在 git worktree sandbox 中修改程式碼、執行檢查、產生可審核 proposal，並記錄發生過的一切。Python API、CLI、Web console、gateway 和 MCP server 都共享同一套 runtime。

核心想法很簡單：AI 生成的程式碼不應該從模型回答直接跳進專案。它應該經過專案上下文、風險控制、驗證、人類審核和 audit trail。

## Sprout 解決什麼

Sprout 聚焦的是「模型給了答案」和「專案裡出現可信變更」之間的斷層。多數 AI coding workflow 真正失效的地方，就在這段距離裡。

| 專案真實痛點 | 為什麼難 | Sprout 的回答 |
|---|---|---|
| **AI 給了答案，但工程還沒完成** | 程式碼片段還要落到正確檔案、適配既有架構、通過測試並處理衝突。 | 把自然語言意圖轉成可執行任務，經過 planning、patch、checks、proposal 和正式 apply。 |
| **上下文分散** | 有用資訊散在原始碼、測試、文件、storage schema、歷史 session、log 和專案偏好裡。 | 從 repository scan、session、memory、knowledge、storage evidence 和 task history 中建構上下文。 |
| **生成程式碼看似合理，但沒有證明** | LLM 輸出常在目標環境中執行前就被拿去 review。 | 在 git worktree sandbox 中執行修改和檢查，並把 verification evidence 附到 proposal。 |
| **高風險動作需要可執行邊界** | 寫檔、跑 process、存取 network、存取 database 和 git 操作的影響範圍不同。 | 用 risk classification、policy、approval 和受控 broker 管理敏感動作。 |
| **維護工作持續堆積** | bug 修復、refactor、補測試、文件、依賴清理和 interface alignment 是長期工作。 | 支援 project task、proposal、approval flow、verification 和 growth candidate。 |
| **經驗無法跨任務累積** | 修復經驗、專案慣例和 workflow knowledge 如果只在聊天紀錄裡，很快就會遺失。 | 持久化 memory、trajectory、task history、knowledge 和 versioned skill。 |
| **入口容易漂移** | CLI、Web、API、gateway 和 MCP 可能發展出不同的行為和權限。 | 所有入口都通過同一個 `create_runtime()` 組裝路徑，共享 storage、security、events 和 tools。 |
| **Storage 和 infrastructure 難以信任** | session、knowledge、audit、vector、graph 和 cache 可能分散在不同後端。 | 提供 SQLite、JSONL、blob、Redis、Milvus、Neo4j 的初始化、狀態檢查和可驗證讀寫路徑。 |

## 核心流程

```text
使用者請求
  |
  v
專案證據 + memory
  |
  v
計畫 + 風險分級
  |
  v
Sandboxed code edits
  |
  v
驗證
  |
  v
可審核 proposal
  |
  v
Approval + apply
  |
  v
Trace + memory + audit
```

Sprout 的設計目標是讓專案變更始終可檢查：人可以看到改了什麼、為什麼改、跑了哪些檢查，以及這次變更是否應該 apply。

## 產品能力

- **專案證據優先**：行動前讀取 repository structure、code context、session、memory、knowledge 和 storage evidence。
- **可審核規劃**：把 project scan 建議或直接請求轉成有證據支撐的 implementation plan。
- **可控 code generation**：建立真實 patch，並透過 broker 執行 file、process 和 change operations。
- **隔離執行與驗證**：在 git worktree sandbox 中執行改動和檢查，再觸碰主專案。
- **變更 proposal**：把生成結果和最終整合分開，支援 review、approval、reject、apply 和 rollback。
- **專案級 memory**：持久化 session、memory、knowledge 和 task history，讓後續任務繼承上下文。
- **自動成長**：從完成的工作中學習，並產出可審核的後續改進候選。
- **統一入口**：透過 Python API、CLI、React Web console、MCP server、gateway 和 remote RPC 暴露同一 runtime。
- **可復用 skill**：透過 safety-scanning broker 匯入和管理 versioned skill。

## 架構

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

runtime 是系統中心。入口層保持輕薄：把各自 transport 的輸入轉換成 runtime 呼叫，然後讓 runtime 處理上下文、授權、工具、storage、task、proposal 和 audit。

## 安全邊界

每個高風險動作都會經過授權層：hard floor、policy、approval 和 broker 檢查。變更落在 git worktree sandbox 中。

這個 sandbox 隔離的是**變更可見性**，不是**權限**。Agent process 仍然共享宿主 filesystem、OS user、network 和 kernel。Sprout 不提供 container、VM 或 OS-level backend isolation。請按這個邊界處理不可信程式碼。

目前 runtime 預設裝配 file、process 和 apply broker。Network、database 和 git broker 已存在，但尚未接入預設 agent execution path。

## 技術棧

| 領域 | 技術 |
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

## 倉庫結構

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

## 安裝

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

預設配置是 local-first 且方便離線開發：`echo` model provider、本地 SQLite database、沒有外部 MCP client。

使用 `aiyallm` provider：

```bash
pip install aiyallm
```

## 快速開始

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

執行 Web console：

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

開啟 `http://127.0.0.1:8000`。

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

所有入口都使用 `create_runtime()` 作為唯一組裝路徑。

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

從 npm、`npx`、IDE task 或背景行程啟動 Sprout 時，不要依賴 process current directory。請明確傳入專案根目錄：

```bash
nohup uv run sprout run --workspace "$PWD" "your task" > sprout-run.log 2>&1 &
```

## Storage

Sprout 會扇出到六條 storage lanes：

- SQLite：本地關聯式狀態。
- JSONL：證據和 append-only records。
- Filesystem blobs：大型 payload。
- Redis：cache-oriented lanes。
- Milvus：vector search。
- Neo4j：graph-oriented knowledge。

檔案型 lanes 不需要外部服務。啟用 Redis、Milvus、Neo4j 時，會使用內建 Docker templates。

`db init` 建立已配置 lanes 和必要 schema。`db status` 按 lane 回報健康狀態。Storage lifecycle 和 Docker 說明見 `~/.sprout/docker/README.md`。

```bash
uv run sprout db init
uv run sprout db status
uv run sprout db backup ./backup
uv run sprout db restore ./backup
```

## 設定

使用者設定位於 `~/.sprout/sprout.toml`。保持一個 canonical user config；只有需要明確指定其他路徑時才使用 `SPROUT_CONFIG`。

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

Secrets 從環境變數讀取，不寫進設定檔。

## MCP Server

透過 stdio 執行 MCP server：

```bash
uv run sprout mcp serve
# or
sprout-mcp
```

查看暴露的 tools、resources 和 prompts：

```bash
uv run sprout mcp inspect
```

MCP client 設定範例：

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

Sprout 安裝到目標機器後，可以直接用 `sprout-mcp` 作為 command。倉庫本地開發時，`.venv/bin/python -m Sprout.cli.app mcp serve` 更明確，也更適合交給其他 agent 繼承。

MCP surface 有意保持保守：暴露傳送訊息、建立 session、讀取 history、列出 skills、搜尋 knowledge 等安全操作。高風險寫入、approval decisions 和 growth publishing 不進入 MCP surface。

stdio server protocol-first 啟動：初始 MCP handshake 只註冊 tools、resources 和 prompts，不要求 Temporal、Docker 或可寫 storage。runtime 和 storage 會在具體操作真正需要時 lazy 組裝。

## Temporal 編排

Task queues、scheduled work、evolution automation、web jobs 和 gateway work 可以執行在 Temporal 上。

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d

export TEMPORAL_HOST=127.0.0.1:7233
uv run sprout orchestrator doctor
uv run sprout orchestrator worker
```

## 開發

```bash
uv run pytest
uv run ruff check .
```

建置 Web frontend：

```bash
cd web/frontend
npm install
npm run build
```

倉庫開發流程、分層規則和 CLI/MCP 暴露規則見 [guidance.md](guidance.md)。

## 貢獻者

感謝所有為 SEAM Sprout 做出貢獻的人：

| Contributor | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 授權

本專案使用 [MIT License](LICENSE)。

# SEAM Sprout

SEAM Sprout 是軟體專案的自我進化 AI 代理人。它會接入程式碼庫、理解結構與上下文，然後執行程式碼生成、隔離環境執行、程式碼驗證與整合，並持續推動專案自動成長。

## 主要特色

- 精準專案分析：在行動前理解儲存庫結構、程式碼上下文、工作階段、記憶與知識。
- 程式碼生成：把意圖轉換成具體修改，而不只是文字建議。
- 隔離環境執行：在 git worktree 沙箱中執行生成程式碼。
- 程式碼驗證：每次修改都先測試與檢查。
- 程式碼整合：套用驗證通過的變更，並保留完整軌跡。
- 自動成長：從已完成的工作中學習，產生可審核的改善提案。

## 商業情境

- 需要內建 AI 工程師，而不是額外聊天工具的專案。
- 需要持續修復、重構或補齊功能的程式碼庫。
- 需要安全執行、測試與整合生成程式碼的團隊。
- 需要專案級記憶、進化與稽核能力的企業或組織。
- 高風險動作必須經過 authorization 層。沙箱隔離的是變更可見性，不是 process 權限、OS 使用者或網路。

## 採用技術

| 層級 | 技術 |
|---|---|
| 語言 | Python 3.12+、Node.js 20+ |
| CLI | Typer |
| Web | Starlette、Uvicorn、React、Vite |
| LLM | echo、OpenAI-compatible、aiyallm |
| MCP | MCP Python SDK |
| 持久化 | SQLite、JSONL、Blob、記憶體、Milvus/Neo4j/Redis |
| 設定 | TOML 與型別化 dataclass |
| 工具 | uv、pytest、ruff |

## 安裝

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Web 控制台

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

開啟 `http://127.0.0.1:8000`。Web 控制台提供聊天、任務看板、任務管理、Token、儲存、日誌與設定。

主要 HTTP API：

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

### 語言切換

```text
/language
/language ja
/language zh-Hant
```

支援語言與新增方法請見 `src/Sprout/cli/i18n_languages.md`。

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## 設定

設定集中在 `~/.sprout/sprout.toml`。請勿在專案根目錄重複新增 `sprout.toml`。

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## 開發

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## 專案結構

```text
src/Sprout/
├── runtime/       # Runtime、中介層、生命週期、工作區
├── agent/         # Agent 協定與 AgentLoop
├── session/       # 工作階段與輪次模型
├── memory/        # 記憶組合、預算、快照
├── context/       # AgentContext 與上下文建置
├── message/       # 統一訊息與轉換
├── llm/           # 模型提供者
├── tools/         # ToolSpec、安全執行器
├── skills/        # 版本化技能
├── security/      # 風險、政策、審批
├── storage/       # 儲存契約與本機實作
├── evolution/     # 成長平面
├── execution/     # 變更套用與 Broker
├── gateway/       # Runtime、RPC、任務閘道
├── orchestration/ # 圖編譯器與 Temporal worker
├── rootstock/     # 工作階段持久化後端
├── sandbox/       # Git worktree 沙箱
├── task/          # 任務模型
├── trajectory/    # 軌跡持久化
├── workspace/     # 工作區輔助
├── config/        # 型別化設定與 TOML
├── cli/           # sprout 命令列
└── mcp/           # MCP 服務端與用戶端

web/
├── frontend/      # Vite + React Web 控制台
└── webapi/        # Starlette HTTP/WebSocket 應用
```

## 六個資料庫

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite、JSONL 與 Blob 是一般檔案。Redis、Milvus 與 Neo4j 可設定為容器。詳細請見 `~/.sprout/docker/README.md`。

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
# 或
sprout-mcp
```

對外工具:

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

## 真實模型設定

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

## 貢獻者

| 貢獻者 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 授權

[MIT License](LICENSE)

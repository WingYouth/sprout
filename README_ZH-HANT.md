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

SEAM Sprout 是嵌入軟體專案內部的 AI Engineering Runtime。它把一次變更從「使用者意圖」推進到「程式碼改動、隔離執行、驗證、審批、整合與追蹤」，讓 AI 不只是給建議，而是能在專案邊界內完成可控、可複查的工程閉環。

它解決的核心問題是：軟體專案每天都有大量小而真實的改動需求，但上下文分散、風險難控、驗證繁瑣、歷史經驗難以重用，導致 AI 生成的程式碼很難安全地變成專案裡可信的變更。Sprout 把程式碼庫、會話、記憶、知識、工具、審批和稽核放進同一套 runtime，讓專案可以持續被維護、修復和成長，同時把危險動作留在人類控制之下。

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Sprout 解決什麼

Sprout 面向的不是一次性的程式碼問答，而是專案級的變更交付。它把 AI 放到一條受控 pipeline 裡：先讀專案證據，再形成計畫，隨後在隔離 worktree 中執行修改，運行檢查，生成可審批的變更提案，最後把通過的結果合入專案並留下軌跡。

| 專案裡的真實痛點 | 為什麼難處理 | Sprout 的回答 |
|---|---|---|
| **AI 給了答案，工程還沒完成** | 程式碼片段需要落到正確檔案、適配既有結構、跑測試、處理失敗和衝突。 | 把自然語言請求轉成可執行任務，經過規劃、補丁、測試、提案和正式 apply，而不是停在建議層。 |
| **上下文散落在程式碼、資料庫、文件和歷史對話裡** | 工程判斷依賴倉庫結構、介面約定、storage schema、歷史決策和本輪目標，聊天視窗很難長期持有這些資訊。 | 在 runtime 中組合專案掃描、會話、記憶、知識和 storage evidence，讓下一次任務繼承已有上下文。 |
| **生成程式碼看起來對，但沒人證明它真的能跑** | LLM 輸出缺少同環境驗證；複製貼上後才發現 build 失敗、測試漏跑或介面不匹配。 | 在 git worktree sandbox 中執行變更和檢查，把驗證結果作為變更提案的一部分。 |
| **高風險操作沒有清晰邊界** | 寫檔、跑 process、接觸 network 或 database 都可能帶來破壞、洩密和越權。 | 用 risk levels、policy、approvals 和受控 broker 管理動作；危險變更先停下等待人類確認。 |
| **維護型工作長期堆積** | 小 bug、文件漂移、介面不一致、refactor 和補測試都重要，但經常因為瑣碎被延後。 | 讓專案可以被持續掃描、修復和提出成長候選，形成可審核的自動成長循環。 |
| **一次任務的經驗無法沉澱** | 修過的問題、踩過的坑和專案偏好如果只留在聊天記錄裡，下一次仍要重來。 | 把軌跡、記憶、知識和技能版本化管理，讓完成的工作反哺後續任務。 |
| **入口很多，runtime 不統一** | CLI、Web、MCP、Python API 和外部 gateway 如果各做各的，行為、權限和稽核會漂移。 | 所有入口都走同一套 `create_runtime()` 組裝路徑，共享 storage、authorization、events 和 audit。 |
| **底層 storage 難搭、難檢查、難信任** | 會話、知識、稽核、向量、圖譜和快取分別落在不同 backend，健康狀態很難靠口頭保證。 | 提供 SQLite、JSONL、blob 與 Redis、Milvus、Neo4j 的初始化、狀態檢查和可驗證讀寫鏈路。 |

## 產品能力

- **專案證據優先**：行動前讀取倉庫結構、程式碼上下文、會話、記憶、知識和 storage evidence。
- **可審核規劃**：把專案掃描建議或使用者請求轉成有證據支撐的實作計畫。
- **可控程式碼生成**：生成真實補丁，並透過 broker 控制 file、process 和 apply 行為。
- **隔離執行與驗證**：在 git worktree sandbox 中運行改動和檢查，再決定是否進入主專案。
- **變更整合與追蹤**：把驗證通過的改動形成 proposal、等待 approval、正式 apply，並保留完整軌跡。
- **專案級記憶**：持久化會話、記憶、知識和任務歷史，讓每次工作建立在累積之上。
- **自動成長**：從完成任務中發現後續改進點，產出可審核的成長候選。
- **統一入口**：同一 runtime 可透過 Python API、React Web console、互動式 CLI、MCP server 和 gateway 存取。
- **可重複使用技能**：透過安全掃描 broker 匯入和管理版本化技能，擴展 agent 能力。

## 適用情境

- 專案希望擁有一個內嵌 AI Engineering Runtime，而不是外置聊天助手。
- 團隊需要把 AI 生成的程式碼納入測試、審批、稽核和整合流程。
- 程式碼庫存在持續修復、重構、補測試、補文件和介面對齊需求。
- 組織需要專案級記憶、可追蹤的自動化變更和可重複使用的工程能力。

## 安全邊界

每個高風險動作都要先經過 authorization layer（hard floor → policy → approvals），變更落在 git worktree sandbox 裡。該 sandbox 隔離的是*變更可見性*，不是*權限*：agent 程序與宿主共享 filesystem、OS user、network 和 kernel，沒有 container 或 OS-level backend。七個 execution broker 裡，目前組裝進 runtime 的是 file、process、apply 三個；network、database、git 三個 broker 已實作但尚未接進 agent path。

## 採用技術

| 層級 | 技術 |
|---|---|
| 語言 | Python 3.12+、Node.js 20+ |
| CLI | Typer |
| Web | Starlette、Uvicorn、React、Vite |
| LLM | echo、OpenAI-compatible、aiyallm |
| MCP | MCP Python SDK |
| 持久化 | SQLite、JSONL、檔案系統 blob、記憶體儲存（預留 Milvus、Neo4j、Redis） |
| 設定 | TOML 與型別化 dataclass 設定 |
| 工具 | uv、pytest、pytest-asyncio、ruff |

## 專案結構

```text
src/Sprout/
├── runtime/       # Runtime、中介層、生命週期、工作區、鎖、佇列與組裝
├── agent/         # Agent 協定、AgentLoop、路由、規劃、執行
├── session/       # 會話與輪次模型
├── memory/        # 記憶組合、預算、快照與持久化
├── context/       # AgentContext 與上下文建置
├── message/       # 統一訊息、附件與轉換
├── llm/           # 模型提供者：echo、OpenAI-compatible、aiyallm
├── tools/         # ToolSpec、安全門控執行器、註冊表、系統工具
├── skills/        # 版本化技能與技能倉儲
├── security/      # 風險分級、策略、審批
├── events/        # 程序內事件匯流排
├── registry/      # 通用註冊表
├── storage/       # 儲存契約與本機實作
├── evolution/     # 成長平面、重播、維護與軌跡成長
├── strategy/      # 需求分解、影響分析與驗證計畫
├── artifacts/     # 產物模型與中繼資料
├── capability/    # 能力模型
├── execution/     # 變更套用與 Broker 配接器
├── gateway/       # Runtime、RPC、Task、Daemon 與傳輸閘道
├── orchestration/ # 圖編譯器、Temporal terminal、worker 與 workflows
├── rootstock/     # 會話/根持久化後端
├── sandbox/       # Git worktree sandbox
├── task/          # 任務模型與生命週期
├── trajectory/    # 軌跡持久化
├── workspace/     # 工作區輔助
├── config/        # 型別化設定與 TOML 載入
├── scheduler/     # 排程任務支援
├── cli/           # sprout 命令列
└── mcp/           # MCP 服務端、用戶端與配接器

web/
├── frontend/      # Vite + React Web 控制台
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Starlette HTTP/WebSocket 應用、路由與資料庫

assets/            # 共享 Logo 與靜態資源
~/.sprout/docker/  # 六庫棧：compose 檔案、執行器映像、引導腳本
```

## 需求策略

`src/Sprout/strategy/` 會把「專案掃描建議」或「使用者直接請求」轉化為一份可審核的實作計畫。它的 `StrategyPipeline` 在規劃階段是唯讀的，只在改動任何程式碼之前產出所需證據。

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

影響分析使用兩類證據來源：

- **資料庫證據**：透過 database broker 對 schema、資料表、遷移、持久化記錄，以及既有介面或任務歷史做唯讀檢查。
- **專案證據**：一次全量工作區掃描，定位原始碼檔案、介面、資料庫相關程式碼與測試檔案，並在可用時帶上工作區圖關係。
- **交叉驗證**：比對兩類來源，標記相符項目、僅資料庫存在、僅程式碼存在以及未解決的衝突。衝突會浮上檯面交由人工審核，而不是被默認為編輯許可。

策略層負責需求受理、影響分析、變更模式選擇、驗收標準與測試檔案規劃。`workspace/` 提供唯讀的專案證據，`runtime/changes.py` 負責提案審批與正式 apply/rollback，`execution/` 負責 patch、database、process 與 Git broker。

## 安裝

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

預設設定完全離線：使用 `echo` 模型提供者、本機 SQLite 資料庫，不連接外部 MCP 用戶端。

使用 `aiyallm` 模型提供者時，先安裝對應發行版：

```bash
pip install aiyallm
```

### 六個資料庫，兩條指令

執行時期會在六個資料庫間扇出。其中三個是普通檔案——SQLite、JSONL 證據日誌、Blob 物件庫——完全不需要安裝；另外三個（Redis、Milvus、Neo4j）以容器形式執行。兩條指令覆蓋整個生命週期：

```powershell
sprout db init                    # 建立/初始化所有已設定 lane
sprout db status                  # 逐個回報 healthy/failed
sprout db backup <dir>            # 備份 SQLite 資料庫
sprout db restore <dir>           # 還原 SQLite 資料庫
```
```bash
sprout db init
sprout db status
```

`init` 會建置五個 SQLite schema、JSONL 與 blob 目錄、三個 Milvus collection 以及 Neo4j 約束——冪等，且不寫入任何資料列。`test` 透過常規儲存束寫入一個會話、兩個輪次、一條記憶事實與一份超大的上下文快照，然後用每條 lane 自己的用戶端把它們讀回來，這才是「六個庫都正常」的可驗證事實，而非一句聲明。`sprout db init` 會初始化所有已設定 lane，`sprout db status` 會逐個檢查。使用 Docker 時，`init` 還會拉取三個服務映像（被封鎖的 Docker Hub 有鏡像回退），建置執行器映像，啟動各 lane 並完成驗證。

連接埠、設定、三層測試、無 Docker 設定與排障見 `~/.sprout/docker/README.md`。

## 使用方式

### Agent

Python API 是核心使用入口。建置一個 runtime 並傳送 `Message`：

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

所有入口都透過 `create_runtime()` 走同一條組裝路徑。

### Web

Web 控制台是一個基於元件的 React 應用，使用 Vite 建置。

先建置一次前端：

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

然後啟動 Web 控制台：

```bash
uv run sprout serve
```

開啟 `http://127.0.0.1:8000`。Web 應用提供聊天、任務看板、任務管理與設定功能。

前端開發熱更新：

```bash
cd web/frontend
npm run dev
```

可用的 HTTP 端點包括：

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

WebSocket 位址為 `ws://127.0.0.1:8000/ws/chat`。

### CLI

```bash
uv run sprout --help
uv run sprout                     # 互動式聊天
uv run sprout chat "hello"        # 單發訊息
uv run sprout info                # 查看執行時期與設定快照
uv run sprout project workspace <path>   # 本機開啟工作區
uv run sprout remote workspace-list      # 操作遠端 SEMA 服務
uv run sprout db init             # 初始化所有已設定 lane
uv run sprout db status           # 回報 healthy/failed
uv run sprout db backup ./backup  # 備份本機資料庫
uv run sprout mcp inspect         # 查看 MCP 定義
uv run sprout evolution candidates  # 成長層：流水線已產出的候選
uv run sprout skills import ~/code/my-skills   # 從本機目錄匯入技能
uv run sprout skills list         # 查看已安裝技能
uv run sprout skills index --rebuild   # 同步快照，回報登錄檔與磁碟的分歧
uv run sprout skills forget <name>     # 刪除登錄檔記錄，保留檔案
uv run sprout serve               # 啟動 Web 控制台與 API
uv run sprout stop serve          # 停止 Web 控制台
```

`skills import` 會遞迴掃描目錄：含 `SKILL.md` 的資料夾算作一個技能，獨立的 `*.toml` 單一檔案也算一筆。巢狀布局（`skills/writing/docs/SKILL.md`）同樣能找到，套件依賴目錄會被跳過；每個技能都走子系統統一的 broker——先做安全掃描，再由策略引擎裁決。本機路徑屬於第一方來源，因此無需審批；掃描器的致命項底線仍舊生效，且無法被審批越過。

### 語言切換

互動式 CLI 可以在不重新啟動的情況下切換選單語言：

```text
/language
/language ja
/language zh-Hant
```

支援的語言見 [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md)。選擇結果保存在 `~/.sprout/settings.json`，下一次啟動會繼續使用。

### Temporal

任務編排、佇列、排程、成長自動化、Web 任務與 Gateway 工作都可以執行在 Temporal 上。

用倉庫內建的 Compose 棧啟動本機 Temporal 服務端：

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

無需安裝 Temporal CLI 即可檢查連通性：

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` 會回報服務端可達性、服務端版本、命名空間是否存在，以及設定的任務佇列上正在輪詢的 worker 數量。

### MCP

透過 stdio 執行 MCP 服務端：

```bash
uv run sprout mcp serve
# 或
sprout-mcp
```

MCP 服務端只暴露安全操作：傳送訊息、建立會話、讀取會話歷史、列出技能與搜尋知識。高風險寫入、審批與成長發布不在 MCP 暴露範圍內。

查看對外暴露的工具、資源與提示詞：

```bash
uv run sprout mcp inspect
```

## 設定

使用者設定位於 `~/.sprout/sprout.toml`。請只保留這一份設定，不要在專案根目錄重複新增 `sprout.toml`；僅在必要時用 `SPROUT_CONFIG` 指向其他顯式路徑。

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

## 真實模型設定

編輯 `~/.sprout/sprout.toml` 以使用 DeepSeek 或其他提供者：

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
# Sprout 執行時期 authority：conversation 支援 sqlite | jsonl | blobstore；
# Milvus/Neo4j/Redis 永遠只是可重建的衍生層。
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

金鑰只從環境變數讀取，不會寫入設定檔。

## 開發

```bash
uv run pytest
uv run ruff check .
```

開發流程與 CLI/MCP 暴露規則見 [guidance.md](guidance.md)。

## 貢獻者

感謝所有為 SEAM Sprout 做出貢獻的人：

| 貢獻者 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 授權

本專案使用 [MIT License](LICENSE)。

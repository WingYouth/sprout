# SEAM Sprout

SEAM Sprout は、ソフトウェアプロジェクトのための自己進化型 AI エージェントです。コードベースに接続し、構造と文脈を理解し、コードを生成し、隔離環境で実行し、結果を検証してから変更を統合します。

## 主な特徴

- 正確なプロジェクト解析: リポジトリ構造、コード文脈、セッション、記憶、知識を事前に確認します。
- コード生成: 意図を具体的な変更に変換します。
- 隔離実行: git worktree サンドボックスで生成コードを実行します。
- コード検証: 統合前にテストとチェックを行います。
- コード統合: 検証済みの変更をプロジェクトへ適用し、履歴を残します。
- 自動成長: 完了した作業から学び、将来の改善提案を作成します。

## ビジネス用途

- 別のチャットツールではなく、組み込み AI エンジニアが必要なプロジェクト。
- 継続的な修正、リファクタリング、機能追加が必要なコードベース。
- 生成コードを安全に実行、テスト、統合したいチーム。
- プロジェクト単位の記憶、進化、監査が必要な組織。
- リスクのある操作は承認プレーンを通ります。sandbox は変更の可視性を隔離しますが、プロセス権限や OS ユーザー、ネットワークをコンテナ分離するものではありません。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| 言語 | Python 3.12+、Node.js 20+ |
| CLI | Typer |
| Web | Starlette、Uvicorn、React、Vite |
| LLM | echo、OpenAI-compatible、aiyallm |
| MCP | MCP Python SDK |
| 永続化 | SQLite、JSONL、Blob、メモリ、Milvus/Neo4j/Redis |
| 設定 | TOML + 型付き dataclass |
| ツール | uv、pytest、ruff |

## インストール

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Web コンソール

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

`http://127.0.0.1:8000` を開きます。Web コンソールにはチャット、タスクボード、タスク管理、トークン管理、ストレージ、ログ、設定があります。

主な HTTP API:

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

### 言語切り替え

```text
/language
/language ja
/language zh-Hant
```

対応言語と追加方法は `src/Sprout/cli/i18n_languages.md` を参照してください。

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## 設定

設定は `~/.sprout/sprout.toml` に集約します。プロジェクトローカルの重複設定は追加しないでください。

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## 開発

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## プロジェクト構成

```text
src/Sprout/
├── runtime/       # ランタイム、ミドルウェア、ライフサイクル、ワークスペース
├── agent/         # エージェントプロトコルと AgentLoop
├── session/       # セッションとターンモデル
├── memory/        # 記憶の構成、予算、スナップショット
├── context/       # AgentContext と文脈構築
├── message/       # 統一メッセージと変換
├── llm/           # モデルプロバイダー
├── tools/         # ToolSpec、セキュリティ付き実行器
├── skills/        # バージョン化されたスキル
├── security/      # リスク、ポリシー、承認
├── storage/       # ストレージ契約とローカル実装
├── evolution/     # 成長プレーン
├── execution/     # 変更適用とブローカー
├── gateway/       # ランタイム、RPC、タスクゲートウェイ
├── orchestration/ # グラフコンパイラと Temporal worker
├── rootstock/     # セッション永続化バックエンド
├── sandbox/       # git worktree サンドボックス
├── task/          # タスクモデル
├── trajectory/    # 軌跡の永続化
├── workspace/     # ワークスペースヘルパー
├── config/        # 型付き設定と TOML
├── cli/           # sprout コマンドライン
└── mcp/           # MCP サーバーとクライアント

web/
├── frontend/      # Vite + React Web コンソール
└── webapi/        # Starlette HTTP/WebSocket アプリ
```

## 6 データベース

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite、JSONL、Blob は通常のファイルです。Redis、Milvus、Neo4j はコンテナとして構成できます。詳細は `~/.sprout/docker/README.md` を参照してください。

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
# または
sprout-mcp
```

公開ツール:

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

## 実際のモデル設定

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

## コントリビューター

| 貢献者 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## ライセンス

[MIT License](LICENSE)

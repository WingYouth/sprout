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

SEAM Sprout は、ソフトウェアプロジェクト内部に組み込む AI Engineering Runtime です。ユーザーの意図からコード変更、隔離実行、検証、承認、統合、トレースまでをつなぎ、AI が提案するだけでなく、プロジェクト境界の内側で制御可能かつレビュー可能な engineering loop を完了できるようにします。

Sprout が解く中心課題は、実際のソフトウェア開発には小さいが重要な変更が大量にあり、その一方でコンテキストは散らばり、リスク制御は難しく、検証は手間がかかり、蓄積した知識も再利用されにくいことです。Sprout は codebase、session、memory、knowledge、tools、approvals、audit trail をひとつの runtime にまとめ、危険な操作は人間が制御したまま、プロジェクトを継続的に保守・修復・改善できるようにします。

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Sprout が解決すること

Sprout は一回限りのコード Q&A ではなく、プロジェクトレベルの変更デリバリーのために作られています。AI を制御された pipeline に置き、プロジェクト証拠を読み、計画を作り、隔離された worktree でコードを変更し、checks を実行し、レビュー可能な proposal を作り、承認済みの結果を trace 付きでプロジェクトへ適用します。

| 実際のプロジェクトの痛み | 難しい理由 | Sprout の答え |
|---|---|---|
| **AI は答えを出すが、engineering work は終わっていない** | snippet は正しいファイルへ入り、既存設計に合い、tests を通り、conflict に耐える必要があります。 | 自然言語の依頼を planning、patches、checks、proposals、formal apply を伴う実行可能タスクへ変換します。 |
| **コンテキストが code、data、docs、過去の会話に散らばる** | 良い判断には repo 構造、interfaces、storage schema、過去の決定、現在の goal が必要です。 | project scan、sessions、memory、knowledge、storage evidence を runtime 内で組み合わせます。 |
| **生成コードはもっともらしいが、証明されていない** | LLM 出力は対象環境で実行される前にレビューされがちです。 | git-worktree sandbox で変更と checks を実行し、検証 evidence を proposal に添付します。 |
| **リスクのある操作には強制できる境界が必要** | file writes、process execution、network access、database access は破壊、漏えい、ownership 回避につながります。 | risk levels、policies、approvals、controlled brokers を通して危険な操作を扱います。 |
| **保守作業が積み上がる** | 小さな bug、docs drift、interface mismatch、refactor、足りない tests は重要でも後回しになります。 | 継続的に scan、repair し、将来改善のための reviewable growth candidates を作ります。 |
| **学習がタスクをまたいで積み上がらない** | 修正、プロジェクトの好み、workflow knowledge が chat history に埋もれます。 | trajectories、memory、knowledge、versioned skills を永続化し、次の作業に効かせます。 |
| **複数の surface がずれる** | CLI、Web、MCP、Python API、gateways が別々の behavior、permissions、audit path を持ちがちです。 | すべての surface を同じ `create_runtime()` 経路へ通し、storage、authorization、events、audit を共有します。 |
| **storage と infrastructure を信頼しにくい** | sessions、knowledge、audit、vectors、graph、cache は別 backend に分かれます。 | SQLite、JSONL、blobs、Redis、Milvus、Neo4j に対して init、status checks、検証可能な read/write path を提供します。 |

## プロダクト能力

- **プロジェクト evidence 優先**：repo 構造、コード文脈、sessions、memory、knowledge、storage evidence を読んでから行動します。
- **レビュー可能な planning**：project scan の提案や直接リクエストを evidence-backed implementation plan に変換します。
- **制御された code generation**：実際の patches を作り、file、process、change 操作を brokers 経由で適用します。
- **隔離実行と検証**：メインプロジェクトへ触る前に git-worktree sandbox で変更と checks を実行します。
- **変更統合と traceability**：検証済み作業を proposals にし、approval を待ち、accepted changes を apply し、trace を残します。
- **プロジェクトレベル memory**：sessions、memory、knowledge、task history を永続化します。
- **自動成長**：完了した作業から学び、将来改善の reviewable candidates を作ります。
- **統一された入口**：Python API、React web console、interactive CLI、MCP server、gateways から同じ runtime を使います。
- **再利用可能な skills**：safety-scanning broker を通して versioned skills を import・管理します。

## ユースケース

- 外部チャットアシスタントではなく、組み込み AI Engineering Runtime が必要なプロジェクト。
- AI 生成コードを tests、approvals、audit、integration に通したいチーム。
- 継続的な修復、refactor、test coverage、docs、interface alignment が必要な codebase。
- プロジェクトレベル memory、traceable automation、再利用可能な engineering capabilities が必要な組織。

## 安全境界

危険な操作はすべて authorization layer（hard floor → policy layers → approvals）を通り、変更は git-worktree sandbox に入ります。この sandbox が隔離するのは*変更の可視性*であり*権限*ではありません。agent processes は host filesystem、OS user、network、kernel を共有し、container や OS-level backend はありません。7 つの execution brokers のうち、現時点で runtime に組み込まれているのは file、process、apply です。network、database、git は実装済みですが、まだ agent path には接続されていません。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| 言語 | Python 3.12+、Node.js 20+ |
| CLI | Typer |
| Web | Starlette、Uvicorn、React、Vite |
| LLM | echo、OpenAI-compatible、aiyallm |
| MCP | MCP Python SDK |
| 永続化 | SQLite、JSONL、ファイルシステム blob、インメモリストア（Milvus、Neo4j、Redis は予約） |
| 設定 | TOML と型付き dataclass 設定 |
| ツール | uv、pytest、pytest-asyncio、ruff |

## プロジェクト構成

```text
src/Sprout/
├── runtime/       # runtime、ミドルウェア、ライフサイクル、ワークスペース、ロック、キュー、組み立て
├── agent/         # エージェントプロトコル、AgentLoop、ルーティング、計画、実行
├── session/       # セッションとターンモデル
├── memory/        # 記憶の構成、予算、スナップショット、永続化
├── context/       # AgentContext と文脈構築
├── message/       # 統一メッセージ、添付、変換
├── llm/           # モデルプロバイダー：echo、OpenAI-compatible、aiyallm
├── tools/         # ToolSpec、セキュリティ付き実行器、レジストリ、システムツール
├── skills/        # バージョン管理されたスキルとスキルリポジトリ
├── security/      # リスクレベル、ポリシー、承認
├── events/        # プロセス内イベントバス
├── registry/      # 汎用レジストリ
├── storage/       # ストレージ契約とローカル実装
├── evolution/     # 成長プレーン、リプレイ、メンテナンス、軌跡の成長
├── strategy/      # 要件分解、影響分析、検証計画
├── artifacts/     # アーティファクトモデルとメタデータ
├── capability/    # ケイパビリティモデル
├── execution/     # 変更適用とブローカーアダプター
├── gateway/       # runtime、RPC、タスク、デーモン、トランスポートゲートウェイ
├── orchestration/ # グラフコンパイラ、Temporal terminal、ワーカー、ワークフロー
├── rootstock/     # セッション/ルート永続化バックエンド
├── sandbox/       # Git worktree サンドボックス
├── task/          # タスクモデルとライフサイクル
├── trajectory/    # 軌跡の永続化
├── workspace/     # ワークスペースヘルパー
├── config/        # 型付き設定と TOML 読み込み
├── scheduler/     # スケジュールタスクのサポート
├── cli/           # sprout コマンドライン
└── mcp/           # MCP サーバー、クライアント、アダプター

web/
├── frontend/      # Vite + React Web コンソール
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Starlette HTTP/WebSocket アプリ、ルート、データベース

assets/            # 共有ロゴと静的アセット
~/.sprout/docker/  # 6 データベーススタック：compose ファイル、ランナーイメージ、ブートストラップ
```

## 要件戦略

`src/Sprout/strategy/` は、プロジェクトスキャンの提案やユーザーの直接リクエストを、レビュー可能な実装計画へ変換します。その `StrategyPipeline` は計画段階では読み取り専用で、コードを変更する前に必要な証拠を生成します。

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

影響分析は 2 種類の証拠源を使います：

- **データベース証拠**：database broker を通じた読み取り専用アクセスで、スキーマ、テーブル、マイグレーション、永続化されたレコード、既存のインターフェースやタスク履歴を確認します。
- **プロジェクト証拠**：完全なワークスペーススキャンで、ソースファイル、インターフェース、データベース関連コード、テストファイルを特定し、利用可能であればワークスペースグラフの関係も含めます。
- **クロスバリデーション**：両方の情報源を比較し、一致、データベースのみ、コードのみ、未解決の競合をマークします。競合は黙って編集許可とみなされるのではなく、人間のレビューのために提示されます。

戦略レイヤーは、要件の受け入れ、影響分析、変更モードの選択、受け入れ基準、テストファイル計画を担当します。`workspace/` は読み取り専用のプロジェクト証拠を提供し、`runtime/changes.py` は提案の承認と正式な apply/rollback を担当し、`execution/` は patch・database・process・Git ブローカーを担当します。

## インストール

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

デフォルト設定は完全にオフラインです：`echo` モデルプロバイダー、ローカル SQLite データベース、外部 MCP クライアントなし。

`aiyallm` モデルプロバイダーを使う場合は、その配布物をインストールします：

```bash
pip install aiyallm
```

### 6 つのデータベースを 2 つのコマンドで

runtime は 6 つのデータベースへ分岐します。3 つはただのファイル（SQLite、JSONL 証跡ログ、blob ストア）なのでインストールは一切不要です。残りの 3 つ（Redis、Milvus、Neo4j）はコンテナです。ライフサイクルは 2 つのコマンドで網羅されます：

```powershell
sprout db init                    # 設定済み lane をすべて作成/初期化
sprout db status                  # lane ごとに healthy/failed を報告
sprout db backup <dir>            # SQLite データベースをバックアップ
sprout db restore <dir>           # SQLite データベースを復元
```
```bash
sprout db init
sprout db status
```

`init` は 5 つの SQLite スキーマ、JSONL と blob のディレクトリ、3 つの Milvus コレクション、Neo4j 制約を構築します。冪等で、行は一切書き込みません。`test` は通常のストレージバンドルを通じてセッション 1 件、ターン 2 件、記憶ファクト 1 件、過大なコンテキストスナップショット 1 件を書き込み、その後各 lane をその lane 自身のクライアントで読み戻します。これにより「6 つすべて稼働中」は主張ではなく検証された事実になります。`sprout db init` は設定済み lane をすべて初期化し、`sprout db status` はそれらを 1 つずつ確認します。Docker を使う場合、`init` は 3 つのサービスイメージを pull し（ブロックされた Docker Hub にはミラーフォールバックあり）、ランナーイメージをビルドし、lane を起動して検証します。

ポート、設定、3 層のテスト、Docker なしのプロファイル、トラブルシューティングは `~/.sprout/docker/README.md` を参照してください。

## 使い方

### Agent

Python API が中心となる利用面です。runtime を組み立てて `Message` を送ります：

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

すべてのエントリポイントは単一の組み立て経路として `create_runtime()` を使います。

### Web

Web コンソールは、Vite でビルドするコンポーネントベースの React アプリケーションです。

まずフロントエンドを一度ビルドします：

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

次に Web コンソールを起動します：

```bash
uv run sprout serve
```

`http://127.0.0.1:8000` を開きます。Web アプリケーションはチャット、タスクボード、タスク管理、設定を提供します。

ホットリロード付きのフロントエンド開発：

```bash
cd web/frontend
npm run dev
```

利用可能な HTTP エンドポイント：

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

WebSocket エンドポイントは `ws://127.0.0.1:8000/ws/chat` です。

### CLI

```bash
uv run sprout --help
uv run sprout                     # 対話型チャット
uv run sprout chat "hello"        # ワンショットメッセージ
uv run sprout info                # runtime と設定のスナップショット
uv run sprout project workspace <path>   # ローカルワークスペースを開く
uv run sprout remote workspace-list      # リモート SEMA サービスを操作
uv run sprout db init             # 設定済み lane をすべて初期化
uv run sprout db status           # healthy/failed を報告
uv run sprout db backup ./backup  # ローカルデータベースをバックアップ
uv run sprout mcp inspect         # MCP 定義を確認
uv run sprout evolution candidates  # 成長レイヤー：パイプラインの生成物
uv run sprout skills import ~/code/my-skills   # ローカルディレクトリからスキルをインポート
uv run sprout skills list         # インストール済みを表示
uv run sprout skills index --rebuild   # スナップショットを同期し、レジストリとディスクの乖離を報告
uv run sprout skills forget <name>     # レジストリ行を削除し、ファイルは残す
uv run sprout serve               # Web コンソールと API を起動
uv run sprout stop serve          # Web コンソールを停止
```

`skills import` はディレクトリを再帰的に走査し、`SKILL.md` を含むフォルダーを 1 つのスキル、単一ファイルの `*.toml` を個別エントリとして扱います。ネストしたレイアウト（`skills/writing/docs/SKILL.md`）も見つけ、ベンダー提供ディレクトリはスキップします。各スキルはサブシステムの他の部分と同じブローカーを通じてインストールされます。まず安全ではない内容をスキャンし、次にポリシーエンジンが判断します。ローカルパスはファーストパーティの情報源であるため承認は不要です。スキャナーの致命的検出フロアは依然として有効で、承認によって覆すことはできません。

### 言語切り替え

対話型 CLI は再起動せずにメニュー言語を切り替えられます：

```text
/language
/language ja
/language zh-Hant
```

対応言語は [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md) に記載されています。選択内容は `~/.sprout/settings.json` に保存され、次回のセッションで再利用されます。

### Temporal

タスクオーケストレーション、キュー、スケジュール、進化の自動化、Web ジョブ、ゲートウェイ作業は Temporal 上で実行できます。

同梱の Compose スタックでローカルの Temporal サーバーを起動します：

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Temporal CLI をインストールせずに到達可能性を確認します：

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor` はサーバーの到達可能性、サーバーバージョン、ネームスペースの有無、設定されたタスクキューでポーリング中のワーカー数を報告します。

### MCP

stdio 経由で MCP サーバーを実行します：

```bash
uv run sprout mcp serve
# または
sprout-mcp
```

サーバーは安全な操作のみを公開します：メッセージ送信、セッション作成、セッション履歴の読み取り、スキルの一覧表示、知識の検索です。高リスクな書き込み、承認、成長の公開は MCP の範囲外です。

公開されているツール、リソース、プロンプトを確認します：

```bash
uv run sprout mcp inspect
```

## 設定

ユーザー設定は `~/.sprout/sprout.toml` にあります。設定はこの単一ファイルにまとめ、プロジェクトローカルに重複する `sprout.toml` を追加しないでください。`SPROUT_CONFIG` は必要に応じて別の明示的なパスを指す場合にのみ使います。

Project Runtime MCP ツール：

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

## 実モデルの設定

DeepSeek や別のプロバイダーを使うには `~/.sprout/sprout.toml` を編集します：

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
# Sprout runtime の authority：conversation は sqlite | jsonl | blobstore。
# Milvus/Neo4j/Redis はあくまで再構築可能な派生層です。
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

シークレットは環境変数から読み取られ、設定ファイルには決して書き込まれません。

## 開発

```bash
uv run pytest
uv run ruff check .
```

開発ワークフローと CLI/MCP 公開ルールは [guidance.md](guidance.md) を参照してください。

## コントリビューター

SEAM Sprout に貢献してくれたすべての方に感謝します：

| コントリビューター | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## ライセンス

本プロジェクトは [MIT License](LICENSE) の下で提供されます。

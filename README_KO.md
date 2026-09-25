# SEAM Sprout

SEAM Sprout은 소프트웨어 프로젝트를 위한 자기 진화형 AI 에이전트입니다. 코드베이스에 연결해 구조와 문맥을 이해하고, 코드를 생성하고, 격리 환경에서 실행하고, 검증한 뒤 변경을 통합합니다.

## 주요 특징

- 정밀한 프로젝트 분석: 저장소 구조, 코드 문맥, 세션, 메모리, 지식을 사전에 확인합니다.
- 코드 생성: 의도를 구체적인 변경으로 변환합니다.
- 격리 실행: git worktree 샌드박스에서 생성 코드를 실행합니다.
- 코드 검증: 통합 전에 테스트와 점검을 수행합니다.
- 코드 통합: 검증된 변경을 프로젝트에 적용하고 이력을 남깁니다.
- 자동 성장: 완료된 작업에서 학습하고 개선 제안을 만듭니다.

## 비즈니스 활용

- 별도 채팅 도구가 아닌 내장 AI 엔지니어가 필요한 프로젝트.
- 지속적인 수정, 리팩터링, 기능 보완이 필요한 코드베이스.
- 생성 코드를 안전하게 실행·테스트·통합하려는 팀.
- 프로젝트 단위 메모리, 진화, 감사가 필요한 조직.
- 위험한 작업은 승인 계층을 통과합니다. 샌드박스는 변경 가시성을 격리하며 프로세스 권한, OS 사용자, 네트워크를 컨테이너 수준으로 격리하지 않습니다.

## 기술 스택

| 계층 | 기술 |
|---|---|
| 언어 | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| 저장소 | SQLite, JSONL, Blob, 메모리, Milvus/Neo4j/Redis |
| 설정 | TOML + typed dataclass |
| 도구 | uv, pytest, ruff |

## 설치

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

## Web 콘솔

```bash
cd web/frontend
npm install
npm run build
cd ../..
uv run sprout serve
```

`http://127.0.0.1:8000`을 엽니다. Web 콘솔에는 채팅, 작업 보드, 작업 관리, 토큰 관리, 저장소, 로그, 설정이 있습니다.

주요 HTTP API:

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

### 언어 전환

```text
/language
/language ja
/language zh-Hant
```

지원 언어와 추가 방법은 `src/Sprout/cli/i18n_languages.md`를 참조하세요.

## Temporal

```bash
temporal server start-dev
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator worker
```

## 설정

설정은 `~/.sprout/sprout.toml`에 모아 둡니다. 프로젝트 로컬 중복 설정은 추가하지 마세요.

```toml
[model]
provider = "aiyallm"
model = "your-model"
api_key_env = "YOUR_PROVIDER_API_KEY"

[web]
host = "127.0.0.1"
port = 8000
```

## 개발

```bash
uv run ruff check .
uv run pytest
uv run sprout --help
```

## 프로젝트 구조

```text
src/Sprout/
├── runtime/       # 런타임, 미들웨어, 수명 주기, 워크스페이스
├── agent/         # 에이전트 프로토콜과 AgentLoop
├── session/       # 세션 및 턴 모델
├── memory/        # 메모리 구성, 예산, 스냅샷
├── context/       # AgentContext와 문맥 구축
├── message/       # 통합 메시지와 변환
├── llm/           # 모델 제공자
├── tools/         # ToolSpec, 보안 실행기
├── skills/        # 버전 관리 스킬
├── security/      # 위험, 정책, 승인
├── storage/       # 저장소 계약과 로컬 구현
├── evolution/     # 성장 평면
├── execution/     # 변경 적용과 브로커
├── gateway/       # 런타임, RPC, 작업 게이트웨이
├── orchestration/ # 그래프 컴파일러와 Temporal worker
├── rootstock/     # 세션 영속화 백엔드
├── sandbox/       # git worktree 샌드박스
├── task/          # 작업 모델
├── trajectory/    # 궤적 영속화
├── workspace/     # 워크스페이스 헬퍼
├── config/        # 타입 설정과 TOML
├── cli/           # sprout 명령줄
└── mcp/           # MCP 서버와 클라이언트

web/
├── frontend/      # Vite + React Web 콘솔
└── webapi/        # Starlette HTTP/WebSocket 앱
```

## 6개 데이터베이스

```bash
sprout db init
sprout db status
sprout db backup <dir>
sprout db restore <dir>
```

SQLite, JSONL, Blob은 일반 파일입니다. Redis, Milvus, Neo4j는 컨테이너로 구성할 수 있습니다. 자세한 내용은 `~/.sprout/docker/README.md`를 참조하세요.

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
# 또는
sprout-mcp
```

공개 도구:

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

## 실제 모델 설정

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

## 기여자

| 기여자 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 라이선스

[MIT License](LICENSE)

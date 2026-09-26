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

SEAM Sprout는 소프트웨어 프로젝트 내부에 내장되는 AI Engineering Runtime입니다. 사용자 의도에서 코드 변경, 격리 실행, 검증, 승인, 통합, 추적까지 이어 주어, AI가 제안에 그치지 않고 프로젝트 경계 안에서 제어 가능하고 검토 가능한 engineering loop를 완료할 수 있게 합니다.

Sprout가 해결하는 핵심 문제는 실제 소프트웨어 작업에는 작지만 중요한 변경이 계속 생기지만, 컨텍스트는 흩어져 있고, 위험은 통제하기 어렵고, 검증은 번거로우며, 어렵게 얻은 프로젝트 지식은 재사용되기 어렵다는 점입니다. Sprout는 codebase, sessions, memory, knowledge, tools, approvals, audit trail을 하나의 runtime에 모아 위험한 작업은 사람이 통제하면서 프로젝트를 지속적으로 유지보수, 수리, 개선할 수 있게 합니다.

<div align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-8b5cf6" /></a>
  <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node.js-20%2B-339933" /></a>
  <a href="https://pypi.org/project/aiyallm/"><img src="https://img.shields.io/pypi/v/aiyallm?color=8b5cf6" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-10b981" /></a>
</div>

## Sprout가 해결하는 것

Sprout는 일회성 코드 Q&A가 아니라 프로젝트 수준의 변경 전달을 위한 도구입니다. AI를 통제된 pipeline 안에 두고, 프로젝트 evidence를 읽고, 계획을 세우고, 격리된 worktree에서 코드를 수정하고, checks를 실행하고, 검토 가능한 proposal을 만든 뒤 승인된 결과를 trace와 함께 프로젝트에 적용합니다.

| 실제 프로젝트의 문제 | 어려운 이유 | Sprout의 답 |
|---|---|---|
| **AI는 답을 주지만 engineering work는 끝나지 않습니다** | snippet은 올바른 파일에 들어가야 하고, 기존 설계에 맞아야 하며, tests를 통과하고 conflicts도 견뎌야 합니다. | 자연어 요청을 planning, patches, checks, proposals, formal apply가 있는 실행 가능한 task로 바꿉니다. |
| **컨텍스트가 code, data, docs, 이전 대화에 흩어져 있습니다** | 좋은 판단에는 repo 구조, interfaces, storage schema, 과거 결정, 현재 goal이 필요합니다. | project scans, sessions, memory, knowledge, storage evidence를 하나의 runtime 안에서 결합합니다. |
| **생성 코드는 그럴듯하지만 증명되지 않았습니다** | LLM 출력은 대상 환경에서 실행되기 전에 검토되는 경우가 많습니다. | git-worktree sandbox에서 변경과 checks를 실행하고 verification evidence를 proposal에 붙입니다. |
| **위험한 작업에는 강제 가능한 경계가 필요합니다** | file writes, process execution, network access, database access는 시스템 파손, secret 유출, ownership 우회를 만들 수 있습니다. | risk levels, policies, approvals, controlled brokers를 통해 위험한 작업을 라우팅합니다. |
| **유지보수 작업이 계속 쌓입니다** | 작은 bug, documentation drift, interface mismatch, refactor, 부족한 tests는 중요하지만 쉽게 미뤄집니다. | 지속적으로 scan, repair하고 향후 개선을 위한 reviewable growth candidates를 만듭니다. |
| **학습이 task 사이에서 누적되지 않습니다** | 수정, 프로젝트 선호, workflow knowledge가 chat history에 묻힙니다. | trajectories, memory, knowledge, versioned skills를 영속화해 다음 작업에 반영합니다. |
| **여러 surface가 서로 어긋납니다** | CLI, Web, MCP, Python API, gateways가 서로 다른 behavior, permissions, audit path를 갖기 쉽습니다. | 모든 surface를 같은 `create_runtime()` 경로로 보내 storage, authorization, events, audit를 공유합니다. |
| **storage와 infrastructure를 신뢰하기 어렵습니다** | sessions, knowledge, audit, vectors, graph, cache가 서로 다른 backends에 있을 수 있습니다. | SQLite, JSONL, blobs, Redis, Milvus, Neo4j 전반에 init, status checks, 검증 가능한 read/write paths를 제공합니다. |

## 제품 역량

- **프로젝트 evidence 우선**: repo 구조, 코드 컨텍스트, sessions, memory, knowledge, storage evidence를 읽고 행동합니다.
- **검토 가능한 planning**: project scan 제안이나 직접 요청을 evidence-backed implementation plan으로 바꿉니다.
- **통제된 code generation**: 실제 patches를 만들고 file, process, change 작업을 brokers로 적용합니다.
- **격리 실행과 검증**: main project를 건드리기 전에 git-worktree sandbox에서 변경과 checks를 실행합니다.
- **변경 통합과 traceability**: 검증된 작업을 proposals로 만들고, approval을 기다리고, accepted changes를 apply하며 trace를 남깁니다.
- **프로젝트 수준 memory**: sessions, memory, knowledge, task history를 영속화합니다.
- **자동 성장**: 완료된 작업에서 학습하고 향후 개선을 위한 reviewable candidates를 만듭니다.
- **통합된 entry points**: Python API, React web console, interactive CLI, MCP server, gateways가 같은 runtime을 사용합니다.
- **재사용 가능한 skills**: safety-scanning broker를 통해 versioned skills를 가져오고 관리합니다.

## 사용 사례

- 외부 채팅 assistant가 아니라 내장 AI Engineering Runtime이 필요한 프로젝트.
- AI 생성 코드를 tests, approvals, audit, integration 절차에 태우고 싶은 팀.
- 지속적인 repair, refactor, test coverage, docs, interface alignment가 필요한 codebase.
- 프로젝트 수준 memory, traceable automation, 재사용 가능한 engineering capabilities가 필요한 조직.

## 안전 경계

모든 위험한 작업은 authorization layer(hard floor → policy layers → approvals)를 통과하며, 변경은 git-worktree sandbox에 들어갑니다. 이 sandbox가 격리하는 것은 *권한*이 아니라 *변경 가시성*입니다. agent processes는 host filesystem, OS user, network, kernel을 공유하며 container나 OS-level backend는 없습니다. 일곱 개 execution brokers 중 현재 runtime에 조립된 것은 file, process, apply이고, network, database, git은 구현되었지만 아직 agent path에는 연결되지 않았습니다.

## 기술 스택

| 계층 | 기술 |
|---|---|
| 언어 | Python 3.12+, Node.js 20+ |
| CLI | Typer |
| Web | Starlette, Uvicorn, React, Vite |
| LLM | echo, OpenAI-compatible, aiyallm |
| MCP | MCP Python SDK |
| 영속성 | SQLite, JSONL, 파일 시스템 blob, 인메모리 저장소(Milvus, Neo4j, Redis 예약) |
| 설정 | TOML 및 타입 지정 dataclass 설정 |
| 도구 | uv, pytest, pytest-asyncio, ruff |

## 프로젝트 구조

```text
src/Sprout/
├── runtime/       # runtime, 미들웨어, 수명주기, 워크스페이스, 잠금, 큐, 조립
├── agent/         # 에이전트 프로토콜, AgentLoop, 라우팅, 계획, 실행
├── session/       # 세션 및 턴 모델
├── memory/        # 메모리 구성, 예산, 스냅샷, 영속화
├── context/       # AgentContext 및 컨텍스트 빌드
├── message/       # 통합 메시지, 첨부 파일, 변환
├── llm/           # 모델 제공자: echo, OpenAI-compatible, aiyallm
├── tools/         # ToolSpec, 보안 게이트 실행기, 레지스트리, 시스템 도구
├── skills/        # 버전 관리되는 스킬과 스킬 저장소
├── security/      # 위험 수준, 정책, 승인
├── events/        # 프로세스 내 이벤트 버스
├── registry/      # 범용 레지스트리
├── storage/       # 저장소 계약 및 로컬 구현
├── evolution/     # 성장 계층, 재생, 유지보수, 궤적 성장
├── strategy/      # 요구사항 분해, 영향 분석, 검증 계획
├── artifacts/     # 아티팩트 모델 및 메타데이터
├── capability/    # 기능 모델
├── execution/     # 변경 적용 및 브로커 어댑터
├── gateway/       # runtime, RPC, 태스크, 데몬, 전송 게이트웨이
├── orchestration/ # 그래프 컴파일러, Temporal 터미널, 워커, 워크플로
├── rootstock/     # 세션/루트 영속화 백엔드
├── sandbox/       # Git worktree 샌드박스
├── task/          # 태스크 모델 및 수명주기
├── trajectory/    # 궤적 영속화
├── workspace/     # 워크스페이스 헬퍼
├── config/        # 타입 지정 설정 및 TOML 로딩
├── scheduler/     # 예약 작업 지원
├── cli/           # sprout 명령줄
└── mcp/           # MCP 서버, 클라이언트, 어댑터

web/
├── frontend/      # Vite + React 웹 콘솔
│   ├── src/components/
│   ├── src/views/
│   └── src/
└── webapi/        # Starlette HTTP/WebSocket 애플리케이션, 라우트, 데이터베이스

assets/            # 공유 로고 및 정적 자산
~/.sprout/docker/  # 6개 데이터베이스 스택: compose 파일, 러너 이미지, 부트스트랩
```

## 요구사항 전략

`src/Sprout/strategy/`는 프로젝트 스캔 제안이나 사용자의 직접 요청을 검토 가능한 구현 계획으로 전환합니다. 그 `StrategyPipeline`은 계획 단계에서 읽기 전용이며, 코드가 변경되기 전에 필요한 근거를 생성합니다.

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

영향 분석은 두 가지 근거 출처를 사용합니다:

- **데이터베이스 근거**: database broker를 통한 읽기 전용 접근으로 스키마, 테이블, 마이그레이션, 영속화된 레코드, 기존 인터페이스나 태스크 이력을 확인합니다.
- **프로젝트 근거**: 전체 워크스페이스 스캔으로 소스 파일, 인터페이스, 데이터베이스 관련 코드, 테스트 파일을 찾고, 가능하면 워크스페이스 그래프 관계도 포함합니다.
- **교차 검증**: 두 출처를 비교하여 일치 항목, 데이터베이스 전용, 코드 전용, 미해결 충돌을 표시합니다. 충돌은 조용히 편집 권한으로 취급되지 않고 사람의 검토를 위해 표면화됩니다.

전략 계층은 요구사항 수집, 영향 분석, 변경 모드 선택, 수용 기준, 테스트 파일 계획을 담당합니다. `workspace/`는 읽기 전용 프로젝트 근거를 제공하고, `runtime/changes.py`는 제안 승인과 공식 apply/rollback을 담당하며, `execution/`은 patch, database, process, Git 브로커를 담당합니다.

## 설치

```bash
git clone <repository-url>
cd SEAM_Sprout
uv sync --dev
```

기본 설정은 완전히 오프라인입니다: `echo` 모델 제공자, 로컬 SQLite 데이터베이스, 외부 MCP 클라이언트 없음.

`aiyallm` 모델 제공자를 사용하려면 해당 배포판을 설치합니다:

```bash
pip install aiyallm
```

### 6개 데이터베이스를 두 명령으로

runtime은 6개의 데이터베이스로 팬아웃합니다. 세 개는 단순 파일(SQLite, JSONL 증거 로그, blob 저장소)이라 설치가 전혀 필요 없고, 나머지 세 개(Redis, Milvus, Neo4j)는 컨테이너입니다. 수명주기는 두 명령으로 해결됩니다:

```powershell
sprout db init                    # 설정된 모든 lane 생성/초기화
sprout db status                  # lane별 healthy/failed 보고
sprout db backup <dir>            # SQLite 데이터베이스 백업
sprout db restore <dir>           # SQLite 데이터베이스 복원
```
```bash
sprout db init
sprout db status
```

`init`은 5개의 SQLite 스키마, JSONL 및 blob 디렉터리, 3개의 Milvus 컬렉션, Neo4j 제약 조건을 빌드합니다. 멱등적이며 어떤 행도 쓰지 않습니다. `test`는 일반 저장소 번들을 통해 세션 1개, 턴 2개, 메모리 팩트 1개, 과도하게 큰 컨텍스트 스냅샷을 쓴 다음 각 lane을 해당 lane의 클라이언트로 다시 읽습니다. 그래서 "6개 모두 정상"이 주장이 아니라 검증된 사실이 됩니다. `sprout db init`은 설정된 모든 lane을 초기화하고 `sprout db status`는 하나씩 확인합니다. Docker를 사용하면 `init`은 세 개의 서비스 이미지를 pull하고(차단된 Docker Hub에는 미러 폴백 있음), 러너 이미지를 빌드하고, lane을 시작하고 검증합니다.

포트, 설정, 세 가지 테스트 계층, Docker 없는 프로필, 문제 해결은 `~/.sprout/docker/README.md`를 참조하세요.

## 사용법

### Agent

Python API가 핵심 사용 표면입니다. runtime을 조립하고 `Message`를 보냅니다:

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

모든 진입점은 단일 조립 경로로 `create_runtime()`을 사용합니다.

### Web

웹 콘솔은 Vite로 빌드하는 컴포넌트 기반 React 애플리케이션입니다.

프런트엔드를 한 번 빌드합니다:

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

그런 다음 웹 콘솔을 시작합니다:

```bash
uv run sprout serve
```

`http://127.0.0.1:8000`을 엽니다. 웹 애플리케이션은 채팅, 태스크 보드, 태스크 관리, 설정을 제공합니다.

핫 리로드 프런트엔드 개발:

```bash
cd web/frontend
npm run dev
```

사용 가능한 HTTP 엔드포인트:

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

WebSocket 엔드포인트는 `ws://127.0.0.1:8000/ws/chat`입니다.

### CLI

```bash
uv run sprout --help
uv run sprout                     # 대화형 채팅
uv run sprout chat "hello"        # 일회성 메시지
uv run sprout info                # runtime 및 설정 스냅샷
uv run sprout project workspace <path>   # 로컬 워크스페이스 열기
uv run sprout remote workspace-list      # 원격 SEMA 서비스 조작
uv run sprout db init             # 설정된 모든 lane 초기화
uv run sprout db status           # healthy/failed 보고
uv run sprout db backup ./backup  # 로컬 데이터베이스 백업
uv run sprout mcp inspect         # MCP 정의 확인
uv run sprout evolution candidates  # 성장 계층: 파이프라인이 만든 후보
uv run sprout skills import ~/code/my-skills   # 로컬 디렉터리에서 스킬 가져오기
uv run sprout skills list         # 설치된 스킬 확인
uv run sprout skills index --rebuild   # 스냅샷 동기화, 레지스트리/디스크 불일치 보고
uv run sprout skills forget <name>     # 레지스트리 행 삭제, 파일은 유지
uv run sprout serve               # 웹 콘솔 및 API 시작
uv run sprout stop serve          # 웹 콘솔 중지
```

`skills import`는 디렉터리를 재귀적으로 탐색하며, `SKILL.md`를 포함한 폴더를 스킬 하나로, 단일 파일 `*.toml`을 개별 항목으로 취급합니다. 중첩 레이아웃(`skills/writing/docs/SKILL.md`)도 찾고, 벤더 디렉터리는 건너뜁니다. 각 스킬은 나머지 하위 시스템이 쓰는 것과 동일한 브로커를 통해 설치됩니다. 안전하지 않은 내용을 스캔한 뒤 정책 엔진이 결정합니다. 로컬 경로는 1차 소스이므로 승인이 필요 없습니다. 다만 스캐너의 치명적 발견 하한은 여전히 적용되며 승인으로 우회할 수 없습니다.

### 언어 전환

대화형 CLI는 재시작 없이 메뉴 언어를 전환할 수 있습니다:

```text
/language
/language ja
/language zh-Hant
```

지원 언어는 [`src/Sprout/cli/i18n_languages.md`](src/Sprout/cli/i18n_languages.md)에 나열되어 있습니다. 선택 사항은 `~/.sprout/settings.json`에 저장되고 다음 세션에서 재사용됩니다.

### Temporal

태스크 오케스트레이션, 큐, 스케줄, 진화 자동화, 웹 작업, 게이트웨이 작업은 Temporal에서 실행할 수 있습니다.

번들된 Compose 스택으로 로컬 Temporal 서버를 시작합니다:

```bash
docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d
```

Temporal CLI 설치 없이 연결 가능 여부를 확인합니다:

```bash
export TEMPORAL_HOST=127.0.0.1:7233
sprout orchestrator doctor
sprout orchestrator worker
```

`doctor`는 서버 도달 가능성, 서버 버전, 네임스페이스 존재 여부, 설정된 태스크 큐를 폴링 중인 워커 수를 보고합니다.

### MCP

stdio로 MCP 서버를 실행합니다:

```bash
uv run sprout mcp serve
# 또는
sprout-mcp
```

서버는 안전한 작업만 노출합니다: 메시지 보내기, 세션 만들기, 세션 기록 읽기, 스킬 나열, 지식 검색. 고위험 쓰기, 승인, 성장 게시는 MCP 표면 밖에 있습니다.

노출된 도구, 리소스, 프롬프트를 확인합니다:

```bash
uv run sprout mcp inspect
```

## 설정

사용자 설정은 `~/.sprout/sprout.toml`에 있습니다. 설정은 이 단일 파일에 유지하고 프로젝트 로컬에 중복 `sprout.toml`을 추가하지 마세요. `SPROUT_CONFIG`는 필요할 때 다른 명시적 경로를 가리킬 때만 사용합니다.

Project Runtime MCP 도구:

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

DeepSeek 또는 다른 제공자를 사용하려면 `~/.sprout/sprout.toml`을 편집합니다:

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
# Sprout runtime authority: conversation은 sqlite | jsonl | blobstore.
# Milvus/Neo4j/Redis는 언제나 재구축 가능한 파생 계층입니다.
core = "sqlite:////<home>/.sprout/data/sprout_core.db"
conversation = "sqlite:////<home>/.sprout/data/sprout_conversation.db"
knowledge = "sqlite:////<home>/.sprout/data/sprout_knowledge.db"
audit = "sqlite:////<home>/.sprout/data/sprout_audit.db"
usage = "sqlite:////<home>/.sprout/data/sprout_usage.db"

[evolution]
approval_required = true
```

비밀 값은 환경 변수에서 읽으며 설정 파일에는 절대 기록되지 않습니다.

## 개발

```bash
uv run pytest
uv run ruff check .
```

개발 워크플로와 CLI/MCP 노출 규칙은 [guidance.md](guidance.md)를 참조하세요.

## 기여자

SEAM Sprout에 기여해 주신 모든 분께 감사드립니다:

| 기여자 | GitHub |
|---|---|
| JasonXuanxuan | [@JasonXuanxuan](https://github.com/JasonXuanxuan) |
| rest8945 | [@rest8945](https://github.com/rest8945) |
| siyuuuu1014-cell | [@siyuuuu1014-cell](https://github.com/siyuuuu1014-cell) |

## 라이선스

이 프로젝트는 [MIT License](LICENSE)로 제공됩니다.

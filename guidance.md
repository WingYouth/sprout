# SEAM Sprout Development Guidance

This document describes the development workflow for contributors, and doubles
as a condensed map of the repository structure, code logic, and local-only
design docs. The main README files (`README.md` and `README_CN.md`) describe
what the project is and how to run it; this file describes how to change it
safely and where to look before you do.

## 1. Core Principles

- Keep the runtime, storage, and evolution boundaries described in the README
  architecture section.
- Add domain logic in the package that owns it. Do not force unrelated
  transport or storage concerns into `src/Sprout/runtime/`.
- Entry points (`CLI`, `MCP`, `Web`) stay thin. They call runtime and public
  services; they do not open databases directly.
- Prefer existing contracts and implementations before creating a new
  abstraction.
- Session persistence belongs to `rootstock/` (the Rootstock/砧木 layer). The
  session module, context builder, and runtime depend on the `SessionStore`
  protocol, never on a concrete database.
- Every externally visible operation needs documentation and, where practical,
  a test.
- Every completed feature that produces observable runtime state must register
  its events in `src/Sprout/events/types.py` and, when it introduces a new
  authority/lane boundary, update `EVENT_LANES` so the event routes to the
  owning layer.

## 2. Development Workflow

1. **Understand the current shape.**
   Read `README.md`, this guidance file, and the relevant package under
   `src/Sprout/` before changing behavior. Section 7 gives the one-page map.

2. **Place the feature in the right module.**
   For example, storage behavior belongs in `storage/`, agent behavior in
   `agent/`, and transport concerns in `gateway/`, `mcp/`, `web/`, or `cli/`.
   Before adding persistence, read section 20 of this document and the
   machine-readable storage topology to see which Layer database owns the
   entity: exactly one is the authority, everything else is a rebuildable
   index, cache, or evidence log. Do not add a second authority for data that
   already has one.

3. **Implement the core capability.**
   Define or update protocols/models in the owning package. Keep the core free
   of entry-point imports such as `Sprout.cli` and `web.webapi`.

4. **Persist only what the feature owns.**
   If a feature needs persistence, add a contract under `storage/contracts/`
   and implementations under `storage/local/`. Update `StorageBundle`,
   `create_storage()`, and `storage_status()` so the feature participates in
   normal storage lifecycle and inspection. Sessions are the exception: their
   backends live in `rootstock/backends/` behind `[storage] session`, and a new
   backend slot is added there (plus `BACKENDS`, `create_session_store()`, and
   a round-trip test) rather than in `storage/`.

   A backend that is reserved but not wired must still parse its DSN and fail
   with an actionable error (`RootstockUnavailableError`: which package to
   install, what the planned mapping is).

   **Register its events before calling the feature complete.** Any new
   observable state change (message, agent, tool, approval, skill, evolution,
   security decision) needs a canonical event name and an entry in
   `EVENT_LANES`. The default fallback lane is `audit`; do not rely on it for
   events that belong to `conversation`, `usage`, `knowledge`, or `evolution`.

5. **Add tests.**
   Prefer focused unit tests for pure logic and integration tests where the
   feature crosses module boundaries. Run them with `uv run pytest`.

6. **Expose the feature through the CLI.**
   Add a command or subcommand under `src/Sprout/cli/commands/`, register it in
   `src/Sprout/cli/app.py`, and follow the CLI presentation rules below.

7. **Expose the feature through MCP when it is safe and useful.**
   Add the tool, resource, or prompt to the MCP server definitions. Respect the
   MCP exposure rules below.

8. **Update documentation.**
   Update `README.md`, `README_CN.md`, and this guidance file when the feature
   changes the public surface, configuration, workflow, or development rules.

9. **Run the full verification loop.**
   ```powershell
   uv run ruff check .
   uv run pytest
   uv run sprout --help
   uv run sprout mcp inspect
   ```

## 3. CLI Exposure Rules

Every new or changed operational feature should be reachable through `sprout`.

### Where to add code

- One command per feature or feature group under `src/Sprout/cli/commands/`.
- Register root commands in `src/Sprout/cli/app.py`.
- For nested functionality, create a sub-`typer.Typer` in the relevant command
  module and attach it with `app.add_typer(...)`.

### Presentation rules

- Use the shared `Sprout.cli.ui` helpers instead of writing raw `typer.echo`
  for labels, headings, success, warning, and error output.
- Keep the primary output purple, with success/warning/error colors reserved for
  status, not decoration.
- Add a useful docstring and option help text. Include examples in an `epilog`
  when the command has more than one obvious invocation.
- Provide a `--json` option for commands whose output is likely to be consumed
  by scripts.
- Do not make interactive commands require interactive input by default when a
  one-shot argument can express the same operation.

### Required help quality

`sprout --help`, `sprout <command> --help`, and `sprout <group> --help` should
answer:

- what the command does;
- which options are required and which are optional;
- what side effects it has;
- how to run the common path.

### i18n and language switching

CLI user-facing strings are routed through `Sprout.cli.i18n`. Static strings
are stored as translation pairs and rendered in the active language; dynamic
strings fall back to English when no translation is registered. Supported
languages and the runtime switch command are documented in
`src/Sprout/cli/i18n_languages.md`.

- Use `Sprout.cli.i18n.L(zh, en)` for new CLI labels.
- Register additional languages with `add_translations()` instead of adding a
  new ad hoc `if` branch in a command.
- Keep model replies untouched: i18n applies to menus, prompts, and status
  text, not generated answers.
- Persist the selection through `Sprout.cli.i18n.set_language()`.

## 4. MCP Exposure Rules

MCP is a public surface for model clients. Add a capability there only when it
is safe to expose and useful for a model-driven workflow.

### Safe surface

The MCP server should expose read-only and low-risk operations such as:

- sending a message and reading a reply;
- creating a session or reading session history;
- listing skills;
- searching knowledge.

### Do not expose through MCP

High-risk or privileged operations remain in the CLI/Web entry points:

- database writes and schema/reservation commands;
- approval decisions;
- evolution publishing/rollback;
- arbitrary filesystem writes;
- secrets or raw configuration material.

### Adding a tool, resource, or prompt

1. Implement the underlying behavior in the owning package.
2. Add the definition to the MCP server surface in `src/Sprout/mcp/server/`.
3. Keep names stable and descriptions specific.
4. Validate and normalize inputs at the MCP boundary.
5. Add the new capability to `sprout mcp inspect` output if that is automatic;
   otherwise update the inspect command to include it.
6. Add a test for the exposed definition and any input validation.

## 5. Definition of Done

A feature is complete when all applicable items are true:

- Core behavior is implemented in the correct module with focused tests.
- Every observable state change introduced by the feature is registered in
  `src/Sprout/events/types.py` and routed in `EVENT_LANES`.
- Persistent data participates in the storage bundle and lifecycle.
- The feature is reachable through an appropriate `sprout` command with clear
  help text, purple-styled output, and a scriptable mode where useful.
- The feature is available through MCP if it belongs on the safe public surface,
  or is intentionally excluded because it is high-risk.
- README and this guidance document reflect the new workflow and public
  commands.
- `uv run ruff check .` and `uv run pytest` pass.

## 6. Worked Example: Adding a New Read-Only Inspection Command

Suppose the project adds an inspection command named `summary`.

1. Add the domain query to the package that owns the data.
2. Add `src/Sprout/cli/commands/summary.py` with:
   - a docstring explaining the command;
   - `--config` and `--json` options where appropriate;
   - `Sprout.cli.ui` output helpers.
3. Register it in `src/Sprout/cli/app.py` with `app.command()(summary.summary)`.
4. If the information is safe for model clients, add a read-only MCP tool or
   resource that returns the same summary.
5. Update both README files and run the verification loop.

For a new state-changing operation, the same steps apply, but do not add it to
the MCP server surface. Keep state changes in the CLI/Web entry points where
approval, auditing, and operator control already exist.

---

# Part II · Repository Structure and Code Logic (Condensed)

> One-page map of the repository and its runtime logic. The full deep-dive
> lives in the local doc `ARCHITECTURE.md` (not committed).

## 7. Layering and Dependency Direction

Dependencies flow strictly downward; reverse imports are forbidden.

```
entry       cli/ · mcp/server/ · mcp/client/ · web/webapi/ · gateway/
assembly    runtime/factory.py::create_runtime  -- the single init path
core        runtime/runtime.py (coordinator)
              ├── runtime/nodes.py        node execution branches
              ├── runtime/changes.py       change-proposal state machine
              ├── runtime/workspaces.py    workspace registry/scan/read plans
              └── orchestration/           graph compile + local/Temporal terminal + worker + workflows
capability  agent/ · context/ · tools/ · skills/ · llm/ · registry/
boundary    security/ (policy + approval) · execution/ (6 brokers) · workspace/ (read edge)
storage     storage/ (StorageBundle, 8 slots) · rootstock/ (session layer, 7 lazy backends)
growth      evolution/ (single trajectory-driven pipeline, HardGate)
```

- `runtime/` never imports `Sprout.evolution` or `Sprout.mcp`; entry points
  attach them inside the event loop (`attach_evolution`, `attach_mcp_clients`).
- The coupling hotspots are the domain models (`workspace/message/session/task
  .models`); `runtime.runtime` is the only implementation-level hub.
- `rootstock` backends must stay lazily imported, otherwise they deadlock with
  `Sprout.storage.bundle` at assembly time.

## 8. Key Packages at a Glance

| Package | Responsibility | Key files |
|---|---|---|
| `security/` | Access decisions + approvals | `access.py` (14 ActionType × 5 AccessDecision), `engine.py` (default matrix), `layered_policy.py` (layered intersection, monotonically tightening), `approval.py` (fingerprint / task scope / single-use / TTL), `secrets.py` + `secret_broker.py` (env-only + redaction) |
| `execution/` | The only path to real I/O | 6 brokers (file/process/apply/git/network/database); shared pattern: build `ActionRequest` → ask policy → return a "denied result object" instead of raising |
| `workspace/` | Read edge + resource models | `read_broker.py` (rejects `..`/symlink, 20 KB cap), `models.py` (ResourceRef + 9 ResourceKinds) |
| `rootstock/` | Session layer (the "stock" Sprout grafts onto) | `SessionStore` protocol (6 methods) + 7 backends behind `[storage] session` |
| `gateway/` | Identity and task admission | `identity.py::Principal`, delegation/task/runtime gateways |
| `evolution/` | Growth layer | Trajectory → Signals → Replay → HardGate → Utility → Publish; HardGate blocks self-escalation and security-boundary weakening |

## 9. The Two Core Paths

**Online turn — `Runtime.handle`**: publish `message.received` → middleware →
`SessionManager.resolve` (the authority is `sprout_conversation.db` through the
conversation/session contract) → `AgentRouter.route` → `ContextBuilder`
(memory = recent turns, Sprout runtime knowledge, tools, skills) → `AgentLoop`
(default max 8 steps) → persist the full message envelope through
`sprout_conversation.Message`; oversized bodies offload to the matching
blobstore and leave a `content_blob_uri` → publish `message.persisted` (message
ids + seqs) → `message.sent`. Bus events land in Sprout runtime evidence/audit
lanes, fail-open where they are derived observations.

**Project task — `Runtime.execute`**: compile the 6-node graph
`READ → SANDBOX → AGENT / EVALUATION → APPROVAL → APPLY`; the
Temporal runs the compiled graph with deterministic node ordering and durable
retries. APPROVAL returns `waiting=True` and suspends the task;
`resume_task` restores node state via `_restore`, so an approval decision never
replays side effects. Change proposals flow
`PENDING → APPROVED → APPLIED → ROLLED_BACK / REJECTED`; only APPROVED changes
reach disk, via `ApplyBroker` (`git apply`).

**Temporal terminal**: `Runtime` always delegates the execution graph to
`TemporalOrchestratorBackend`; `TEMPORAL_HOST` only overrides the default local
endpoint. A separate
`sprout orchestrator worker` process hosts the workflows and activities.
`run_sprout_node` activity goes through the public `Runtime.execute_node`
method, so external schedulers never touch Runtime private fields. Start the
server with `docker compose -f ~/.sprout/docker/temporal/docker-compose.yml up -d` and
validate with `sprout orchestrator doctor` before starting the worker.

## 10. Storage Split: Two Layers, Authority vs Derived

Every entity has exactly one authority store; callers go through
`storage/contracts` protocols, never connections. The write path is single
(synchronous to the authority) while the read path may fan out
(cache -> vector/FTS -> graph -> authority fallback).

Sprout now uses two different database layers. They are physically separate and
their schemas are intentionally different:

- **Sprout runtime layer**: records how this Sprout runtime operates: sessions,
  tasks, runs, approvals, tool calls, cost, audit, runtime knowledge, and runtime
  evidence.
- **User project ontology layer**: records what the user's project is: backend,
  frontend, agent, skill, infrastructure components; code structure; interfaces;
  database schemas and split plans; project versions and evolution.

`sprout_*` databases must never become a second authority for user project
structure. They may hold only bridge references (`target_ref_id`, `project_id`,
`ref_type`, `ref_id`) to records owned by `project_*` databases.

| Layer | Authority stores | Purpose |
|---|---|---|
| Sprout runtime | `sprout_core.db`, `sprout_conversation.db`, `sprout_knowledge.db`, `sprout_audit.db`, `sprout_usage.db` | Runtime control, conversations, runtime knowledge, approvals, audit, cost/performance |
| User project ontology | `projects/{project_id}/project_manifest.db`, `project_structure.db`, `project_architecture.db`, `project_database.db`, `project_evolution.db` | User project identity, components, source structure, interfaces, database schemas, decomposition, version evolution |
| Evidence | `sprout_trajectory/*.jsonl`, `sprout_blobs/`, `projects/{project_id}/trajectory/*.jsonl`, `projects/{project_id}/blobs/` | Append-only traces and large objects; replay/evidence layer, not relational authority |
| Derived hot path | Redis namespaces `sprout:*`, `project:{id}:*` | Cache, locks, queues, run status, context blocks; always rebuildable |
| Derived vectors | Milvus `sprout_vec_*`, `project_{id}_vec_*` | Semantic search over authority text/blob content; always rebuildable |
| Graph backbone | Neo4j Sprout labels + UserProject labels | Cross-domain relationships, dependency paths, impact paths, version paths; graph backbone, not a blob projection |

---

# Part III · Local Docs Map and Development Baselines

The repository ships source only. The following generated design/planning docs
are local reading material — see `.gitignore`:

| Doc | One-line summary |
|---|---|
| `ARCHITECTURE.md` | Full architecture deep-dive: measured import graph, fan-in/out, the 6-node pipeline, risk list (the most detailed single doc) |
| `AUTHZ_DESIGN.md` | AuthZ design: unified policy engine + hard floor, actor authentication and scoping, resource classification over write/delete, secret provider + unified redaction, approval merge + decision entry points, tiered sandbox + SSRF guard, hash-chained audit (with a Hermes cross-reference table) |
| `GATEWAY_DESIGN.md` | Gateway admission-layer design (committed to the repo) |
| `src/Sprout/rootstock/DESIGN.md` | Session-layer six-backend design |
| §21 of this document | Skills subsystem: discovery, trust, delivery (absorbed the former `docs/SKILLS_SYSTEM_DESIGN.md`) |

There is one external baseline that is not a repo file: the
**Herness Runtime V1.0 master spec**
(`Herness_Runtime_V1.0_总体技术架构方案.docx`, in Downloads). Extract its
text with a zipfile + regex over `word/document.xml` (script:
`.workbuddy/docx_extract.py`); do not install python-docx for this.

Also local-only: `tests/` (kept out of the remote by convention), `.workbuddy/`
(session scratch), and root-level `*.txt` (tooling logs).

## 11. Development Baselines: Which Doc Drove Which Part of the Project

The authoritative answer to "what was each part of the current codebase
developed against". Status is as of 2026-09-18.

| Project area (code) | Development baseline | Status |
|---|---|---|
| Security layer: `ReadBroker` boundary checks, `ApprovalManager` (one-time / task-scoped / TTL), `ResourceKind` PUBLIC/SENSITIVE/EXTERNAL, `HardGateEvaluator` | Herness V1.0 master spec (§11.5, §21.2, §16.4) | Implemented (`5f77b27`); AUTHZ_DESIGN.md is the **next** baseline for this area (see §12) |
| Session layer: `rootstock/` (contract + 7 backends, lazy imports) | `src/Sprout/rootstock/DESIGN.md` | Implemented (`bdb0114`) |
| Runtime decomposition: `runtime/nodes.py`, `changes.py`, `workspaces.py`; `runtime.py` 890 → 485 lines | `ARCHITECTURE.md` risk list (items 2, 5, 7) | Implemented (`3eeb364`) |
| Evolution single-track pipeline (old track archived to `.workbuddy/legacy/`) | Herness V1.0 §16 + `ARCHITECTURE.md` §8 | Implemented (`9290608`, `30e8121`) |
| Gateway admission (`gateway/`, feishu/rpc routing, SEMA rename) | `GATEWAY_DESIGN.md` | Implemented by the owner (`597b226`) |
| AuthZ: actor authentication, policy unification, approval decision entry points, sandbox tiers, audit chain | `AUTHZ_DESIGN.md` (§12 below) | **Not yet implemented** — A0–A5 roadmap pending |
| Skills: loader/index/matcher/resolver/broker/crawler, trust gate, progressive disclosure, agent tools | §21 of this document (the standalone `docs/SKILLS_SYSTEM_DESIGN.md` was folded in and deleted) | Implemented |

Rule of thumb for new work: **pick the owning row's doc as the baseline**,
check its status column, and do not re-open decisions a doc has already made
without updating that doc first.

## 12. AUTHZ_DESIGN: Key Points (A0-A5 landed; see section 20)

> Status note: the roadmap below was executed, so read it as *what was
> agreed*, not as *what is still missing*. The permissions rules that bind
> code review today are in section 20.

Condensed from `AUTHZ_DESIGN.md`; read the full doc before touching
`security/`, `gateway/identity.py`, or any Broker.

**Three most critical gaps found in current code:**

1. `principal_from_message` reads `roles` from message metadata — callers can
   self-assign roles and escalate. Fix: roles come only from entry-point
   adapters (CLI = OS user, Web = session token, MCP = declared principal).
2. `known_command=True` lives in `ActionRequest.arguments` — the model can
   self-attest "known command" and bypass approval. Fix: server-side command
   allowlist in `[security.commands]`, set by the Broker, never by arguments.
3. Approvals have **no decision entry point**: neither Web nor CLI exposes
   approve/reject, so tasks hang in WAITING_APPROVAL forever.

**Design in one line per module:**

- **Policy engine**: one shared Protocol for `PolicyEngine` /
  `LayeredPolicyEngine` / `SecurityPolicy`; add a hard floor
  (`security/floor.py`) no config can relax (rm -rf /, fork bombs, `| sh`
  from untrusted URLs, `secret.read`); rules gain actor_role / resource_kind /
  argument_guards and fnmatch globs; decisions carry `matched_rules` for
  provenance.
- **Actor scope**: `DelegationScope` gains expiry + max_depth + issued_by;
  subagents intersect (never widen) the parent scope; `system` principal is
  separated from user principals in audit.
- **Resource classification**: explicit classifier table (glob → ResourceKind)
  applied to write/delete too — SECRET/EXTERNAL are never writable, SENSITIVE
  writes require approval (today `file.write` is blanket `SANDBOX_ONLY`).
- **Secrets**: `SecretProvider` protocol (env-only today); one unified
  redactor (known values, then `sk-`/`ghp_`/Bearer/`token=` patterns, then
  zero-width Unicode rejection); subprocesses get an env whitelist
  (PATH/HOME/… plus explicitly injected secrets), never full inheritance.
- **Approvals**: merge the in-memory `ApprovalTicketManager` into the
  persisted `ApprovalRecord`; add `POST /api/approvals/{id}/decide` and
  `sprout approvals list/approve/reject/suggest`; cron/unattended tasks deny
  by default (Hermes `cron_mode: deny`).
- **Sandbox**: worktree = logical boundary only (documented as such);
  `sandbox.mode=container` as P2 with hardened Docker flags
  (cap-drop ALL, no-new-privileges, pids-limit); `net_guard` blocks
  RFC1918/loopback/link-local (SSRF + cloud-metadata protection).
- **Audit**: `~/.sprout/data/audit/security.jsonl` for every policy decision with a
  hash chain (`sprout audit verify`); audit-write failure is **not**
  swallowed (unlike today's `RequestAuditMiddleware`).

**Roadmap:** A0 (security stopgaps: roles, known_command, env whitelist) →
A1 (floor + protocol unification) → A2 (approval merge + decision entry) →
A3 (classifier + redactor) → A4 (audit chain) → A5 (net_guard + container).

---

# Part IV · Project Conventions and Operational Rules

These are the rules a fresh session needs to know before touching code on
this project. They are derived from recurring failures logged in daily memory
and have cost real time — assume each one was earned.

## 13. Hard Conventions for This Project

**Pre-commit gates — both must be green:**

```powershell
uv run pytest src/Sprout/tests web/tests
uv run ruff check src web
```

**Architectural invariants (do not break):**

- `src/Sprout/runtime/` must **not** import `Sprout.evolution` or `Sprout.mcp`;
  those are attached in the event loop by `attach_evolution` /
  `attach_mcp_clients`. `runtime/factory.py::create_runtime` is the only init
  path.
- `rootstock` backends must stay **lazily** imported. Top-level imports in
  `rootstock/__init__.py` deadlock with `Sprout.storage.bundle`. Use the
  module-level `__getattr__` pattern.
- `config/loader.py` raises on unknown config keys. Before deleting a
  settings field, grep for every read site and confirm no external
  `sprout.toml` references it (the only in-repo source is
  `config/defaults.py`).
- `ApprovalRecord` is bound by four hard rules: sha256 fingerprint, task
  scope, `single_use=True` by default, TTL. New callers must pass `task_id`
  and never let one task inherit another task's grant.
- Broker pattern is non-negotiable: build `ActionRequest` → call `decide` →
  if not `ALLOW`, return a denied result object (do not raise).

**Tool and environment quirks (Windows + PowerShell 5.1):**

- `Edit` silently drops writes occasionally (file-lock / AV scan).
  **Read back every key edit** to confirm it landed.
- `Remove-Item` is intercepted by a safe-delete hook that fails closed.
  Archive with `Move-Item` into `<project>/.workbuddy/legacy/` instead.
- PowerShell swallows native stdout for long-running commands. Pipe into
  `Out-File -Encoding utf8` and read back via the `Read` tool.
- For Chinese output from native Python, set
  `[Console]::OutputEncoding = [Text.UTF8Encoding]::new()` first.
- JSON CLI args (`--json-file` etc.) on Windows need double-backslashed
  paths or single backslashes are parsed as escapes.

**Editing style for the codebase:**

- Code, docstrings, comments, commit messages: **English**.
- Conversation, design docs, log entries: **Chinese** (matches R/A memory).
- Finance / chart UI: 涨红跌绿 (red up, green down), currency ¥ — opposite
  of US/European convention, do not "fix" it.
- `tests/` stays local-only by convention (`.gitignore`, not tracked on
  `origin/main`); use `git add -f` only if you really need to push a test.

## 14. Git Push Rules and `.git` Recovery

**Local checkout is `main`**, but `main` is not the public branch. Always push
via:

```powershell
git push origin main:dev       # never `git push origin main`
```

**Before every push, check divergence:**

```powershell
git ls-remote origin           # confirm remote dev SHA
git fetch origin "+refs/heads/dev:refs/remotes/origin/dev"
# merge if remote dev is not in local main, no force push
```

**HTTPS TLS disconnect (`curl 56 OpenSSL SSL_read: unexpected eof` /
`send-pack: unexpected disconnect`):** blind retry does not help. Set
`http.version = HTTP/1.1` (and optionally `http.postBuffer 524288000`)
once, then retry:

```powershell
git config http.version HTTP/1.1
```

**`origin/dev` remote-tracking ref is unreliable** on this machine — it
disappears after `fetch`. When you need it, use the explicit SHA from
`git ls-remote origin dev` (use `git show <sha>` or `git diff <sha>` rather
than relying on the `origin/dev` name).

**`.git` corruption has happened at least twice** (refs deleted, pack data
lost, only reflog + remote survive). Likely external process (AV / sync /
indexer) scanning `.git/`. After any long `git` op is killed or interrupted:

```powershell
git fsck       # if it passes, only refs are missing, not objects
```

Recovery recipe when refs are gone:

1. Archive bad pack idx / index to `.workbuddy/legacy/git_recovery_<date>/`.
2. Read the last SHA of each branch from `logs/refs/heads/<branch>` (the
   second whitespace-separated field on the last line).
3. `git fetch origin "+refs/heads/*:refs/remotes/origin/*"` to rebuild the
   object library (works only if history is fully on the remote).
4. Write refs files directly + `git reset --mixed origin/dev` to rebuild
   the index (delete the old index if its cache-tree references bad objects).
5. Never use `git init -b main` + force checkout as a recovery step — it
   overwrites working-tree uncommitted changes. First `cp -r` the whole
   working tree to a backup location outside `.git/`.

## 15. Testing Conventions

**`conftest.py` defaults to `in_memory()`** for SQLite. That means WAL,
busy_timeout, file-lock contention, migration, and corruption recovery have
**zero coverage** when the test suite is green. Do not claim "passes" on
`memory://` alone; every storage-touching change needs at least one
file-backed SQLite test.

**Required fault-injection tests** (none are written today; add them as
you change the relevant code):

1. Two processes writing the same session simultaneously — no
   `database is locked`.
2. Two processes initializing the schema at the same time — no lock
   collision.
3. WAL unavailable (e.g. NFS) → falls back to DELETE with a warning, not
   silent stall.
4. Old schema upgraded; data still readable.
5. Compact / write race on `covered_through` stays consistent.

**Security regression test patterns** (use these as templates):

- Actor / role forgery (sending `roles=["admin"]` in message metadata).
- Path escape via `..` and symlink through `ReadBroker`.
- `DelegationScope` expiry crossing.
- Zero-width Unicode injection into memory / trajectory / redactor input.
- Approval fingerprint match with mismatched task_id → must deny.
- Audit hash chain break detection (mutate one line, expect `verify` to fail).

**Smoke coverage** lives at `.workbuddy/smoke_test.py` (38 cases). It
covers driver WAL, session+seq, FTS5 EN+CJK, memory add/replace/remove,
scanner, blob, cascade delete, backup, the 7 reserved SQLite backends, the
4 reserved (milvus/neo4j/redis/sonic) backend errors, and the
composer+budget+estimator+snapshot trio. Re-run it after any
`storage/`/`memory/` change.

## 16. Sandbox Lifecycle Closure Rules

Project tasks create Git worktrees under `<workspace.root.parent>/.sprout-*`.
Those worktrees are execution artifacts, not repository source. Every sandbox
must be removed at a deterministic terminal point, with a startup reaper as
the crash-recovery backstop.

Rules:

- Keep a sandbox while its task is `running` or `waiting_approval`.
- Remove the sandbox when the task reaches `completed`, `failed`, or
  `cancelled`.
- `completed` cleanup applies even when a proposal has no diff.
- Cleanup must remove both the worktree and the `sprout-sandbox-*` branch.
- Cleanup must be idempotent and must never touch paths outside
  `workspace.root.parent/.sprout-*`.
- On startup, reconcile all `workspace.root.parent/.sprout-*` worktrees against
  active proposal sandbox references and remove unreferenced orphans.
- New sandbox lifecycle logic belongs in `src/Sprout/sandbox/`, assembled by
  `Runtime`, and must not import CLI, web, MCP, or evolution code.

The external design baseline for this area is
`D:\SEMA_Sandbox_Auto_Cleanup_Plan.md`.

## 17. Gateway Channel Routing Rules

Gateway channels adapt external messaging surfaces to SEMA. The active
WeChat iLink channel is a personal-WeChat Bot API integration:

```text
QR login -> getupdates long poll -> route inbound text -> reply
```

Routing rules:

- Ordinary private text uses the online conversation path
  (`Runtime.handle`) and must not create a project task or sandbox.
- Explicit task messages use the project path (`Runtime.execute`) and keep
  approval gating. Recognized prefixes are `/task`, `/project`, `/任务`, and
  `/项目`.
- `/task` replies immediately with the created task id, then executes the
  project task in the background.
- When the task reaches `waiting_approval`, the gateway polls proposal state;
  approval triggers `resume_task`, rejection stops the background flow, and
  the final result is sent back through iLink.
- Per-peer iLink state persists `context_token`, `session_id`,
  `last_task_id`, and `sync_buf`. Legacy `context_tokens` files are migrated
  into the current state store.
- Conversation messages do not grant file-write permissions. Project task
  messages use `DelegationScope` exactly like other external task gateways.

Approval decisions remain in CLI/Web and must not be exposed through MCP.

## 18. Workspace Intelligence Rules

Workspace Intelligence combines manifest discovery, read planning, graph
construction, and project knowledge extraction.

Rules:

- `WorkspaceScanner` owns manifest discovery and ReadPlan construction.
- `WorkspaceIntelligence.analyze()` is the single composition entry point; it
  returns a `WorkspaceAnalysis` containing manifest, ReadPlan, graph, and
  project knowledge.
- `WorkspaceGraphBuilder` must produce deterministic node and edge ids and
  attach evidence to generated edges.
- Python import edges are built by parsing source ASTs; analyzers must not
  execute project code.
- User project facts must carry evidence ids and confidence. Project identity,
  code structure, interfaces, database structures, and evolution are persisted
  through the `project_manifest`, `project_structure`, `project_architecture`,
  `project_database`, and `project_evolution` authorities, not through
  `sprout_knowledge.db`.
- New graph or analyzer logic belongs under `src/Sprout/workspace/` and must
  not import CLI, MCP, or web entry points.

## 19. Database Architecture Rules: Sprout Layer + User Project Layer

This section is the code-review baseline for storage design. If implementation
details conflict with this section, update the implementation or update this
section in the same change.

### 19.1 Two physical database sets

There are two physical database sets:

- `sprout_*`: Sprout's own runtime state.
- `projects/{project_id}/project_*`: the user's project ontology and evolution.

They are not replicas of each other and must not share table schemas. Sprout
runtime records may point to user project records only through stable bridge
references:

```text
TargetRef(
  id,
  target_layer,        -- sprout | project
  project_id?,
  ref_type,            -- Project | Component | File | Symbol | Table | Interface
  ref_id,
  display_name,
  last_seen_version_id?,
  metadata_json
)
```

### 19.2 Sprout runtime authorities

`sprout_core.db` is the authority for runtime coordination:

- `RuntimeWorkspace(id, root_path, sprout_version, config_hash, active_profile,
  status, data_root, metadata_json, created_at, updated_at)`
- `TargetRef(id, target_layer, project_id, ref_type, ref_id, display_name,
  last_seen_version_id, metadata_json)`
- `Task(id, workspace_id, target_ref_id, parent_task_id, title, instruction,
  source, status, priority, task_type, actor_json, delegation_scope_json,
  budget_json, context_snapshot_id, result_summary, error_summary,
  metadata_json, created_at, updated_at, completed_at)`
- `ExecutionRun(id, task_id, agent_name, model, status, sandbox_id, started_at,
  ended_at, result_json, error, trace_jsonl_uri, metadata_json)`
- `ExecutionStep(id, run_id, seq, kind, status, input_json, output_json,
  tool_calls_json, started_at, ended_at, duration_ms, metadata_json)`
- `ChangeSet(id, task_id, run_id, target_ref_id, sandbox_id, status, risk,
  summary, rollback_plan, project_evolution_change_set_id, created_at,
  updated_at)`
- `FileChange(id, change_set_id, path, change_type, old_hash, new_hash,
  diff_blob_uri, created_at)`
- `Validation(id, task_id, change_set_id, command, status, exit_code,
  output_blob_uri, duration_ms, created_at)`
- `Artifact(id, task_id, run_id, target_ref_id, kind, name, version, status,
  content_blob_uri, content_hash, metadata_json, created_at, updated_at)`

`sprout_conversation.db` is the authority for user-to-Sprout control
conversation:

- `Session(id, user_id, channel, target_ref_id, title, status, locale, summary,
  metadata_json, created_at, updated_at)`
- `Message(id, session_id, seq, role, content_type, content, content_blob_uri,
  line_count, token_estimate, language, metadata_json, created_at)`
- `Attachment(id, message_id, kind, filename, mime_type, blob_uri, size_bytes,
  content_hash, scan_status, metadata_json, created_at)`
- `MessageTaskLink(message_id, task_id, relation, confidence, created_at)`

For CLI pasted blocks over four lines, preserve the user's original content in
`Message.content` or `content_blob_uri`, set `content_type='folded_block'`, set
`line_count`, detect/store `language` where practical, and let the UI render it
as one purple folded unit. Do not alter model-generated message bodies for i18n;
i18n applies to UI labels, prompts, and status text.

`sprout_knowledge.db` is the authority for Sprout's own operating knowledge,
not user project code structure:

- `KnowledgeItem(id, scope, kind, title, content, content_blob_uri,
  evidence_json, status, version, confidence, created_at, updated_at)`
- `MemoryFact(id, scope, owner_id, key, value, confidence, source_json,
  expires_at, created_at, updated_at)`
- `CapabilityNote(id, capability_name, tool_name, risk_level, usage_pattern,
  constraints_json, examples_blob_uri, updated_at)`
- `KnowledgeEvidence(knowledge_id, source_type, source_id, weight,
  quote_blob_uri, created_at)`
- `KnowledgeLink(source_id, target_type, target_id, relation, weight,
  created_at)`
- `KnowledgeFTS(rowid, title, content, kind, scope)` as a rebuildable FTS index.

`sprout_audit.db` is the authority for platform approvals, security decisions,
HTTP request audit, and operation logs:

- `Approval(id, task_id, tool, arguments_fingerprint, status, requested_by,
  decided_by, reason, resource_scope, action_hash, single_use, created_at,
  decided_at, expires_at, used_at)`
- `SecurityEvent(id, ts, actor_id, action, resource, decision, risk, reason,
  metadata_json)`
- `WebRequest(id, ts, route, method, status_code, duration_ms, session_id,
  user_id, request_id)`
- `OperationLog(id, ts, actor_id, source, operation, target, payload_json)`

`sprout_usage.db` is the authority for model/tool cost and runtime performance:

- `ModelCall(id, ts, provider, model, session_id, task_id, run_id, step_id,
  input_tokens, output_tokens, total_tokens, latency_ms, cost_usd, request_id,
  metadata_json)`
- `ToolUsage(id, ts, task_id, run_id, step_id, tool_name, duration_ms, status,
  metadata_json)`

### 19.3 User project ontology authorities

`project_manifest.db` is the authority for project identity and components:

- `Project(id, name, display_name, root_path, repo_url, default_branch,
  product_type, owner, status, current_version_id, metadata_json, created_at,
  updated_at)`
- `ProjectComponent(id, project_id, name, component_type, root_path, runtime,
  framework, package_manifest_path, owner_team, lifecycle_status, metadata_json)`
- `RuntimeProfile(id, component_id, language, language_version, package_manager,
  install_command, build_command, test_command, start_command, env_schema_json,
  ports_json)`
- `EntryPoint(id, component_id, kind, path, symbol_id, route, command,
  is_primary, metadata_json)`
- `ExternalService(id, project_id, owner_component_id, name, service_type,
  endpoint, auth_type, config_ref, risk_level, metadata_json)`
- `ProjectTag(project_id, key, value, category, source, created_at)`

`component_type` must distinguish at least `backend`, `frontend`, `agent`,
`skill`, `infra`, and `docs`.

`project_structure.db` is the authority for scanned source structure:

- `WorktreeSnapshot(id, project_id, git_revision, branch, base_revision,
  scan_status, scanned_at, scanner_version, file_count, symbol_count,
  error_blob_uri)`
- `DirectoryNode(id, snapshot_id, parent_id, path, depth, role, component_id,
  metadata_json)`
- `FileNode(id, snapshot_id, component_id, directory_id, path, language,
  file_role, content_hash, size_bytes, lines, blob_uri)`
- `SymbolNode(id, file_id, parent_symbol_id, name, qualified_name, kind,
  signature, visibility, start_line, end_line, docstring_blob_uri,
  metadata_json)`
- `Dependency(id, component_id, source_file_id, name, version, dependency_type,
  scope, source, license, risk_json)`
- `CodeRelation(id, source_symbol_id, target_symbol_id, target_dependency_id,
  target_file_id, relation_type, confidence, evidence_span_json, created_at)`

Analyzers must parse source; they must not execute user project code.

`project_architecture.db` is the authority for modules, interfaces, contracts,
and component interactions:

- `ModuleBoundary(id, component_id, name, layer, responsibility, stability,
  owner, boundary_rules_json, created_at, updated_at)`
- `ModuleFileMap(module_id, file_id, role, confidence, source)`
- `InterfaceSurface(id, component_id, module_id, name, interface_type,
  visibility, lifecycle_status, description, source, created_at, updated_at)`
- `InterfaceEndpoint(id, interface_id, method, path_or_name, operation_id,
  auth_policy, rate_limit_policy, stability, deprecated_at, metadata_json)`
- `InterfaceSchema(id, endpoint_id, schema_kind, direction, content_type,
  schema_json, schema_blob_uri, schema_hash, example_blob_uri, created_at)`
- `InterfaceImplementation(id, endpoint_id, file_id, symbol_id,
  framework_binding, handler_kind, line_range_json, confidence,
  evidence_blob_uri)`
- `InterfaceCall(id, caller_component_id, caller_file_id, caller_symbol_id,
  target_endpoint_id, call_type, request_shape_hash, confidence,
  evidence_blob_uri, created_at)`
- `InterfaceVersion(id, interface_id, version, introduced_in_version_id,
  removed_in_version_id, schema_hash, breaking_change, changelog,
  migration_notes_blob_uri, created_at)`
- `DataFlow(id, source_component_id, target_component_id, interface_id,
  data_source_id, medium, payload_schema_id, direction, sync_mode,
  metadata_json)`
- `AgentContract(id, component_id, agent_name, role, interface_id,
  tool_surface_json, memory_policy_json, guardrail_json, model_policy_json,
  lifecycle_status)`
- `SkillContract(id, component_id, skill_name, trigger_scope, interface_id,
  inputs_json, outputs_json, dependencies_json, side_effects_json,
  lifecycle_status)`

Interface storage rule: never store only a display name. Store the surface,
endpoint, request/response schema, implementation symbol/file, callers, and
interface version. API, CLI, tool, agent, skill, GraphQL, RPC, and event
interfaces all use this model.

`project_database.db` is the authority for user project database structures,
database relationships, and decomposition:

- `DataSource(id, project_id, component_id, name, engine, authority_level,
  connection_ref, config_file_id, lifecycle_status, metadata_json)`
- `SchemaVersion(id, data_source_id, version, revision, project_version_id,
  ddl_hash, schema_blob_uri, migration_id, captured_at, captured_by)`
- `DatabaseTable(id, schema_version_id, name, table_type, domain,
  authority_role, owner_component_id, estimated_rows, retention_policy)`
- `DatabaseColumn(id, table_id, name, ordinal, data_type, nullable,
  default_value, is_primary_key, is_unique, is_indexed, pii_level,
  semantic_role, description)`
- `DatabaseRelation(id, source_table_id, source_column_id, target_table_id,
  target_column_id, relation_type, cardinality, constraint_name, confidence,
  evidence_blob_uri)`
- `DatabaseSplitPlan(id, project_id, source_data_source_id,
  target_topology_json, reason, strategy, status, owner_decision_id, risk_json,
  created_at, updated_at)`
- `SplitMapping(split_plan_id, source_table_id, target_data_source_id,
  target_table_name, ownership, migration_order, sync_strategy, notes)`
- `MigrationStep(id, schema_version_id, split_plan_id, step_order, operation,
  script_blob_uri, rollback_blob_uri, validation_query, expected_result_json,
  status)`
- `DataAccessPoint(id, table_id, column_id, file_id, symbol_id, access_type,
  query_fingerprint, query_blob_uri, confidence, created_at)`

Database split/decomposition is a user project fact. It belongs in
`project_database.db` and `project_evolution.db`, not in `sprout_core.db`.

`project_evolution.db` is the authority for project versions, decisions,
changes, impact, validation, and decomposition plans:

- `ProjectVersion(id, project_id, version_name, semantic_version, git_revision,
  snapshot_id, schema_version_set_json, interface_version_set_json,
  release_notes_blob_uri, created_at, created_by)`
- `ArchitectureDecision(id, project_id, version_id, title, decision_type,
  context, options_json, decision, consequences, status, created_at)`
- `EvolutionChangeSet(id, project_id, from_version_id, to_version_id,
  sprout_change_set_id, change_type, summary, rationale, diff_blob_uri, status,
  created_at)`
- `ChangeImpact(id, change_set_id, target_type, target_id, impact_level,
  reason, mitigation, confidence, evidence_blob_uri)`
- `ValidationResult(id, change_set_id, validator, validation_type, status,
  command, exit_code, output_blob_uri, duration_ms, created_at)`
- `DecompositionPlan(id, project_id, target_version_id, decomposition_type,
  plan_json, boundary_json, dependency_cut_json, status, owner_task_id,
  created_at, updated_at)`

### 19.4 JSONL and Blob rules

JSONL is append-only evidence:

- Sprout runtime traces live in `sprout_trajectory/{task_id}.jsonl`.
- User project scanning, analysis, decomposition, migration, and validation
  traces live in `projects/{project_id}/trajectory/{task_or_scan_id}.jsonl`.
- JSONL events include `event_id`, `layer`, `project_id?`, `task_id?`,
  `run_id?`, `name`, `occurred_at`, and `payload`.

Blob storage is content-addressed object storage:

- Sprout blobs live under `sprout_blobs/`.
- User project blobs live under `projects/{project_id}/blobs/`.
- Blob records include `layer`, `project_id?`, `uri`, `sha256`, `mime_type`,
  `size_bytes`, and `bytes`.
- Blob references include `layer`, `owner_table`, `owner_id`, `column_name`,
  `blob_uri`, and optional preview. Do not reuse `blob_uri` across layers.

### 19.5 Redis, Milvus, and Neo4j rules

Redis is derived and ephemeral:

- Sprout keys use `sprout:*` (`sprout:queue:tasks`,
  `sprout:lock:{resource}`, `sprout:run:{id}:status`,
  `sprout:context:{sid}`, `sprout:memory:block:{owner}`,
  `sprout:ws:progress:{run_id}`).
- User project keys use `project:{id}:*` (`project:{id}:queue:tasks`,
  `project:{id}:lock:{resource}`, `project:{id}:run:{id}:status`,
  `project:{id}:context:{sid}`, `project:{id}:memory:block:{owner}`,
  `project:{id}:ws:progress:{run_id}`).
- Redis failures degrade realtime behavior only. They must not become authority
  write failures.

Milvus is derived semantic search:

- Base vector record: `key`, `embedding`, `metadata_json`, `source_layer`,
  `source_id`.
- Sprout collections include `sprout_vec_messages` and `sprout_vec_tasks`.
- User project collections include `project_{id}_vec_manifest`,
  `project_{id}_vec_structure`, `project_{id}_vec_database`, and
  `project_{id}_vec_evolution`.
- Original text stays in the matching SQLite/Blob layer. Vectors are
  rebuildable.
- Standalone Milvus still needs flush after upsert/delete when tests rely on
  immediate bounded-consistency reads.

Neo4j is the cross-domain graph backbone:

- Sprout labels include `SproutRuntime`, `Agent`, `Capability`, `Tool`, `Task`,
  `ExecutionRun`, `ChangeSet`, `Approval`, `KnowledgeItem`.
- User project labels include `UserProject`, `UserComponent`, `UserModule`,
  `UserDirectory`, `UserFile`, `UserSymbol`, `UserDependency`,
  `UserDataSource`, `UserTable`, `UserVersion`.
- Required user project edges include
  `UserProject-[:HAS_COMPONENT]->UserComponent`,
  `UserComponent-[:HAS_MODULE]->UserModule`,
  `UserDirectory-[:CONTAINS]->UserFile`,
  `UserFile-[:DEFINES]->UserSymbol`,
  `UserSymbol-[:CALLS|EXTENDS|IMPLEMENTS]->UserSymbol`,
  `UserComponent-[:OWNS|USES]->UserDataSource`,
  `UserDataSource-[:CONTAINS]->UserTable`,
  `UserTable-[:FK|READ_MODEL|EVENT]->UserTable`,
  `UserVersion-[:SNAPSHOTS]->UserFile/UserTable`.
- Required bridge edges include
  `Sprout Task-[:TARGETS_PROJECT]->UserProject`,
  `Sprout Task-[:TARGETS_MODULE]->UserModule`,
  `Sprout Task-[:READS|MODIFIES]->UserFile`,
  `Sprout ChangeSet-[:CHANGES]->UserFile/UserTable`,
  `Sprout KnowledgeItem-[:EXPLAINS|MENTIONS]->UserSymbol/UserTable`,
  `Sprout ExecutionRun-[:INSTALLS|USES]->UserDependency`.
- Neo4j relationships are core graph responsibilities, not merely a projection.
  SQLite still owns row-level facts.

### 19.6 Development and verification rules

1. Every write goes authority-first; derived lanes are mirrored asynchronously or
   by fanout/indexer. Derived lane failures are logged and reported as degraded,
   not raised as authority write failures.
2. Calls go through `storage/contracts` protocols and `StorageBundle` fields
   only. Never construct a backend in a caller.
3. New entities must register in `storage/topology.py` or its successor
   topology registry before wiring. The guard must reject dangling authority
   registrations.
4. Cross-layer references use `TargetRef` or explicit bridge fields. Do not add
   `project_*` structure tables to `sprout_*` databases.
5. Deletion must cascade through derived Redis/Milvus/Neo4j lanes and must leave
   enough JSONL/blob evidence for audit unless the deletion policy explicitly
   requires secure purge.
6. Live integration tests remain env-gated
   (`SPROUT_TEST_{REDIS,MILVUS,NEO4J}_URL`). The generated Docker stack lives at
   `~/.sprout/docker/docker-compose.yml`; keep lane diagnostics topology-aware so missing
   optional lanes are reported as skipped, not silently counted as pass.
7. File-backed SQLite tests are required for storage changes. `memory://` cannot
   prove WAL, busy timeout, migration, locking, or corruption behavior.
8. `database-architecture-map.html` in the repo and the copy in Downloads are
   documentation artifacts; when this section changes materially, update that
   HTML too.

### 19.7 Measured footprint baseline

Native/local development should continue to run SQLite + JSONL + Blob in-process
with optional lightweight Redis/Milvus/Neo4j. Full integration verification may
use Docker Redis, Milvus, and Neo4j. Treat Redis/Milvus/Neo4j loss as degraded
capability unless the command is explicitly a lane-health test.

## 20. Execution Layer and Permissions (condensed)

The full audit -- findings R1-R13, the Hermes comparison, the reproduction
commands, and the second-pass corrections -- lives in
`EXECUTION_SECURITY_AUDIT.md` (local reading, not committed). The rules that
bind code review:

### Two execution paths, and only one of them is policy-gated

`Runtime` assembles exactly three brokers: `ProcessBroker`, `FileBroker`,
`ApplyBroker`. The agent tool path (`tools/system_tools.py`) is a second,
thinner path that reaches the same primitives. `NetworkBroker`,
`DatabaseBroker`, and `GitBroker` exist but are **not** assembled outside
tests -- do not describe them as active.

- A new privileged primitive belongs behind the matching broker. Do not open
  a third path; `network_broker.py` / `database_broker.py` / `git_broker.py`
  are the templates.
- A tool's `risk_level` is an *additional* gate, never the only one. A tool
  that shells out must take its environment from `SecretBroker.child_env()`;
  a tool that fetches must consult `NetworkGuard` first and must not follow
  redirects (a redirect leaves the guarded URL behind).

### What every decision must carry

`HardFloor` -> `PolicyEngine` matrix -> `LayeredPolicyEngine` (organization /
workspace / delegation) -> tool-risk floor ->
`PolicyDecision(decision, reason, matched_rules, approval_id)` -> hash-chained
audit.

- The floor runs **before** every layer and no configuration can widen it.
  Adding a rule is a security decision: state in `reason` what it prevents.
- Layers only tighten (`_intersect`), with one controlled exception: an
  organization `allow` rule may pre-approve a `REQUIRE_APPROVAL`.
- **Dangerous text must reach the floor.** If a new action carries a
  command-like string, put it in `ActionRequest.arguments` *and* add its
  argument name to `HardFloor._COMMAND_ARGUMENTS`. A statement kept out of
  `arguments` is a statement no layer can judge -- that was the whole of R8,
  where a bare `ATTACH DATABASE '<abs path>'` cleared every layer through an
  action rated `ALLOW`.
- **Reject raw input before resolving it.** `classifier.is_device_namespace()`
  exists because resolving `\\?\UNC\host\share` can trigger outbound SMB
  authentication. Any new path entry point runs that check before
  `Path.resolve()`.
- Fail closed by default. `weixin_ilink`'s `dm_policy` is `closed`, and only
  the literal `open` bypasses the allowlist -- a mistyped value must fall back
  to the allowlist, not to "accept everyone". Never add a default that admits
  senders.

### Approval rules

- Per source: interactive asks; cron/automation deny outright; an MCP client
  parks and only the operator decides, through Web/CLI. MCP itself never
  exposes `decide` -- that asymmetry is deliberate (AUTHZ_DESIGN 5.2/5.3).
- Approving a change is not enough to land it: `apply()` refuses a proposal
  whose `test_results` contain a failure unless the caller passes
  `allow_failing_tests=True`.
- Verification runs where the change is (the sandbox worktree), never in
  `workspace.root`; otherwise a green run proves nothing about the pending
  diff.
  `ChangeProposal.files_changed` must name real workspace-relative paths,
  untracked files included.

### Test rules for guards (an expensive lesson)

Ablation is the acceptance test for a security guard: delete the guard and
the test protecting it **must fail**. `.workbuddy/ablation_check.py` and
`ablation_check2.py` do that for the audit fixes. Two traps, both hit here:

1. **An assertion about the outcome can pass for the wrong reason.** R9's
   first regression test only asserted that `_safe_target()` returned `None`;
   with the guard removed, the `relative_to(root)` fallback produced the same
   `None`, so the ablation did not catch it. Assert the behaviour *only the
   guard* produces -- for R9, "zero calls to `Path.resolve()`". When two code
   paths lead to the same result, an outcome assertion proves nothing.
2. Never ship a guard test you have not watched fail.

### Open items -- do not assume these are handled

- **R6**: the three brokers are still unwired, so `SecurityLayer` is *not*
  yet the only execution choke point. Wiring them and turning the tool path
  into broker thin-wrappers is one design question, not two.
- **R12**: the sandbox is a git worktree -- same filesystem, OS user, network,
  and kernel. There is no container or OS-level backend. The READMEs state
  this honestly; keep them true.
- **R13**: no pre-execution content scanning, no context-file injection scan,
  no supply-chain (OSV) check.

## 21. Skills: Discovery, Trust, and Delivery

Skills are versioned procedural knowledge the agent can load on demand. The
subsystem answers one question end to end: *the user wants X — do we already
have a skill for it, and if not, where could we get one?*

### 21.1 The four layers

| Layer | Module | Responsibility |
|---|---|---|
| Model | `skills/models.py` | `Skill` (full body), `SkillRecord` (index entry, no body), `TrustLevel` |
| Load | `skills/loader.py` | TOML + `SKILL.md` parsing; `iter_skill_artifacts` is the **single scan path** |
| Index / match | `skills/index.py`, `skills/matcher.py`, `skills/ranker.py` | `index.json` snapshot; keyword scoring; candidate ranking |
| Acquire | `skills/resolver.py`, `broker.py`, `crawler.py`, `sources/`, `trust.py`, `scanner.py` | local → remote → scan → policy → approval → install |

Disclosure is progressive (`context/context.py`): the prompt carries **L0** only
— one summary line per visible skill. **L1** (full body) and **L2** (a file
inside the skill) come from the `skill_view` tool, which `agent/loop.py`
explicitly tells the model to call. Setting `[skills].disclosure = "eager"`
restores the legacy full-body injection.

### 21.2 On-disk layout

Names live in `skills/layout.py` and nowhere else — the broker, CLI, and loader
all read them from there.

```
<skills_dir>/                     # settings.skills_dir, default ~/.sprout/skills
├── <name>.toml                   # single-file skill (source: local)
├── <name>/SKILL.md               # directory skill (source: local)
├── .fetched/<name>/              # downloaded third-party skills
├── .evolved/<name>/              # self-evolution products
├── .quarantine/<name>/           # staged, not yet trusted — never loaded
└── .hub/
    ├── index.json                # derived snapshot of the registry (authority: the store)
    └── remote.json               # crawled candidates — NOT installed, NOT injected
```

`remote.json` is deliberately separate from `index.json`: the latter is what the
matcher and the L0 injection read, so listing uninstalled candidates there would
leak them into the prompt.

### 21.3 Trust is decided by the registry, never by disk

This is the rule most likely to be broken by a well-meaning change, so it is
stated twice in the code.

- Anything under `.fetched/` or `.evolved/` loads as **`untrusted` regardless of
  what its frontmatter claims**. A downloaded skill that could mark itself
  trusted by writing `trust: trusted` would defeat the whole gate.
- `create_skill_registry(dir, index=...)` promotes a skill to trusted only when
  the store says `trusted` **and** the content still hashes to the digest that
  was approved. Editing an installed skill changes its digest and drops it back
  to untrusted.
- No snapshot ⇒ **fail closed**. A missing or unreadable `index.json` means every
  managed skill stays untrusted; it never means "trust what is on disk".
- Only `trusted` skills are injected (`context.py::_skill_visible`).

The digest has **one implementation**: `loader.files_digest`. The broker hashes a
fetched bundle with it and the loader hashes the installed artifact with it, so
the value recorded at install time still matches at load time.

### 21.4 Acquiring a skill

```
local index (always, no network)
   └─ miss → crawl configured catalogs (only on explicit request)
        └─ rank candidates      (ranker.py: install_command +5, CLI-ready +2, missing CLI −3)
             └─ user chooses    (nothing installs itself)
                  └─ SkillInstallBroker.install
                       fetch → .quarantine/ → SkillScanner
                         ├─ fatal finding → DENY (never reaches the policy engine)
                         └─ otherwise → LayeredPolicyEngine.decide
                              ├─ allow            → promote → register → reload registry
                              ├─ require_approval → ApprovalManager (quarantined until a human approves)
                              └─ deny             → discard
```

**Bulk import from a local path.** `sprout skills import <dir>` walks a directory
tree (`sources/tree.py`) instead of searching one flat level, because a foreign
directory — a cloned skills repository — is nested several levels down. Two rules
make the walk correct:

- **A directory holding `SKILL.md` is a skill, and the walk stops there.** Its
  own `assets/SKILL.md` is not a second skill. Pointing the command at a single
  skill folder finds that one skill.
- **The destination is excluded from the walk.** `import .` with the default
  `~/.sprout/skills` would otherwise walk back into what it is writing and
  rediscover every skill as a duplicate.

Each found skill still goes through `SkillInstallBroker.install` — the scanner's
fatal floor and the policy engine both see it. Its `source` is `local`, so the
engine allows it without a prompt (`_FIRST_PARTY_SKILL_SOURCES`); the floor runs
*before* that branch and is not relaxed. `--force` passes `replace=True` so a
re-import overwrites in place instead of accumulating `<name>-<digest>` versions;
without it a same-name skill is skipped.

Two layout facts this command depends on, both easy to get wrong:

- A **single-file `*.toml` skill installs to `<root>/<name>.toml`**, not
  `<root>/<name>/<name>.toml`. The loader scans `*.toml` directly under the root
  and `*/SKILL.md`, so the nested shape installs "successfully" and stays
  permanently invisible. `broker._promote` picks the shape from the bundle.
- **`--dir` is the destination, `--from` is the source.** `install` used to take
  only `--dir` and use it for both, so `install a --source local --dir X` copied
  `X/a` to `X/a-<digest>`. A `--source local` install without `--from` is now a
  usage error rather than an in-place copy.

### 21.4.1 Registry and disk may disagree, and the divergence is reported

The registry (`sprout_audit.db`, the authority on what was *approved*) and the
skills tree (the authority on what is *present*) can drift apart in both
directions, and neither alone is the truth:

- Files deleted by hand leave a registry row pointing at nothing.
- A skill folder copied in by hand has no row, so it loads `untrusted` — visible
  in `index.json`, invisible to the model.

This used to be silent and self-masking: `skills list` read the store,
`index --rebuild` read the disk, and each looked consistent on its own. A
production registry held three skills while the tree held one, and the only
command that could reveal it rewrote the snapshot instead of reporting.

`index.reconcile(store, skills_dir)` is the single comparison point, and its
rules bind new callers:

- **A `missing` row is dropped from the snapshot but kept in the registry.** The
  snapshot must list what can actually load; the registry row must stay so an
  operator can still see the broken install. Deleting it automatically would
  hide exactly the failure worth surfacing.
- **`sprout skills list` marks such rows `[missing]`** and names the dead path,
  plus a closing line pointing at `index --rebuild` (sync the snapshot) and
  `skills forget <name>` (drop the row).
- **`sprout skills forget` touches the registry only.** It leaves files on disk
  and says so when the skill is still present; removing files is a separate act.
- **`index --rebuild` reconciles when it has a registry** and prints the
  divergence; with `--dir` (a standalone tree) it is a plain disk scan and says
  that instead. Never let it silently rewrite over a divergence again.

The broker **decides nothing itself** — it builds an `ActionRequest` and obeys
the engine (the rule in `security/__init__.py`). Sources only *fetch*; nothing is
installed by a source.

Discovery is opt-in and bounded: `catalog_sites` is empty by default, so a stock
runtime never crawls. The crawler visits only operator-listed sites, follows only
same-site links to `SKILL.md`, and caps responses at 1 MB. It is read-only by
construction and bypasses the network broker, which is why the site list must
never be model-controlled.

### 21.5 The two CLI fields, and why they are display-only

`Skill` / `SkillRecord` / `SkillStub` each carry:

| Field | Meaning |
|---|---|
| `install_command` | How to install the skill itself when it is distributed rather than copied (`npx skills add acme/pdf`) |
| `requires_cli` | External binaries the skill needs on PATH |
| `cli_install_command` | How to install those binaries (`brew install pandoc`) |

The first two drive ranking, and `requires_cli` is checked against this machine
with `shutil.which`. **All three are displayed and never executed.** A string
fetched from the internet and then run is a shell injection wearing a skill's
clothes; the command is shown to the human who approves the install instead.

### 21.6 Agent-facing tools

| Tool | Risk | Purpose |
|---|---|---|
| `skill_view` | low | L1/L2: full instructions, or one file inside the skill |
| `skill_search` | low | Match the local index; `crawl=true` also queries catalogs |
| `skill_install` | **high** | Hand a candidate to the broker — always goes through approval |

`skill_view` takes a *provider* rather than a snapshot, and the resolver fires an
`on_install` hook that reloads the registry, so a skill installed mid-session is
usable immediately instead of after a restart.

### 21.7 Config

```toml
[skills]
enabled = true
disclosure = "progressive"                 # progressive (L0 only) | eager (legacy full body)
search_enabled = true
catalog_sites = []                         # crawler seeds; empty = never crawl (the default)
crawl_max_results = 5
crawl_timeout = 15.0
search_extra_on_miss = true
sources = ["catalog", "well-known"]
```

### 21.8 Testing a change here

- `pytest src/Sprout/tests/ -k skills` — the whole subsystem.
- `test_skills_trust_restore.py` is the guard test for §21.3: if you weaken the
  fail-closed rule, it must fail. Never edit it to match new behaviour without
  deciding that behaviour is actually right.
- `test_skills_runtime_wiring.py` boots a real `Runtime`, so a change that
  registers tools or loads skills wrongly is caught without a CLI run.
- The crawler is tested through an injected `fetch=`, never the network.


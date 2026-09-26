---
name: seam-sprout-project
description: "Work on the SEAM Sprout repository: an embedded AI Engineering Runtime for project-level code changes, verification, approvals, memory, storage, web, CLI, MCP, and gateway surfaces."
metadata:
  short-description: Work safely in the SEAM Sprout codebase
---

# SEAM Sprout Project Skill

Use this skill when working inside the `SEAM_Sprout` repository or when another agent needs enough project context to modify, review, test, or explain it.

SEAM Sprout is an embedded AI Engineering Runtime. It turns user intent into planned code edits, isolated execution, verification, approval, integration, and traceability. It is not a chat wrapper. The core product surface is a shared runtime used by the Python API, CLI, React web console, MCP server, gateways, and remote RPC paths.

## Product Frame

Sprout solves the gap between "the model gave me an answer" and "the project has a trustworthy change."

Keep this framing when changing docs, UI copy, prompts, CLI help, or product-facing text:

- AI-generated code should not jump directly into the project.
- Changes should pass through project context, risk controls, verification, human review, and audit.
- The runtime is the central authority: entry points should stay thin and call runtime/public services.
- Git worktree sandboxing isolates change visibility, not OS privileges.
- Humans stay in control of dangerous changes through policy and approvals.

Prefer these terms as-is when precision matters:

- `runtime`
- `sandbox`
- `broker`
- `gateway`
- `MCP`
- `storage schema`
- `approval`
- `proposal`
- `audit`

## Read First

Before making non-trivial changes, read:

- `README.md` for product positioning, architecture, commands, and safety boundary.
- `guidance.md` for repository rules, module ownership, CLI/MCP exposure rules, storage authority rules, and definition of done.
- The owning package under `src/Sprout/` for the specific feature.

For frontend work, also inspect:

- `web/frontend/src/`
- `web/webapi/`

For command changes, inspect:

- `src/Sprout/cli/app.py`
- `src/Sprout/cli/commands/`
- `src/Sprout/cli/ui.py`
- `src/Sprout/cli/i18n.py`

## Architecture Boundaries

Keep domain logic in the package that owns it.

- `runtime/`: assembly, lifecycle, queues, middleware, shared runtime services.
- `agent/`: agent protocol, loops, routing, planning, execution flow.
- `context/`: context construction.
- `message/`: unified message and attachment models.
- `session/`: session and turn models.
- `rootstock/`: session/root persistence backends.
- `memory/`: memory composition, budgets, snapshots, memory stores.
- `storage/`: storage contracts, storage bundle, local implementations, lane lifecycle.
- `security/`: risk levels, policy, approvals.
- `execution/`: brokers and change application.
- `sandbox/`: git worktree sandbox behavior.
- `strategy/`: requirement intake, impact analysis, verification planning.
- `evolution/`: growth candidates, replay, maintenance, trajectory growth.
- `skills/`: versioned skill repository and imports.
- `gateway/`: external message/RPC/task transport gateways.
- `mcp/`: MCP server/client/adapters.
- `web/`: HTTP/WebSocket API and React web console.
- `cli/`: command presentation and transport into runtime services.

Entry points must stay thin. CLI, Web, MCP, and gateways should call runtime/public services instead of opening databases directly or reimplementing agent behavior.

## Storage Rules

Before adding persistence, identify the authority lane. Exactly one store should own a piece of state; other lanes should be rebuildable indexes, caches, or evidence logs.

Important conventions:

- Session persistence belongs behind `rootstock/`, not ad hoc code in `session/`.
- New storage behavior usually needs a contract under `storage/contracts/`, an implementation under `storage/local/`, and participation in `StorageBundle`, `create_storage()`, and status checks.
- Reserved or optional backends should fail with actionable errors when unavailable.
- Storage lifecycle should be inspectable through CLI commands where practical.

## Events and Audit

Every new externally visible state change should register a canonical event in `src/Sprout/events/types.py`.

If the change introduces a new authority or lane boundary, update `EVENT_LANES` so events route to the owning lane. Do not rely on the default audit fallback for conversation, usage, knowledge, or evolution events.

Risky or privileged behavior should leave an audit trail.

## CLI Rules

Every new operational feature should normally be reachable through `sprout`.

When adding or changing commands:

- Put command modules under `src/Sprout/cli/commands/`.
- Register them in `src/Sprout/cli/app.py`.
- Use `Sprout.cli.ui` helpers for user-facing output.
- Provide useful help text and side-effect descriptions.
- Add `--json` for script-consumed output.
- Keep commands non-interactive when a one-shot argument can express the same operation.
- Use `Sprout.cli.i18n.L(zh, en)` for new static CLI labels.

Useful command groups include:

```bash
uv run sprout --help
uv run sprout chat "hello"
uv run sprout info
uv run sprout serve
uv run sprout stop serve

uv run sprout project workspace <path>
uv run sprout project analyze
uv run sprout project task-create <workspace-id> "task"
uv run sprout project changes <task-id>
uv run sprout project approve <proposal-id>
uv run sprout project apply <proposal-id>

uv run sprout db init
uv run sprout db status
uv run sprout storage check

uv run sprout approvals list
uv run sprout audit verify
uv run sprout security check
uv run sprout mcp inspect
```

## MCP Rules

MCP is a public model-facing surface. Expose only safe and useful operations.

Good MCP candidates:

- send a message through the runtime;
- create or inspect sessions;
- read session history;
- list skills;
- search knowledge.

Stdio startup rule:

- `sprout mcp serve` must keep stdout exclusively for MCP JSON-RPC frames.
- Do not run Temporal checks, Docker startup, storage schema initialization, or
  other bootstrap work before `server.run(transport="stdio")`.
- Register tools/resources/prompts first; assemble runtime lazily when a tool or
  resource actually needs runtime state.

Do not expose through MCP:

- approval decisions;
- arbitrary filesystem writes;
- database writes or schema commands;
- raw secrets or configuration;
- growth publishing or rollback;
- privileged operational controls.

## Safety Boundary

Do not describe the git worktree sandbox as a security sandbox.

The sandbox isolates change visibility. It does not isolate privileges. Agent processes share the host filesystem, OS user, network, and kernel. There is no container, VM, or OS-level backend isolation boundary.

Risky actions should go through:

1. hard floor checks;
2. policy checks;
3. resource classification;
4. broker-specific validation;
5. human approval when required;
6. audit records.

## Development Workflow

For code changes:

1. Read the relevant package and tests before editing.
2. Put behavior in the owning module.
3. Keep entry points thin.
4. Add or update events for externally visible state.
5. Add focused tests for new behavior.
6. Update README/guidance when public commands, config, workflows, or safety boundaries change.
7. Run the narrowest useful verification, then broaden when touching shared code.

Common checks:

```bash
uv run pytest
uv run ruff check .
uv run sprout --help
uv run sprout mcp inspect
```

For frontend changes:

```bash
cd web/frontend
npm install
npm run build
```

## Documentation Style

For project-facing copy:

- Lead with the product problem Sprout solves.
- Prefer "AI Engineering Runtime" over vague "AI assistant" language.
- Keep `runtime`, `sandbox`, `broker`, `gateway`, `MCP`, `proposal`, and `approval` in English when translating is awkward.
- Be explicit about the safety boundary.
- Avoid claiming container, VM, or OS-level isolation unless the implementation actually adds it.
- Keep README concise and operational; move development rules to `guidance.md`.

## Definition of Done

A change is usually done when:

- behavior lives in the owning module;
- entry points call runtime/public services;
- storage ownership is clear;
- events and audit are updated when needed;
- CLI/MCP exposure is intentional and safe;
- tests cover the meaningful behavior;
- docs reflect new public behavior;
- `uv run ruff check .` and relevant tests pass, or the reason they were not run is reported.

"""Ask for a workspace before running a coding request typed into chat.

A task intent with no workspace used to fall through to the conversation path,
where the agent has no write tools at all — they live on AGENT nodes, which
only exist once a task is compiled. So "write me a file" was answered by an
agent that could not do it, and nothing said why. These tests pin the ask: the
turn is held, the operator names a directory, and only then is a task created.

The expensive failure mode is the *opposite* one — interrupting ordinary chat
with a workspace prompt — so the ask also requires deterministic keyword
evidence on top of the classifier's opinion, and that guard has its own test.

There are two routes to the ask, and they cover each other's blind spot. The
gate above reads the *wording* before the agent runs, so it is cheap but blind
to a typo. The other is the ``request_workspace`` tool: the agent sees the whole
turn, and when it recognises a coding request it cannot carry out it says so
through a channel the runtime listens on. The tests for that route are below;
the case that motivated it is a real message with a typo in it.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from Sprout.config.loader import default_settings
from Sprout.execution.models import ChangeProposal
from Sprout.intents import detect_task_hint
from Sprout.llm.echo import EchoModel
from Sprout.llm.messages import LLMResponse, LLMStreamEvent, ToolCall
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime
from Sprout.runtime.runtime import WORKSPACE_CONSENT_KEY
from Sprout.task.models import Task, TaskStatus
from Sprout.tests.conftest import TestIntentRecognizer

#: A coding request in the shape a user actually types at the REPL.
CODING_REQUEST = "帮我在当前项目的根目录下写一个冒泡排序的代码"

#: The same request with a typo — ``写一一个`` — which is what a user actually
#: sent. It matches no ``TASK_KEYWORDS`` entry, so the wording gate misses it
#: entirely and the agent is the only thing that can still recognise it.
CODING_REQUEST_TYPO = "你能帮我在整个项目的根目录下写一一个冒泡排序的代码吗"

#: Ordinary chat that an intent classifier may well mislabel as a task.
ORDINARY_CHAT = "use the tool"


def _runtime(tmp_path: Path):
    """A runtime backed by real sqlite stores.

    The in-memory bundle has no metadata store, and a held turn has to survive
    the round trip through the session store — so these tests need the same
    shape the real runtime has, not a stub.
    """
    settings = default_settings()
    settings.model.provider = "echo"
    settings.model.model = "echo-1"
    db = (tmp_path / "meta.db").as_posix()
    settings.storage.operational = f"sqlite:///{(tmp_path / 'op.db').as_posix()}"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{db}"
    settings.storage.session = f"sqlite:///{db}"
    settings.storage.trajectory_dir = str(tmp_path / "traj")
    settings.storage.blobs_dir = str(tmp_path / "blobs")
    settings.security.audit.path = str(tmp_path / "audit.jsonl")
    runtime = create_runtime(settings)
    runtime._intent_recognizer = TestIntentRecognizer()  # noqa: SLF001
    runtime.models.register(EchoModel(), default=True)
    return runtime


async def _stream(runtime, content: str, **kwargs) -> tuple[str, dict, str]:
    """Drive one streaming turn to quiescence.

    Returns the reply text, its metadata, and the session id the runtime
    resolved — the id ``grant_workspace_consent`` needs, which only exists
    after the turn has run.

    The final turn write happens off the stream path, so the background work is
    drained before returning. A real operator takes longer to read the question
    and answer it than this wait takes to finish.
    """
    message = Message(content, channel="cli", user_id="u-1", **kwargs)
    chunks = [chunk async for chunk in runtime.handle_stream(message)]
    if runtime._background_tasks:
        await asyncio.gather(*list(runtime._background_tasks), return_exceptions=True)
    text = "".join(chunk.content for chunk in chunks if chunk.content)
    outbound = next((chunk.outbound for chunk in chunks if chunk.outbound is not None), None)
    metadata = dict(outbound.metadata) if outbound is not None else {}
    return text, metadata, (outbound.session_id if outbound is not None else "")


def _repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()  # enough for workspace-kind detection
    return root


class _AsksForWorkspace:
    """A model that recognises a coding request and calls ``request_workspace``.

    This is the behaviour the tool exists to elicit. The model is deliberately
    dumb about everything else: the point under test is the runtime's response
    to the call, not how the call was decided.

    The test recognizer may call the typo a task, but the wording gate is
    known to miss it; the agent route remains the behavior under test.
    """

    name = "asks-for-workspace"
    model = name

    def __init__(self) -> None:
        self.asked = False

    async def chat(self, messages, *, tools=()) -> LLMResponse:
        available = {spec.name for spec in tools}
        if "request_workspace" in available and not self.asked:
            self.asked = True
            return LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="request_workspace",
                        arguments={"reason": "the user asked for a file"},
                    ),
                ),
                finish_reason="tool_use",
                model=self.name,
            )
        # Reached only if the loop continued after the tool call, which it must
        # not: this stands in for the agent rambling about the obstacle.
        return LLMResponse(
            content="I cannot write files here.", finish_reason="stop", model=self.name
        )

    async def stream_events(self, messages, *, tools=()):
        response = await self.chat(messages, tools=tools)
        yield LLMStreamEvent(content=response.content or "", tool_calls=response.tool_calls)


def _runtime_with_agent(tmp_path: Path, model) -> tuple[object, object]:
    """A runtime whose agent really runs ``model``.

    ``create_runtime`` assembles the loop with the *default* provider, so
    registering a model afterwards does not reach it — the agent keeps the model
    it was built with. The agent is rebuilt here on the factory's own executor,
    which is what makes the real tool set (including ``request_workspace``)
    visible to the double.
    """
    from Sprout.agent.loop import AgentLoop
    from Sprout.agent.planner import DirectPlanner
    from Sprout.agent.router import AgentRouter

    runtime = _runtime(tmp_path)
    runtime.models.register(model, default=True)
    existing = runtime.agents.get(runtime.default_agent)
    runtime.register_agent(
        runtime.default_agent,
        AgentLoop(
            model=model,
            executor=existing.executor,
            max_steps=existing.max_steps,
            planner=DirectPlanner(),
        ),
        default=True,
    )
    runtime.set_router(AgentRouter(runtime.agents, default=runtime.default_agent))
    return runtime, model


async def _ask(runtime) -> str:
    """Ask the runtime for consent and return the session id holding it."""
    _, metadata, session_id = await _stream(runtime, CODING_REQUEST)
    assert metadata.get(WORKSPACE_CONSENT_KEY) is True
    return session_id


@pytest.mark.asyncio
async def test_a_coding_request_without_a_workspace_asks_before_running(tmp_path) -> None:
    """The turn is held rather than handed to an agent that cannot write."""
    runtime = _runtime(tmp_path)
    text, metadata, _ = await _stream(runtime, CODING_REQUEST)

    assert metadata.get(WORKSPACE_CONSENT_KEY) is True
    assert metadata.get("proposed_workspace_root")
    # The reply has to explain *why* nothing happened, or it reads as refusal.
    assert "工作区" in text
    await runtime.stop()


@pytest.mark.asyncio
async def test_no_task_and_no_workspace_are_created_until_the_answer(tmp_path) -> None:
    """Asking is not doing: nothing is registered while the question is open."""
    runtime = _runtime(tmp_path)
    before = await runtime.list_workspaces()
    await _stream(runtime, CODING_REQUEST)

    assert await runtime.list_workspaces() == before
    assert await runtime.list_tasks() == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_ordinary_chat_is_not_interrupted_by_a_workspace_prompt(tmp_path) -> None:
    """A mis-classified intent must not hijack a conversation.

    The classifier is the model's opinion; asking the user a question needs
    deterministic evidence on top of it.
    """
    runtime = _runtime(tmp_path)
    _, metadata, _ = await _stream(runtime, ORDINARY_CHAT)

    assert WORKSPACE_CONSENT_KEY not in metadata
    assert await runtime.list_tasks() == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_granting_consent_registers_the_workspace_and_queues_the_task(
    tmp_path,
) -> None:
    """Agreeing compiles the task, against the directory that was proposed."""
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)

    outbound = await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    assert outbound.metadata.get("task_id")
    tasks = await runtime.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].instruction == CODING_REQUEST
    await runtime.stop()


@pytest.mark.asyncio
async def test_consent_is_single_use(tmp_path) -> None:
    """Answering twice must not queue the same instruction twice."""
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)

    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")
    with pytest.raises(LookupError):
        await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    assert len(await runtime.list_tasks()) == 1
    await runtime.stop()


@pytest.mark.asyncio
async def test_consent_without_a_held_turn_is_an_error(tmp_path) -> None:
    """A session that never asked cannot be granted consent out of thin air."""
    runtime = _runtime(tmp_path)
    with pytest.raises(LookupError):
        await runtime.grant_workspace_consent("no-such-session", user_id="u-1")
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_task_uses_the_directory_the_operator_named(tmp_path) -> None:
    """A directory the operator chose is what gets registered, not cwd."""
    chosen = tmp_path / "somewhere-else"
    chosen.mkdir()
    (chosen / ".git").mkdir()
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)

    await runtime.grant_workspace_consent(session_id, root=chosen, user_id="u-1")

    workspaces = await runtime.list_workspaces()
    assert len(workspaces) == 1
    assert workspaces[0].root == chosen.resolve()
    await runtime.stop()


@pytest.mark.asyncio
async def test_open_workspace_is_idempotent_and_listing_folds_duplicate_roots(
    tmp_path,
) -> None:
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)

    first = await runtime.open_workspace(repo)
    reopened = await runtime.open_workspace(repo)
    legacy_duplicate = await runtime.open_workspace(repo, workspace_id="legacy-copy")

    assert reopened.id == first.id
    assert legacy_duplicate.id != first.id
    assert [item.root for item in await runtime.list_workspaces()] == [repo.resolve()]
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_held_instruction_survives_into_the_task(tmp_path) -> None:
    """What runs is what the operator was shown, not a caller-supplied string.

    ``grant_workspace_consent`` reads the held turn back rather than accepting
    an instruction, so consent cannot be attached to a different task.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)

    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    turns = await runtime.history(session_id)
    held = [turn for turn in turns if turn.role == "user"]
    assert any(turn.content == CODING_REQUEST for turn in held)
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_held_instruction_is_stored_once(tmp_path) -> None:
    """One instruction is one user turn.

    Regression: the hold wrote a turn itself *and* the streaming path persisted
    the turn it was handed, so a single request landed in the session twice.
    Nothing failed — the second row was simply a phantom the consent lookup
    could match.
    """
    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, CODING_REQUEST)

    turns = await runtime.history(session_id)
    matching = [turn for turn in turns if turn.role == "user" and turn.content == CODING_REQUEST]

    assert len(matching) == 1
    await runtime.stop()


# -- the agent-initiated route (``request_workspace``) ----------------------


@pytest.mark.asyncio
async def test_the_agent_can_ask_for_a_workspace_itself(tmp_path) -> None:
    """A request the wording gate missed is still caught, after the agent runs.

    The message here contains a typo that matches no keyword, so
    ``detect_task_hint`` is false and the pre-agent gate stays out of the way.
    The agent reaches the model, recognises the coding request, and calls the
    tool — and the runtime must treat that exactly like its own gate.
    """
    runtime, model = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    assert detect_task_hint(CODING_REQUEST_TYPO) is False  # the premise

    text, metadata, _ = await _stream(runtime, CODING_REQUEST_TYPO)

    assert model.asked is True
    assert metadata.get(WORKSPACE_CONSENT_KEY) is True
    assert metadata.get("proposed_workspace_root")
    # The runtime's question, not the agent's prose about being unable to write.
    assert "I cannot write files here." not in text
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_agent_route_creates_nothing_until_consent(tmp_path) -> None:
    """Holding through the tool is the same hold: no task, no workspace yet.

    The hold itself is asserted, not just the absence of the task: "no task was
    created" is also true when the turn was never held at all, which is exactly
    the failure this suite exists to catch.
    """
    runtime, _ = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    _, metadata, _ = await _stream(runtime, CODING_REQUEST_TYPO)

    assert metadata.get(WORKSPACE_CONSENT_KEY) is True
    assert await runtime.list_tasks() == []
    assert await runtime.list_workspaces() == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_agent_route_holds_the_instruction_once(tmp_path) -> None:
    """One instruction is one held turn, whichever route held it.

    Same invariant as the keyword route, and worth pinning separately: this one
    is persisted by a different call site, after the streamed turn has already
    been yielded.
    """
    runtime, _ = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    _, _, session_id = await _stream(runtime, CODING_REQUEST_TYPO)

    turns = await runtime.history(session_id)
    matching = [
        turn for turn in turns if turn.role == "user" and turn.content == CODING_REQUEST_TYPO
    ]

    assert len(matching) == 1
    # One turn *and it is held*. Counting alone would pass on an unheld turn.
    envelope = dict(matching[0].metadata or {})
    assert envelope.get("message_metadata", {}).get(WORKSPACE_CONSENT_KEY) is True
    await runtime.stop()


@pytest.mark.asyncio
async def test_consent_from_the_agent_route_still_queues_the_task(tmp_path) -> None:
    """The two routes converge: consent resumes the held instruction."""
    repo = _repo(tmp_path)
    runtime, _ = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    _, _, session_id = await _stream(runtime, CODING_REQUEST_TYPO)

    outbound = await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    assert outbound.metadata.get("task_id")
    tasks = await runtime.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].instruction == CODING_REQUEST_TYPO
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_agent_does_not_ask_again_when_a_workspace_is_bound(
    tmp_path,
) -> None:
    """With a workspace there is nothing to ask for.

    The tool is still in the tool set, so a model could call it anyway; doing so
    must not re-hold a turn that already has its answer. Otherwise the resume
    would hold itself, and the task would never start.
    """
    repo = _repo(tmp_path)
    runtime, model = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    workspace = await runtime.open_workspace(repo)

    _, metadata, _ = await _stream(
        runtime, CODING_REQUEST_TYPO, metadata={"workspace_id": workspace.id}
    )

    # The agent called the tool; the runtime declined to act on it, because the
    # message carries the answer already. The guard is what stops here — not
    # the agent's restraint.
    assert model.asked is True
    assert WORKSPACE_CONSENT_KEY not in metadata
    assert await runtime.list_tasks() == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_agent_does_not_reask_when_the_session_has_an_active_task(
    tmp_path,
) -> None:
    """A status question next to a running task must not mint a second one."""
    repo = _repo(tmp_path)
    runtime, _ = _runtime_with_agent(tmp_path, _AsksForWorkspace())
    _, _, session_id = await _stream(runtime, "hello")
    workspace = await runtime.open_workspace(repo)
    await runtime.create_task(
        workspace.id,
        "写个冒泡排序",
        metadata={"session_id": session_id},
    )

    _, metadata, _ = await _stream(
        runtime,
        CODING_REQUEST_TYPO,
        session_id=session_id,
    )

    assert WORKSPACE_CONSENT_KEY not in metadata
    assert len(await runtime.list_tasks()) == 1
    await runtime.stop()


# -- telling the asker that the task parked --------------------------------


async def _parked_task(
    runtime,
    tmp_path: Path,
    session_id: str | None,
    status: TaskStatus = TaskStatus.WAITING_APPROVAL,
    *,
    instruction: str = "写一个冒泡排序",
) -> Task:
    """A task in ``status``, filed under ``session_id`` (or under none).

    Written straight to the store rather than driven through a worker: the
    states worth testing here take a whole agent run to reach naturally, and
    what is under test is the *lookup* over those states, not how a task gets
    into one.
    """
    workspaces = await runtime.list_workspaces()
    if not workspaces:
        workspaces = [await runtime.open_workspace(_repo(tmp_path))]
    metadata: dict[str, object] = {}
    if session_id:
        metadata["session_id"] = session_id
    task = await runtime.create_task(workspaces[0].id, instruction, metadata=metadata)
    if status is not task.status:
        task = replace(task, status=status)
        await runtime.storage.metadata.save_task(task)
    return task


@pytest.mark.asyncio
async def test_a_consented_task_is_filed_under_the_surface_it_came_from(
    tmp_path,
) -> None:
    """A chat request must not be recorded as ``unknown`` after consent.

    Regression: consent resumes over an internal message, and the task source
    was read from *that* message. ``coerce_source("internal")`` has no alias, so
    every consented task was filed as ``unknown`` — which is also the value that
    means "we could not tell", making the record useless for grading.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)

    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    task = (await runtime.list_tasks())[0]
    assert task.source == "cli", "the surface the operator typed at was lost"
    await runtime.stop()


@pytest.mark.asyncio
async def test_parked_tasks_are_found_by_the_session_that_asked(tmp_path) -> None:
    """Only this session's waiting tasks are reported back to it."""
    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    mine = await _parked_task(runtime, tmp_path, session_id)
    foreign = await _parked_task(runtime, tmp_path, "some-other-session")
    unfiled = await _parked_task(runtime, tmp_path, None)

    parked = await runtime.parked_tasks_for_session(session_id)

    assert [task.id for task in parked] == [mine.id]
    assert foreign.id not in {task.id for task in parked}
    assert unfiled.id not in {task.id for task in parked}
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_task_queued_from_chat_can_be_reported_back_to_it(tmp_path) -> None:
    """The link the notice travels on: the task remembers the session.

    Without it a parked task belongs to no conversation, so the reporter that
    exists to tell the operator has nothing to match on — which is how a file
    got written and sat unmentioned for the rest of a session.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)
    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")
    # Consent starts a background worker, which owns the task's status from then
    # on. Driving it to a parked state by hand while that worker is live is a
    # race — it overwrites whatever we set. Stopping it first is what makes the
    # state below ours to assert on.
    await runtime.stop_worker()

    task = (await runtime.list_tasks())[0]
    assert str(task.metadata.get("session_id") or "") == session_id
    # Parked by hand: a real worker takes a whole agent run to reach a hold,
    # and the subject here is the session link, not the run.
    await runtime.storage.metadata.save_task(
        replace(task, status=TaskStatus.WAITING_APPROVAL)
    )

    parked = await runtime.parked_tasks_for_session(session_id)

    assert [item.id for item in parked] == [task.id]
    await runtime.stop()


@pytest.mark.asyncio
async def test_settled_tasks_are_not_reported_as_waiting(tmp_path) -> None:
    """A task that is done, or still running, is not something to decide about.

    Reporting these would train the operator to ignore the notice, which is the
    only thing that makes the notice worth printing.
    """
    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    await _parked_task(runtime, tmp_path, session_id, TaskStatus.COMPLETED)
    await _parked_task(runtime, tmp_path, session_id, TaskStatus.RUNNING)

    assert await runtime.parked_tasks_for_session(session_id) == []
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_parked_task_points_at_the_approval_that_unblocks_it(tmp_path) -> None:
    """The task says *which* command to run and with which id.

    ``waiting_approval`` alone does not say whether the hold is an approval or a
    change proposal, and those take different ids and different subcommands —
    so the answer is resolved from what actually exists.
    """
    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    task = await _parked_task(runtime, tmp_path, session_id)
    record = await runtime.approvals.request(
        "cli_tool_run", {"command": "pytest", "args": []}, task_id=task.id
    )

    kind, handle = await runtime.task_progress(task)

    assert kind == "approval"
    assert handle == record.id
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_change_proposal_takes_precedence_over_an_approval(tmp_path) -> None:
    """When both exist, the proposal is the next thing to decide.

    A proposal cannot be approved until it is requested, so an approval on the
    same task — the one that let the work run — is already spent. Pointing the
    operator at it would be a dead end.
    """
    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    task = await _parked_task(runtime, tmp_path, session_id, TaskStatus.READY_TO_APPLY)
    await runtime.approvals.request("cli_tool_run", {"command": "ls"}, task_id=task.id)
    proposal = ChangeProposal(task_id=task.id)
    await runtime.storage.metadata.save_change_proposal(proposal)

    kind, handle = await runtime.task_progress(task)

    assert kind == "proposal"
    assert handle == proposal.id
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_reporter_names_the_exact_command_and_decides_nothing(
    tmp_path, capsys
) -> None:
    """The notice is actionable and inert: it prints a command, it does not run.

    Parking is the safety property. A notice that resolved the hold it was
    reporting would defeat the very gate the operator is being asked to pass.
    """
    from Sprout.cli.commands.chat import _report_parked_tasks

    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    task = await _parked_task(runtime, tmp_path, session_id)
    record = await runtime.approvals.request(
        "cli_tool_run", {"command": "pytest", "args": []}, task_id=task.id
    )
    capsys.readouterr()

    await _report_parked_tasks(runtime, session_id)

    printed = capsys.readouterr().out
    assert task.id[:8] in printed
    assert f"sprout approvals approve {record.id[:8]}" in printed
    # Still waiting: printing is the whole of what the reporter does.
    assert [item.id for item in await runtime.pending_approvals()] == [record.id]
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_reporter_stays_quiet_when_nothing_is_parked(tmp_path, capsys) -> None:
    """No parked work means no notice — an always-on banner stops being read."""
    from Sprout.cli.commands.chat import _report_parked_tasks

    runtime = _runtime(tmp_path)
    _, _, session_id = await _stream(runtime, "hello")
    await _parked_task(runtime, tmp_path, session_id, TaskStatus.COMPLETED)
    capsys.readouterr()

    await _report_parked_tasks(runtime, session_id)

    assert capsys.readouterr().out == ""
    await runtime.stop()


# -- the consent is remembered for the session, not just the resumed turn ------


@pytest.mark.asyncio
async def test_consent_is_not_asked_again_for_the_next_coding_request(
    tmp_path,
) -> None:
    """Answering "yes, for this task" must not be asked again next turn.

    The grant was remembered only on the one resumed message, so a session that
    had already answered looked unbound again on the very next coding request.
    An operator hit this four times in a row: each "yes" queued a task and
    consumed the consent, and the next message asked for a directory again.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)
    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    _, metadata, _ = await _stream(runtime, CODING_REQUEST, session_id=session_id)

    assert WORKSPACE_CONSENT_KEY not in metadata, "the workspace was asked for twice"
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_later_coding_request_actually_runs_in_the_bound_workspace(
    tmp_path,
) -> None:
    """Staying silent is not enough: the request has to become a task.

    Suppressing the question alone would be worse than asking it — the coding
    intent would still fall through to the conversation path, where the agent
    has no write tools, so "yes" would quiet the prompt and still do nothing.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)
    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")

    await _stream(runtime, CODING_REQUEST, session_id=session_id)

    tasks = await runtime.list_tasks()
    assert len(tasks) == 2, "the second coding request was not queued"
    assert all(task.workspace_id for task in tasks), "a task ran without a workspace"
    await runtime.stop()


@pytest.mark.asyncio
async def test_a_status_question_is_not_run_as_a_task(tmp_path) -> None:
    """A bound workspace must not lower the bar for what counts as an instruction.

    "好了吗" is a status question. The classifier labelled it ``task`` — its own
    reason read "are you done?" — and with a workspace already bound in the
    session that was enough to queue a full read→sandbox→plan→agent→evaluate
    run for three characters. The keyword gate the ask path already requires is
    what absorbs that mislabel, so it is required here too.
    """
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)
    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")
    before = len(await runtime.list_tasks())

    _, metadata, _ = await _stream(runtime, "好了吗", session_id=session_id)

    assert not metadata.get("task_id"), "a status question was queued as a task"
    assert len(await runtime.list_tasks()) == before, "a task was created anyway"
    await runtime.stop()


@pytest.mark.asyncio
async def test_consent_stays_scoped_to_its_own_session(tmp_path) -> None:
    """One session's answer must not silence another session's question."""
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    first = await _ask(runtime)
    await runtime.grant_workspace_consent(first, root=repo, user_id="u-1")

    # ``_stream`` fixes the user; a distinct session id is what makes this a
    # different conversation, which is the thing under test.
    _, metadata, other = await _stream(
        runtime, CODING_REQUEST, session_id="another-session"
    )

    assert other != first
    assert metadata.get(WORKSPACE_CONSENT_KEY) is True, "another session inherited it"
    await runtime.stop()


@pytest.mark.asyncio
async def test_the_bound_workspace_survives_a_reload(tmp_path) -> None:
    """The grant lives on the session record, so it outlives the process."""
    repo = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    session_id = await _ask(runtime)
    await runtime.grant_workspace_consent(session_id, root=repo, user_id="u-1")
    await runtime.stop()

    reloaded = _runtime(tmp_path)
    session = await reloaded.get_session(session_id)

    assert session is not None
    assert reloaded.session_workspace_id(session), "the session forgot its workspace"
    await reloaded.stop()

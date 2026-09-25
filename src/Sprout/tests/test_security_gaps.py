"""Regression tests for the residual audit findings R8, R9 and R10.

R1/R2/R3/R5/R7 live in ``test_execution_gate.py``. These three are what the
first pass left open, and they share one theme: the decision layer was never
*shown* what it was deciding about.

* **R8** — ``DatabaseBroker._decide`` passed an empty argument dict, so a
  statement such as ``ATTACH DATABASE '<abs path>'`` reached no layer at all:
  ``PolicyRule.argument_guards`` could not target it and the hard floor only
  scans ``command``/``cmd``/``argv``/``script``. Measured on this host
  (sqlite3 3.50.4): ``ATTACH DATABASE`` succeeds and creates the file, whereas
  ``SELECT load_extension(...)`` is refused by SQLite itself, and a
  multi-statement string is refused by ``execute()``.
* **R9** — device-namespace paths were resolved *before* being judged, which is
  the one thing Hermes' rule forbids: resolving ``\\?\\UNC\\host\\share`` can
  trigger outbound SMB authentication and leak an NTLM hash.
* **R10** — the weixin gateway defaulted to ``dm_policy = "open"``, so a bot
  nobody configured accepted everybody, and a mistyped policy value was read as
  open too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Sprout.config.settings import WeixinIlinkSettings
from Sprout.execution.database_broker import DatabaseBroker
from Sprout.execution.file_broker import FileBroker
from Sprout.execution.models import SandboxRef
from Sprout.gateway.channels.weixin_ilink import (
    WeixinIlinkAccount,
    WeixinIlinkGateway,
    WeixinIlinkInbound,
)
from Sprout.security.access import (
    AccessDecision,
    ActionRequest,
    ActionType,
    PolicyDecision,
)
from Sprout.security.engine import PolicyEngine
from Sprout.security.floor import HardFloor
from Sprout.workspace.classifier import classify, classify_with_reason, is_device_namespace
from Sprout.workspace.models import ResourceKind, ResourceRef, Workspace, WorkspaceKind
from Sprout.workspace.read_broker import ReadBroker

# Windows separators spelled out, so a reader can count the backslashes instead
# of guessing how many layers of escaping a literal survived.
_BS = chr(92)
_DEVICE_DOT = _BS * 2 + "." + _BS  # \\.\
_DEVICE_QMARK = _BS * 2 + "?" + _BS  # \\?\
_DEVICE_NT = _BS + "?" + "?" + _BS  # \??\
_EXTENDED_LOCAL = _BS * 2 + "?" + _BS + "C:" + _BS + "Users"  # \\?\C:\Users
_UNC_PLAIN = _BS * 2 + "server" + _BS + "share"  # \\server\share


def _workspace(root: Path) -> Workspace:
    return Workspace(id="ws-gaps", root=root, kind=WorkspaceKind.LOCAL_DIRECTORY)


def _db_request(sql: str, *, action: ActionType = ActionType.DB_READ) -> ActionRequest:
    return ActionRequest(
        task_id="task-db",
        action=action,
        resource=ResourceRef(
            workspace_id="ws-gaps", path="data/app.db", kind=ResourceKind.DATA
        ),
        arguments={"sql": sql},
    )


# -- R8: a statement is a command, so the policy has to see it ----------------


class _RecordingPolicy:
    """Policy engine stand-in that records the request it was shown."""

    def __init__(self, decision: AccessDecision = AccessDecision.ALLOW) -> None:
        self.requests: list[ActionRequest] = []
        self._decision = decision

    def decide(self, request: ActionRequest) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(decision=self._decision, reason="recorded")


@pytest.mark.asyncio
async def test_database_broker_shows_the_statement_to_the_policy(tmp_path) -> None:
    policy = _RecordingPolicy()
    broker = DatabaseBroker(policy)  # type: ignore[arg-type]

    await broker.query(_workspace(tmp_path), tmp_path / "app.db", "SELECT 1")

    assert [request.arguments for request in policy.requests] == [{"sql": "SELECT 1"}]


def test_the_hard_floor_reads_database_statements() -> None:
    decision = HardFloor().check(
        _db_request("ATTACH DATABASE 'C:/somewhere/else.db' AS ext")
    )

    assert decision is not None
    assert decision.decision is AccessDecision.DENY
    assert "floor:sqlite-attach" in decision.matched_rules


def test_load_extension_is_on_the_floor_too() -> None:
    decision = HardFloor().check(_db_request("SELECT load_extension('evil.dll')"))

    assert decision is not None
    assert "floor:sqlite-load-extension" in decision.matched_rules


def test_ordinary_statements_clear_the_floor() -> None:
    """An un-overridable rule has to stay narrow.

    ``attach`` as a bare word, as a column prefix (``attachments``) or inside a
    string literal must not deny a request.
    """
    floor = HardFloor()

    for sql in (
        "SELECT * FROM turns ORDER BY seq",
        "INSERT INTO notes VALUES ('attach the file first')",
        "SELECT count(*) FROM attachments",
        "UPDATE jobs SET state = 'leased' WHERE id = ?",
    ):
        assert floor.check(_db_request(sql)) is None, sql


@pytest.mark.asyncio
async def test_attach_database_is_refused_end_to_end(tmp_path) -> None:
    """Without the fix the statement cleared every layer and created the file."""
    outside = tmp_path / "outside.db"
    broker = DatabaseBroker(PolicyEngine())

    result = await broker.query(
        _workspace(tmp_path),
        tmp_path / "main.db",
        f"ATTACH DATABASE '{outside}' AS ext",
    )

    assert result.allowed is False
    assert not outside.exists()


# -- R9: refuse the raw string, never resolve it first ------------------------


def test_device_namespace_prefixes_are_recognised() -> None:
    assert is_device_namespace(_DEVICE_DOT + "D:" + _BS + "SEAM_Sprout")
    assert is_device_namespace(_DEVICE_NT + "C:" + _BS + "Windows")
    assert is_device_namespace(_DEVICE_QMARK + "UNC" + _BS + "host" + _BS + "share")
    assert is_device_namespace(_DEVICE_QMARK + "GLOBALROOT" + _BS + "Device")


def test_harmless_paths_are_not_flagged() -> None:
    """Hermes is explicit that these two are unaffected by the rule."""
    assert not is_device_namespace(_EXTENDED_LOCAL)
    assert not is_device_namespace(_UNC_PLAIN)
    assert not is_device_namespace("src/Sprout/cli/app.py")
    assert not is_device_namespace("")


def test_classify_refuses_a_device_path_without_resolving_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = Path.resolve

    def spy(self: Path, *args: Any, **kwargs: Any) -> Path:
        calls.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", spy)
    raw = _DEVICE_DOT + "D:" + _BS + "SEAM_Sprout" + _BS + "src"

    assert classify(raw, workspace_root=".") is ResourceKind.EXTERNAL
    assert classify_with_reason(raw, workspace_root=".") == (
        ResourceKind.EXTERNAL,
        "device-namespace",
    )
    # The whole point of R9: judging the raw string means nothing was resolved,
    # so no outbound authentication could have been triggered on the way.
    assert calls == []


def test_safe_target_refuses_a_device_path_without_resolving_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""Containment alone would reject ``\\.\D:\\x`` — but only *after* resolving it.

    The ablation run proved this: with the guard removed from ``_safe_target``,
    ``relative_to(root)`` still turned the path away, so a test that only asserts
    "returns None" is decoration. What the guard actually buys is that no
    resolution ever happens, which is what keeps ``\\?\\UNC\\host\\share`` from
    reaching the network on the way to being rejected.
    """
    calls: list[str] = []
    original = Path.resolve

    def spy(self: Path, *args: Any, **kwargs: Any) -> Path:
        calls.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", spy)
    workspace = _workspace(tmp_path)
    sandbox = SandboxRef(id="s1", kind="git_worktree", root=tmp_path)

    assert ReadBroker._safe_target(workspace, _DEVICE_DOT + "D:" + _BS + "x") is None
    assert FileBroker._safe_target(sandbox, _DEVICE_NT + "C:" + _BS + "x") is None
    assert calls == []


# -- R10: an unconfigured gateway admits nobody ------------------------------


class _UnusedClient:
    """A rejected sender must never reach the client."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"client.{name} must not be used")


class _StubStateStore:
    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    async def get_context_token(self, peer: str) -> str:
        return self.tokens.get(peer, "")

    async def set_context_token(self, peer: str, token: str) -> None:
        self.tokens[peer] = token


def _inbound(sender: str, *, message_id: str = "m1") -> WeixinIlinkInbound:
    return WeixinIlinkInbound(from_user_id=sender, text="hello", message_id=message_id)


def _gateway(
    *,
    dm_policy: str | None = None,
    allowed_users: tuple[str, ...] = (),
) -> WeixinIlinkGateway:
    kwargs: dict[str, Any] = {}
    if dm_policy is not None:
        kwargs["dm_policy"] = dm_policy
    return WeixinIlinkGateway(
        None,  # type: ignore[arg-type]  # a rejected sender never reaches runtime
        client=_UnusedClient(),  # type: ignore[arg-type]
        account=WeixinIlinkAccount(token="t"),
        state_store=_StubStateStore(),  # type: ignore[arg-type]
        allowed_users=allowed_users,
        **kwargs,
    )


def _record_admissions(gateway: WeixinIlinkGateway, sink: list[str]) -> None:
    """Replace the two message handlers so admission is observable on its own."""

    async def conversation(message: Any, instruction: str, context_token: str) -> dict:
        sink.append(message.from_user_id)
        return {"ok": True, "kind": "conversation"}

    async def task(
        message: Any, instruction: str, context_token: str, *, workspace_id: str = ""
    ) -> dict:
        sink.append(message.from_user_id)
        return {"ok": True, "kind": "task"}

    gateway._handle_conversation = conversation  # type: ignore[method-assign]
    gateway._handle_task = task  # type: ignore[method-assign]


def test_weixin_settings_default_to_closed_admission() -> None:
    assert WeixinIlinkSettings().dm_policy == "closed"


@pytest.mark.asyncio
async def test_an_unconfigured_gateway_ignores_every_sender() -> None:
    gateway = _gateway()

    assert await gateway.handle_inbound(_inbound("stranger")) == {
        "ok": True,
        "ignored": "not_allowed",
    }


@pytest.mark.asyncio
async def test_only_the_literal_open_policy_admits_a_stranger() -> None:
    admitted: list[str] = []
    gateway = _gateway(dm_policy="open")
    _record_admissions(gateway, admitted)

    result = await gateway.handle_inbound(_inbound("stranger"))

    assert admitted == ["stranger"]
    assert "ignored" not in result


@pytest.mark.asyncio
async def test_a_mistyped_admission_policy_falls_back_to_the_allowlist() -> None:
    """A typo must not widen access, and must not shut the gateway either."""
    admitted: list[str] = []
    gateway = _gateway(dm_policy="opne", allowed_users=("friend",))
    _record_admissions(gateway, admitted)

    assert await gateway.handle_inbound(_inbound("stranger")) == {
        "ok": True,
        "ignored": "not_allowed",
    }
    assert admitted == []

    assert "ignored" not in await gateway.handle_inbound(
        _inbound("friend", message_id="m2")
    )
    assert admitted == ["friend"]

"""Tests for the Feishu gateway adapter.

The regression these lock in: ``handle_event`` used to run a
``im.message.receive_v1`` payload without checking anything, so a forged POST to
the callback URL drove the agent. Every event must now pass the verification
token, and the signature too once an encrypt key is configured.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

import pytest

from Sprout.config.loader import default_settings
from Sprout.gateway.channels.feishu import FeishuGateway
from Sprout.runtime.factory import create_runtime

ENCRYPT_KEY = "test-encrypt-key"


def _signed_headers(raw: bytes, *, timestamp: str | None = None, nonce: str = "nonce-1"):
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    digest = hashlib.sha256(
        stamp.encode() + nonce.encode() + ENCRYPT_KEY.encode() + raw
    ).hexdigest()
    return {
        "X-Lark-Request-Timestamp": stamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": digest,
    }


def _message_body(token: str | None = None, workspace_id: str = "") -> dict:
    body: dict = {
        "event_type": "im.message.receive_v1",
        "event": {
            "sender": {"sender_id": "ou_123"},
            "message": {"content": {"text": "explain this project"}},
        },
    }
    if token is not None:
        body["header"] = {"event_type": "im.message.receive_v1", "token": token}
    if workspace_id:
        body["workspace_id"] = workspace_id
    return body


def test_feishu_url_verification(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)
    gateway = FeishuGateway(runtime, verification_token="token-1")
    body = {
        "type": "url_verification",
        "token": "token-1",
        "challenge": "challenge-1",
    }
    assert gateway.url_verification(body) == {"challenge": "challenge-1"}


def test_feishu_url_verification_rejects_a_wrong_token(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)
    gateway = FeishuGateway(runtime, verification_token="token-1")

    assert gateway.url_verification(
        {"type": "url_verification", "token": "nope", "challenge": "x"}
    ) is None


def test_feishu_message_event_creates_task(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)

    async def run() -> None:
        workspace = await runtime.open_workspace(tmp_path)
        gateway = FeishuGateway(
            runtime,
            verification_token="token-1",
            default_workspace_id=workspace.id,
        )
        response = await gateway.handle_event(
            _message_body("token-1", workspace_id=workspace.id)
        )
        assert isinstance(response, object)

    asyncio.run(run())


def test_feishu_message_event_without_a_token_is_refused(tmp_path: Path) -> None:
    """The forged-callback regression: no token, no execution."""
    runtime = _runtime_for_test(tmp_path)

    async def run() -> None:
        workspace = await runtime.open_workspace(tmp_path)
        gateway = FeishuGateway(
            runtime,
            verification_token="token-1",
            default_workspace_id=workspace.id,
        )
        with pytest.raises(ValueError, match="verification-token"):
            await gateway.handle_event(
                _message_body(None, workspace_id=workspace.id)
            )

    asyncio.run(run())


def test_feishu_message_event_with_a_wrong_token_is_refused(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)

    async def run() -> None:
        gateway = FeishuGateway(runtime, verification_token="token-1")
        with pytest.raises(ValueError, match="verification-token"):
            await gateway.handle_event(_message_body("forged"))

    asyncio.run(run())


def test_feishu_gateway_without_a_configured_token_refuses_everything(
    tmp_path: Path,
) -> None:
    """Fail closed: an unverifiable gateway must not accept anything."""
    runtime = _runtime_for_test(tmp_path)

    async def run() -> None:
        gateway = FeishuGateway(runtime, verification_token="")
        assert gateway.verification_enabled is False
        with pytest.raises(ValueError, match="no verification token"):
            await gateway.handle_event(_message_body("anything"))

    asyncio.run(run())


def test_feishu_signature_is_required_once_an_encrypt_key_is_set(
    tmp_path: Path,
) -> None:
    runtime = _runtime_for_test(tmp_path)

    async def run() -> None:
        gateway = FeishuGateway(
            runtime, verification_token="token-1", encrypt_key=ENCRYPT_KEY
        )
        assert gateway.signature_enabled is True
        body = _message_body("token-1")
        raw = b'{"event_type":"im.message.receive_v1"}'

        # A body without signature headers is refused even though the token fits.
        with pytest.raises(ValueError, match="request-signature"):
            await gateway.handle_event(body, headers={}, raw_body=raw)

        # A stale timestamp is treated as a replay.
        stale = str(int(time.time()) - 3600)
        with pytest.raises(ValueError, match="request-signature"):
            await gateway.handle_event(
                body,
                headers=_signed_headers(raw, timestamp=stale),
                raw_body=raw,
            )

        # A digest computed over different bytes does not match.
        with pytest.raises(ValueError, match="request-signature"):
            await gateway.handle_event(
                body,
                headers=_signed_headers(b"other bytes"),
                raw_body=raw,
            )

        # The genuine signature passes verification.
        gateway.require_authentic(
            body, headers=_signed_headers(raw), raw_body=raw
        )

    asyncio.run(run())


def test_feishu_signature_check_is_skipped_without_an_encrypt_key(tmp_path: Path) -> None:
    runtime = _runtime_for_test(tmp_path)
    gateway = FeishuGateway(runtime, verification_token="token-1")

    assert gateway.signature_enabled is False
    gateway.require_authentic(_message_body("token-1"))


def _runtime_for_test(root: Path):
    (root / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    settings = default_settings()
    settings.storage.operational = "memory://"
    settings.storage.knowledge = "memory://"
    settings.storage.observations.enabled = False
    settings.storage.metadata = f"sqlite:///{root / 'metadata.db'}"
    settings.storage.trajectory_dir = str(root / "trajectory")
    settings.storage.blobs_dir = str(root / "blobs")
    # Keep the audit stream in tmp_path too: the default points at the real
    # ~/.sprout/data/audit/security.jsonl, and tests must not write there.
    settings.security.audit.path = str(root / "security.jsonl")
    return create_runtime(settings)

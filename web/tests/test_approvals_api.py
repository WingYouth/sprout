"""Approval decision API tests (AUTHZ §5.2).

The web API is one of exactly two human decision surfaces (the other is the
CLI). These tests go through the real Starlette app so the route wiring, the
status codes, and the runtime's resume hook are all exercised.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from web.webapi.app import create_app
from web.webapi.database import WebDatabase

_FRONTEND = Path(__file__).resolve().parents[2] / "web" / "frontend"


@pytest.fixture
def database(tmp_path) -> WebDatabase:
    db = WebDatabase(tmp_path / "webapi.db")
    db.initialize()
    yield db
    db.close()


def _client(runtime, database) -> TestClient:
    app = create_app(
        runtime,
        database=database,
        static_dir=_FRONTEND if (_FRONTEND / "index.html").exists() else None,
    )
    return TestClient(app)


@pytest.mark.asyncio
async def test_pending_approval_can_be_approved_over_http(runtime, database) -> None:
    record = await runtime.approvals.request(
        "file.write",
        {"path": "src/app.py"},
        task_id="task-1",
        requested_by="agent",
        resource_scope="src/**",
        source="interactive",
    )

    with _client(runtime, database) as client:
        listed = client.get("/api/approvals/pending").json()["approvals"]
        assert [item["id"] for item in listed] == [record.id]
        assert listed[0]["resource_scope"] == "src/**"

        decided = client.post(
            f"/api/approvals/{record.id}/decide",
            json={"approve": True, "decided_by": "reviewer", "reason": "looks fine"},
        )
        assert decided.status_code == 200
        body = decided.json()
        assert body["status"] == "approved"
        assert body["decided_by"] == "reviewer"

        # A second decision on the same record is a conflict, not a new grant.
        again = client.post(f"/api/approvals/{record.id}/decide", json={"approve": False})
        assert again.status_code == 409


def test_decide_requires_the_approve_field(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.post("/api/approvals/abc/decide", json={})
    assert response.status_code == 400


def test_decide_unknown_approval_is_not_found(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.post("/api/approvals/missing/decide", json={"approve": True})
    assert response.status_code == 404


def test_list_approvals_rejects_unknown_status(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.get("/api/approvals", params={"status": "nonsense"})
    assert response.status_code == 400


def test_sweep_endpoint_reports_how_many_expired(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.post("/api/approvals/sweep")
    assert response.status_code == 200
    assert response.json()["swept"] == 0

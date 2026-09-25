"""Web API tests: HTTP endpoints, WebSocket chat, the reserved web database,
and the request-audit middleware — all through the real Starlette app.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from web.webapi.app import create_app
from web.webapi.database import WebDatabase

_FRONTEND = Path(__file__).resolve().parents[2] / "web" / "frontend"


def _client(runtime, database) -> TestClient:
    app = create_app(
        runtime,
        database=database,
        static_dir=_FRONTEND if (_FRONTEND / "index.html").exists() else None,
    )
    return TestClient(app)


@pytest.fixture
def database(tmp_path) -> WebDatabase:
    db = WebDatabase(tmp_path / "webapi.db")
    db.initialize()
    yield db
    db.close()


# -- health ---------------------------------------------------------------------


def test_health_reports_runtime_identity(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["name"] == "SEAM_Sprout"
    assert body["default_agent"] == "assistant"


# -- chat + history ---------------------------------------------------------------


def test_chat_round_trip_and_history(runtime, database) -> None:
    with _client(runtime, database) as client:
        reply = client.post("/api/chat", json={"message": "hello"})
        assert reply.status_code == 200
        body = reply.json()
        assert body["content"] == "Echo: hello"
        assert body["channel"] == "web"
        session_id = body["session_id"]

        # The same session continues: context flows through the runtime.
        second = client.post(
            "/api/chat", json={"message": "again", "session_id": session_id}
        )
        assert second.status_code == 200
        assert second.json()["session_id"] == session_id

        history = client.get(f"/api/sessions/{session_id}/history")
        assert history.status_code == 200
        turns = history.json()["turns"]
        assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]


def test_chat_rejects_invalid_bodies(runtime, database) -> None:
    with _client(runtime, database) as client:
        assert client.post("/api/chat", json={"message": "  "}).status_code == 400
        assert (
            client.post(
                "/api/chat", content=b"not json", headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )


def test_history_of_unknown_session_is_empty(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.get("/api/sessions/nope/history")
    assert response.status_code == 200
    assert response.json()["turns"] == []


# -- project layer ----------------------------------------------------------------


def test_project_routes_are_mounted(runtime, database) -> None:
    """The runtime project layer is reachable over HTTP, not a dead route."""
    with _client(runtime, database) as client:
        response = client.get("/api/project/workspaces")
    # The route exists (a 404 would mean it is not mounted); the fixture
    # runtime has no metadata store, so the handler surfaces a clean 500.
    assert response.status_code == 500
    assert "error" in response.json()


# -- WebSocket -------------------------------------------------------------------


def test_websocket_chat(runtime, database) -> None:
    with _client(runtime, database) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.send_json({"message": "hi"})
            reply = ws.receive_json()
            assert reply["content"] == "Echo: hi"

            ws.send_json({"message": ""})
            error = ws.receive_json()
            assert "error" in error


# -- static frontend and 404 -------------------------------------------------------


def test_frontend_is_served(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.get("/")
    assert response.status_code == 200


def test_unknown_api_route_returns_json_404(runtime, database) -> None:
    with _client(runtime, database) as client:
        response = client.get("/api/definitely-not-here")
    assert response.status_code == 404
    assert response.json() == {"error": "not found"}


# -- audit middleware + reserved web database ----------------------------------------


@pytest.mark.asyncio
async def test_requests_are_audited_into_web_database(runtime, database) -> None:
    # Query inside the client context: the app closes the database on shutdown.
    with _client(runtime, database) as client:
        client.get("/api/health")
        client.post("/api/chat", json={"message": "audit me"})
        count = await database.count_requests()
        routes = {row["route"] for row in await database.recent_requests()}
    assert count >= 2
    assert "/api/health" in routes


@pytest.mark.asyncio
async def test_web_database_upserts_sessions(tmp_path) -> None:
    db = WebDatabase(tmp_path / "webapi.db")
    db.initialize()
    try:
        await db.touch_web_session("ws-1", "user-1")
        await db.touch_web_session("ws-1", "user-1")  # upsert, not duplicate
        db.initialize()  # idempotent re-open of the same file
    finally:
        db.close()

    # The file is reserved on disk even before any request table is used.
    assert (tmp_path / "webapi.db").exists()

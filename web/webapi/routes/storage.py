"""Storage and lane endpoints for the web console.

These routes are intentionally transport-thin: they call the runtime's
storage bundle and existing lane contracts, so Milvus and Neo4j are reached
through the same production wiring as the CLI and runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from Sprout.storage.bundle import storage_status
from Sprout.storage.contracts.vectors import MESSAGES
from Sprout.storage.plan import data_layer_plan
from Sprout.storage.topology import consistency_violations, topology_plan

if TYPE_CHECKING:
    from Sprout.config.settings import Settings
    from Sprout.runtime.runtime import Runtime


def create_storage_routes(runtime: Runtime, settings: Settings | None = None) -> list[Route]:
    from Sprout.config.loader import load_settings

    effective = settings or load_settings()
    storage = runtime.storage

    async def plan(request: Request) -> JSONResponse:
        return JSONResponse({"lanes": data_layer_plan(effective.storage)})

    async def topology(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                **topology_plan(),
                "consistency_violations": consistency_violations(),
            }
        )

    async def status(request: Request) -> JSONResponse:
        # DSNs carry credentials (``neo4j://user:pass@host``), so they go out
        # through the same redactor ``/api/settings`` uses. This route used to
        # return them verbatim while that one masked the identical values — the
        # console showed ``[REDACTED]`` on one screen and the live password on
        # the next, and masking must not depend on which endpoint is asked.
        from Sprout.security.redact import Redactor

        scrub = Redactor().scrub
        return JSONResponse(
            {
                "storage": await storage_status(storage),
                "lanes": {
                    "cache": scrub(effective.storage.cache),
                    "vectors": scrub(effective.storage.vectors),
                    "graph": scrub(effective.storage.graph),
                    "context": scrub(effective.storage.context),
                },
            }
        )

    async def vector_count(request: Request) -> JSONResponse:
        store = storage.vectors
        if store is None:
            return JSONResponse({"error": "vector lane is not configured"}, status_code=503)
        namespace = request.query_params.get("namespace")
        try:
            count = await store.count(namespace=namespace)
        except Exception as exc:  # noqa: BLE001 - lane errors must be readable
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"count": count, "namespace": namespace})

    async def vector_upsert(request: Request) -> JSONResponse:
        store = storage.vectors
        if store is None:
            return JSONResponse({"error": "vector lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        error = _validate_vector_payload(data)
        if error:
            return JSONResponse({"error": error}, status_code=400)
        try:
            await store.upsert(
                data["key"],
                data["vector"],
                namespace=data.get("namespace", MESSAGES),
                metadata=data.get("metadata") or {},
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"ok": True, "key": data["key"]}, status_code=201)

    async def vector_search(request: Request) -> JSONResponse:
        store = storage.vectors
        if store is None:
            return JSONResponse({"error": "vector lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        error = _validate_vector_payload(data, key_required=False)
        if error:
            return JSONResponse({"error": error}, status_code=400)
        limit = data.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            return JSONResponse(
                {"error": "'limit' must be an integer from 1 to 100"},
                status_code=400,
            )
        try:
            hits = await store.search(
                data["vector"],
                limit=limit,
                namespace=data.get("namespace", MESSAGES),
                filters=data.get("filters"),
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"hits": [_hit_to_dict(hit) for hit in hits]})

    async def vector_delete(request: Request) -> JSONResponse:
        store = storage.vectors
        if store is None:
            return JSONResponse({"error": "vector lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        key = data.get("key")
        if not isinstance(key, str) or not key:
            return JSONResponse({"error": "'key' must be a non-empty string"}, status_code=400)
        namespace = data.get("namespace", MESSAGES)
        if not isinstance(namespace, str):
            return JSONResponse({"error": "'namespace' must be a string"}, status_code=400)
        try:
            deleted = await store.delete(key, namespace=namespace)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"deleted": bool(deleted), "key": key, "namespace": namespace})

    async def graph_status(request: Request) -> JSONResponse:
        graph = storage.graph
        session_store = storage.session_store()
        backend = getattr(session_store, "backend_name", None)
        if graph is None and backend != "neo4j":
            return JSONResponse(
                {
                    "configured": False,
                    "backend": backend or "none",
                    "sessions": 0,
                    "turns": 0,
                }
            )
        result: dict[str, Any] = {
            "configured": bool(graph),
            "backend": getattr(graph, "backend_name", backend),
            "sessions": await session_store.count_sessions(),
            "turns": await session_store.count_turns(),
        }
        return JSONResponse(result)

    async def graph_turns(request: Request) -> JSONResponse:
        graph = storage.graph
        session_store = storage.session_store()
        backend = getattr(session_store, "backend_name", None)
        if graph is None and backend != "neo4j":
            return JSONResponse({"error": "Neo4j graph lane is not configured"}, status_code=503)
        session_id = request.path_params["session_id"]
        limit = int(request.query_params.get("limit", 20))
        try:
            turns = await session_store.recent_turns(session_id, limit=limit)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse(
            {
                "session_id": session_id,
                "turns": [
                    {
                        "id": turn.id,
                        "role": turn.role,
                        "content": turn.content,
                        "created_at": turn.created_at.isoformat(),
                    }
                    for turn in turns
                ],
            }
        )

    async def graph_merge_node(request: Request) -> JSONResponse:
        graph = _graph_store(storage)
        if graph is None:
            return JSONResponse({"error": "Neo4j graph lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        label = data.get("label")
        key_prop = data.get("key_prop", "id")
        props = data.get("props")
        if not isinstance(label, str) or not label:
            return JSONResponse({"error": "'label' must be a non-empty string"}, status_code=400)
        if not isinstance(key_prop, str) or not key_prop:
            return JSONResponse({"error": "'key_prop' must be a non-empty string"}, status_code=400)
        if not isinstance(props, dict):
            return JSONResponse({"error": "'props' must be an object"}, status_code=400)
        try:
            await graph.merge_node(label, key_prop, props)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"ok": True, "label": label}, status_code=201)

    async def graph_merge_relation(request: Request) -> JSONResponse:
        graph = _graph_store(storage)
        if graph is None:
            return JSONResponse({"error": "Neo4j graph lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        required = ("src_label", "src_key", "rel", "dst_label", "dst_key")
        if any(not isinstance(data.get(field), str) or not data.get(field) for field in required):
            return JSONResponse(
                {"error": "src_label, src_key, rel, dst_label, and dst_key are required"},
                status_code=400,
            )
        props = data.get("props") or {}
        if not isinstance(props, dict):
            return JSONResponse({"error": "'props' must be an object"}, status_code=400)
        try:
            await graph.merge_relation(
                data["src_label"],
                data["src_key"],
                data["rel"],
                data["dst_label"],
                data["dst_key"],
                props=props,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"ok": True, "relation": data["rel"]}, status_code=201)

    async def graph_drop_node(request: Request) -> JSONResponse:
        graph = _graph_store(storage)
        if graph is None:
            return JSONResponse({"error": "Neo4j graph lane is not configured"}, status_code=503)
        data = await _json_body(request)
        if isinstance(data, JSONResponse):
            return data
        label = data.get("label")
        key_prop = data.get("key_prop", "id")
        key_value = data.get("key_value")
        if not isinstance(label, str) or not isinstance(key_value, str):
            return JSONResponse({"error": "'label' and 'key_value' are required"}, status_code=400)
        try:
            deleted = await graph.drop_node(label, key_prop, key_value)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=503)
        return JSONResponse({"deleted": deleted, "label": label})

    return [
        Route("/api/storage/plan", plan, methods=["GET"]),
        Route("/api/storage/topology", topology, methods=["GET"]),
        Route("/api/storage/status", status, methods=["GET"]),
        Route("/api/storage/vectors/count", vector_count, methods=["GET"]),
        Route("/api/storage/vectors/upsert", vector_upsert, methods=["POST"]),
        Route("/api/storage/vectors/search", vector_search, methods=["POST"]),
        Route("/api/storage/vectors/delete", vector_delete, methods=["POST"]),
        Route("/api/storage/graph/status", graph_status, methods=["GET"]),
        Route("/api/storage/graph/turns/{session_id}", graph_turns, methods=["GET"]),
        Route("/api/storage/graph/node", graph_merge_node, methods=["POST"]),
        Route("/api/storage/graph/relation", graph_merge_relation, methods=["POST"]),
        Route("/api/storage/graph/node/delete", graph_drop_node, methods=["POST"]),
    ]


async def _json_body(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    return data


def _validate_vector_payload(data: dict[str, Any], *, key_required: bool = True) -> str | None:
    if key_required:
        key = data.get("key")
        if not isinstance(key, str) or not key:
            return "'key' must be a non-empty string"
    vector = data.get("vector")
    if not isinstance(vector, list) or not vector:
        return "'vector' must be a non-empty array"
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in vector):
        return "'vector' must contain only numbers"
    namespace = data.get("namespace", MESSAGES)
    if not isinstance(namespace, str) or not namespace:
        return "'namespace' must be a non-empty string"
    return None


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    return {
        "key": hit.key,
        "score": hit.score,
        "namespace": hit.namespace,
        "metadata": dict(hit.metadata),
    }


def _graph_store(storage: Any):
    graph = getattr(storage, "graph", None)
    if graph is not None and hasattr(graph, "merge_node"):
        return graph
    session_store = storage.session_store()
    if getattr(session_store, "backend_name", None) == "neo4j":
        return session_store
    return None

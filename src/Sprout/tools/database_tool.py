"""Read-only SQLite query tool gated by the :class:`DatabaseBroker`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from Sprout.execution.database_broker import DatabaseBroker
from Sprout.tools.result import ToolResult
from Sprout.tools.spec import ToolSpec
from Sprout.workspace.models import Workspace, WorkspaceKind


class DatabaseQueryTool:
    """Run a read-only SQL query through the policy-controlled database broker."""

    spec = ToolSpec(
        name="database_query",
        description="Run a read-only SQL query against a SQLite database. The "
        "statement is evaluated by the authorization policy before execution.",
        input_schema={
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Path to the SQLite database file.",
                },
                "sql": {
                    "type": "string",
                    "description": "Read-only SELECT SQL statement.",
                },
                "workspace_id": {
                    "type": "string",
                    "description": "Workspace id used for the policy decision.",
                    "default": "",
                },
            },
            "required": ["database", "sql"],
        },
        risk_level="low",
    )

    def __init__(self, broker: DatabaseBroker) -> None:
        self._broker = broker

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolResult:
        database = arguments.get("database")
        sql = arguments.get("sql")
        if not isinstance(database, str) or not database.strip():
            return ToolResult.failure("Argument 'database' must be a non-empty string")
        if not isinstance(sql, str) or not sql.strip():
            return ToolResult.failure("Argument 'sql' must be a non-empty string")

        workspace = Workspace(
            id=str(arguments.get("workspace_id") or ""),
            root=Path.cwd(),
            kind=WorkspaceKind.LOCAL_DIRECTORY,
        )
        result = await self._broker.query(workspace, database, sql)
        if not result.allowed:
            return ToolResult.denied(result.reason or "Database query not allowed")
        rows = [list(row) for row in result.rows]
        return ToolResult.success(
            json.dumps(rows, ensure_ascii=False, default=str),
            data={"rows": rows},
        )


__all__ = ["DatabaseQueryTool"]

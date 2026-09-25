"""MCP resource adapter (reserved for future resource bridging)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RemoteResource:
    """A resource exposed by an external MCP server."""

    uri: str
    name: str | None = None
    description: str | None = None
    mime_type: str | None = None


def to_remote_resource(resource: object) -> RemoteResource:
    return RemoteResource(
        uri=getattr(resource, "uri", ""),
        name=getattr(resource, "name", None),
        description=getattr(resource, "description", None),
        mime_type=getattr(resource, "mimeType", None),
    )

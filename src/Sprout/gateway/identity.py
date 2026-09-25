"""Identity carried alongside messages into the runtime (AUTHZ §2.1).

Trust model: **roles never come from the message body.** ``message.metadata``
is caller-supplied, so honouring ``metadata["roles"]`` meant anyone could send
``roles = ["admin"]`` and escalate. Identity now enters through an entry-point
adapter that can vouch for it:

===============  ==========================================  =========================
Entry point      Identity source                             Trust basis
===============  ==========================================  =========================
CLI              OS user, loopback only                      local process is the owner
Web API          session token -> server-side user lookup     session ticket
MCP client       ``[[mcp.clients]] principal`` declaration   deployment configuration
Runtime internals ``service_principal()``                    isolated from user identity
===============  ==========================================  =========================

``principal_from_message`` is kept, but only as a *degraded* read: it copies
``user_id`` and ``display_name`` and always discards roles. Any roles found in
the metadata are reported through :func:`discarded_roles` so the caller can
publish ``auth.roles_discarded``.
"""

from __future__ import annotations

from dataclasses import dataclass

from Sprout.message.models import Message

SYSTEM_USER_ID = "system"

#: Metadata key that callers keep trying to use for self-declared roles.
ROLES_METADATA_KEY = "roles"


@dataclass(frozen=True, slots=True)
class Principal:
    """An identity that has already been resolved through a trusted entry point."""

    user_id: str
    display_name: str | None = None
    roles: tuple[str, ...] = ()
    #: True only when an entry-point adapter asserted the identity from a trusted
    #: source; unauthenticated principals may not receive grants.
    authenticated: bool = False
    #: Which adapter produced this principal (``cli``, ``web``, ``mcp_client``...).
    source: str = ""

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_service(self) -> bool:
        """Internal runtime behaviour, kept distinguishable from users in audits."""
        return self.user_id == SYSTEM_USER_ID


def service_principal() -> Principal:
    """The identity for runtime-internal behaviour (never a user's identity)."""
    return Principal(
        user_id=SYSTEM_USER_ID,
        display_name="Runtime",
        roles=("system",),
        authenticated=True,
        source="runtime",
    )


def principal_from_message(
    message: Message,
    *,
    roles: tuple[str, ...] = (),
    source: str = "",
    authenticated: bool = False,
) -> Principal:
    """Build a principal from a message, discarding any self-declared roles.

    ``roles`` must be injected by the entry-point adapter from a trusted source
    (a token lookup, a config declaration); anything in ``message.metadata`` is
    ignored.
    """
    return Principal(
        user_id=message.user_id,
        display_name=message.metadata.get("display_name"),
        roles=tuple(roles),
        authenticated=authenticated,
        source=source or message.channel,
    )


def discarded_roles(message: Message) -> tuple[str, ...]:
    """Roles the caller tried to self-declare; the caller should audit them."""
    raw = message.metadata.get(ROLES_METADATA_KEY, ())
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(role) for role in raw)
    return ()

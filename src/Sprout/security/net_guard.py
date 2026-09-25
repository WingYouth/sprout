"""Outbound network guard: SSRF and cloud-credential protection (AUTHZ §6.3).

``network.get`` stays ``ALLOW`` in the policy matrix, but "allowed" must not
mean "may reach the link-local metadata endpoint". The guard resolves the
target and refuses anything that is not globally routable — RFC1918, loopback,
link-local (including ``169.254.169.254``), CGNAT, multicast, and IPv6
unique-local. Explicit host allowlisting via ``[security.network]
allow_private`` is the only way through, and ``blocked_domains`` adds a
``website_blocklist`` on top.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from threading import Lock
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from Sprout.config.settings import SecuritySettings

# Metadata services that hand out cloud credentials.
BLOCKED_HOSTNAMES: tuple[str, ...] = (
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
)

Resolver = Callable[[str], Sequence[str]]


@dataclass(frozen=True, slots=True)
class NetworkVerdict:
    """The guard's answer for one URL."""

    allowed: bool
    reason: str = ""
    host: str = ""

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class NetworkGuard:
    """Decides whether an outbound URL may be requested.

    Known limitation (AUTHZ §6.3): the verdict is computed from one DNS
    resolution while the HTTP client performs its own, so a TTL-0 record that
    answers with a public address first and a loopback address second can still
    slip through (DNS rebinding). Pinning the connection to the verified address
    needs a custom transport, which is not wired yet; the TTL on this cache at
    least stops a *poisoned or stale* answer from being honoured forever.
    """

    allow_private: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    resolver: Resolver | None = None
    #: How long a resolution stays cached, and how many hosts may be held. Both
    #: used to be unbounded, so a poisoned answer lived for the process
    #: lifetime and the cache grew with every host ever contacted.
    dns_ttl_seconds: float = 60.0
    dns_cache_max: int = 256
    _dns_cache: dict[str, tuple[float, tuple[str, ...]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @classmethod
    def from_settings(cls, security: SecuritySettings) -> NetworkGuard:
        network = security.network
        return cls(
            allow_private=tuple(network.allow_private),
            blocked_domains=tuple(network.blocked_domains),
        )

    def check(self, url: str) -> NetworkVerdict:
        """Return a verdict; the guard fails closed on unparsable or unresolvable URLs."""
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            return NetworkVerdict(False, f"Unsupported URL scheme: {parts.scheme!r}")
        host = (parts.hostname or "").strip().casefold()
        if not host:
            return NetworkVerdict(False, "URL has no host")
        if host in BLOCKED_HOSTNAMES or host.endswith(".internal"):
            return NetworkVerdict(False, f"Metadata/internal host is blocked: {host}", host)
        for pattern in self.blocked_domains:
            if fnmatch(host, pattern.casefold()):
                return NetworkVerdict(False, f"Host is on the website blocklist: {host}", host)
        if self._is_exempt(host):
            return NetworkVerdict(True, "Host is explicitly allowlisted", host)

        addresses = self._resolve(host)
        if not addresses:
            return NetworkVerdict(False, f"Cannot resolve host: {host}", host)
        for address in addresses:
            if self._is_exempt(address):
                continue
            if not _is_global(address):
                return NetworkVerdict(
                    False,
                    f"Non-routable address is blocked (SSRF protection): {address}",
                    host,
                )
        return NetworkVerdict(True, "", host)

    async def acheck(self, url: str) -> NetworkVerdict:
        """Async wrapper; DNS resolution happens off the event loop."""
        return await asyncio.to_thread(self.check, url)

    # -- internals ---------------------------------------------------------
    def _is_exempt(self, host: str) -> bool:
        for entry in self.allow_private:
            candidate = entry.strip().casefold()
            if not candidate:
                continue
            if candidate == host or fnmatch(host, candidate):
                return True
            try:
                network = ipaddress.ip_network(candidate, strict=False)
            except ValueError:
                continue
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                continue
            if address.version == network.version and address in network:
                return True
        return False

    def _resolve(self, host: str) -> tuple[str, ...]:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return (host,)
        if self.resolver is not None:
            return tuple(self.resolver(host))
        now = time.monotonic()
        with self._lock:
            cached = self._dns_cache.get(host)
            if cached is not None:
                expires_at, addresses = cached
                if expires_at > now:
                    return addresses
                del self._dns_cache[host]
        resolved = _system_resolve(host)
        with self._lock:
            if len(self._dns_cache) >= self.dns_cache_max:
                self._prune_cache(now)
            self._dns_cache[host] = (now + self.dns_ttl_seconds, resolved)
        return resolved

    def _prune_cache(self, now: float) -> None:
        """Drop expired entries first, then the oldest half if still full."""
        expired = [host for host, (expires_at, _) in self._dns_cache.items() if expires_at <= now]
        for host in expired:
            del self._dns_cache[host]
        if len(self._dns_cache) < self.dns_cache_max:
            return
        oldest = sorted(self._dns_cache.items(), key=lambda item: item[1][0])
        for host, _ in oldest[: max(1, len(oldest) // 2)]:
            del self._dns_cache[host]


def _system_resolve(host: str) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return ()
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


def _is_global(address: str) -> bool:
    """True only for globally routable unicast addresses.

    ``is_global`` already excludes loopback, RFC1918, link-local, CGNAT,
    multicast, reserved, unspecified, IPv6 unique-local, and IPv4-mapped
    private ranges, which is exactly the SSRF surface we care about.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped
    return bool(parsed.is_global)


def check_url(url: str, *, allow_private: Sequence[str] = ()) -> NetworkVerdict:
    """Module-level convenience for one-off checks."""
    return NetworkGuard(allow_private=tuple(allow_private)).check(url)

"""Routing rules for Weixin iLink inbound messages."""

from __future__ import annotations

from dataclasses import dataclass

_TASK_PREFIXES = ("/task", "/project", "/任务", "/项目")


@dataclass(frozen=True, slots=True)
class WeixinIlinkRoute:
    kind: str
    instruction: str


class WeixinIlinkRouter:
    """Classify a Weixin text message as conversation or project task."""

    def classify(self, text: str) -> WeixinIlinkRoute:
        normalized = text.strip()
        lowered = normalized.casefold()

        for prefix in _TASK_PREFIXES:
            lowered_prefix = prefix.casefold()
            if lowered == lowered_prefix:
                return WeixinIlinkRoute(kind="task", instruction="")
            if lowered.startswith(f"{lowered_prefix} ") or lowered.startswith(
                f"{lowered_prefix}\t"
            ):
                instruction = normalized[len(prefix) :].strip()
                return WeixinIlinkRoute(kind="task", instruction=instruction)

        return WeixinIlinkRoute(kind="conversation", instruction=normalized)


__all__ = ["WeixinIlinkRoute", "WeixinIlinkRouter"]

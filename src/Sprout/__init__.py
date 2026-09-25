"""Public API for the SEAM Sprout runtime.

Exports are lazy so that importing a leaf module does not eagerly initialize
the LLM, HTTP, and gateway dependency graph. This also keeps Temporal's
workflow sandbox from pulling non-deterministic modules into workflow
validation.
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Sprout.agent.base import Agent, AgentResult, ModelAgent
    from Sprout.agent.loop import AgentLoop
    from Sprout.config.loader import load_settings
    from Sprout.config.settings import Settings
    from Sprout.events.bus import Event, EventBus
    from Sprout.llm.aiyallm import AiyallmProvider
    from Sprout.llm.base import ModelProvider
    from Sprout.llm.echo import EchoModel
    from Sprout.message.models import Message, OutboundMessage
    from Sprout.runtime.factory import create_runtime
    from Sprout.runtime.lifecycle import managed
    from Sprout.runtime.runtime import Runtime
    from Sprout.security.approval import ApprovalManager
    from Sprout.security.policy import SecurityPolicy
    from Sprout.security.risk import RiskLevel
    from Sprout.storage.bundle import StorageBundle, create_storage
    from Sprout.tools.result import ToolResult
    from Sprout.tools.spec import ToolSpec

_LAZY_EXPORTS = {
    "Agent": ("Sprout.agent.base", "Agent"),
    "AgentLoop": ("Sprout.agent.loop", "AgentLoop"),
    "AgentResult": ("Sprout.agent.base", "AgentResult"),
    "ApprovalManager": ("Sprout.security.approval", "ApprovalManager"),
    "AiyallmProvider": ("Sprout.llm.aiyallm", "AiyallmProvider"),
    "EchoModel": ("Sprout.llm.echo", "EchoModel"),
    "Event": ("Sprout.events.bus", "Event"),
    "EventBus": ("Sprout.events.bus", "EventBus"),
    "Message": ("Sprout.message.models", "Message"),
    "ModelAgent": ("Sprout.agent.base", "ModelAgent"),
    "ModelProvider": ("Sprout.llm.base", "ModelProvider"),
    "OutboundMessage": ("Sprout.message.models", "OutboundMessage"),
    "RiskLevel": ("Sprout.security.risk", "RiskLevel"),
    "Runtime": ("Sprout.runtime.runtime", "Runtime"),
    "SecurityPolicy": ("Sprout.security.policy", "SecurityPolicy"),
    "Settings": ("Sprout.config.settings", "Settings"),
    "StorageBundle": ("Sprout.storage.bundle", "StorageBundle"),
    "ToolResult": ("Sprout.tools.result", "ToolResult"),
    "ToolSpec": ("Sprout.tools.spec", "ToolSpec"),
    "create_runtime": ("Sprout.runtime.factory", "create_runtime"),
    "create_storage": ("Sprout.storage.bundle", "create_storage"),
    "load_settings": ("Sprout.config.loader", "load_settings"),
    "managed": ("Sprout.runtime.lifecycle", "managed"),
}

__all__ = [
    "Agent",
    "AgentLoop",
    "AgentResult",
    "ApprovalManager",
    "AiyallmProvider",
    "EchoModel",
    "Event",
    "EventBus",
    "Message",
    "ModelAgent",
    "ModelProvider",
    "OutboundMessage",
    "RiskLevel",
    "Runtime",
    "SecurityPolicy",
    "Settings",
    "StorageBundle",
    "ToolResult",
    "ToolSpec",
    "create_runtime",
    "create_storage",
    "load_settings",
    "managed",
]

try:
    __version__ = version("seam-sprout")
except PackageNotFoundError:  # pragma: no cover - local source tree
    __version__ = "0.0.0.dev0"


def __getattr__(name: str):
    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value

try:
    __version__ = version("seam-sprout")
except PackageNotFoundError:  # pragma: no cover - local source tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "Agent",
    "AgentLoop",
    "AgentResult",
    "ApprovalManager",
    "AiyallmProvider",
    "EchoModel",
    "Event",
    "EventBus",
    "Message",
    "ModelAgent",
    "ModelProvider",
    "OutboundMessage",
    "RiskLevel",
    "Runtime",
    "SecurityPolicy",
    "Settings",
    "StorageBundle",
    "ToolResult",
    "ToolSpec",
    "create_runtime",
    "create_storage",
    "load_settings",
    "managed",
]

"""Reserved argument keys the tool layer injects, and no tool declares.

``Tool.invoke`` takes only ``arguments``, so a tool that delegates onward has no
other channel to learn *which task* and *which source* it is acting for. The
keys here are the ones the executor adds for that purpose.

They live in their own module because both sides need them and must not import
each other: ``tools/executor.py`` imports the registry, which imports
``tools/system_tools.py``, which needs the key names. A constant defined in the
executor and imported by the tools closed that cycle and broke application
startup.

**A reserved key is never part of an approval fingerprint.** It is injected
after the decision, and a tool that forwards it into its own policy arguments
would make identical calls in different turns fingerprint differently — one
approval would then cover only the turn that produced it.
"""

from __future__ import annotations

#: Carries ``{task_id, source, requested_by}`` from ``ToolExecutor`` to a tool
#: that hands work to a broker. The broker gates the delegated action under its
#: own tool name and a task-scoped grant, so dropping this context makes an
#: already-approved call look unapproved one layer down.
CONTEXT_KEY = "_sprout_context"

#: Tools the executor attaches the context to. An explicit list rather than
#: every tool: a tool that cannot reach a second policy layer has no use for it,
#: and adding a reserved key to arguments whose schema does not declare one is
#: noise at best.
CONTEXT_TOOLS = frozenset({"cli_tool_run"})

__all__ = ["CONTEXT_KEY", "CONTEXT_TOOLS"]

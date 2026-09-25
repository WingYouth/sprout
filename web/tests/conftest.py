"""Fixtures for the web API tests: a runtime wired exactly like `sprout serve`."""

from __future__ import annotations

import pytest

from Sprout.agent.executor import ActionExecutor
from Sprout.agent.loop import AgentLoop
from Sprout.llm.echo import EchoModel
from Sprout.llm.registry import ModelRegistry
from Sprout.runtime.runtime import Runtime
from Sprout.skills.registry import SkillRegistry
from Sprout.storage.bundle import StorageBundle
from Sprout.tools.executor import ToolExecutor
from Sprout.tools.registry import ToolRegistry


@pytest.fixture
def runtime() -> Runtime:
    """An offline runtime (echo model, in-memory storage, no tools)."""
    storage = StorageBundle.in_memory()
    tools = ToolRegistry()
    executor = ToolExecutor(tools=tools)
    model = EchoModel()
    instance = Runtime(
        storage=storage,
        models=ModelRegistry(),
        tools=tools,
        skills=SkillRegistry(),
    )
    instance.models.register(model, default=True)
    instance.register_agent(
        "assistant",
        AgentLoop(model=model, executor=ActionExecutor(tools=executor)),
        default=True,
    )
    return instance

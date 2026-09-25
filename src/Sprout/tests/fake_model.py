"""A deterministic stand-in for a real provider, for end-to-end tests.

The end-to-end path (task -> graph -> agent -> evaluation -> approval -> apply)
had no automated coverage: every defect found while building it was caught by
driving a real model by hand, and the suite stayed green through all of them.
Running a real provider inside the suite is not an option — it needs a key,
takes tens of seconds, and would go red when the model changes rather than when
the code does.

This model is scripted instead. It reads the prompt and decides what a model
would plausibly do at that point, so the pipeline exercises its real branches
while the inputs stay fixed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from Sprout.llm.messages import LLMMessage, LLMResponse, ToolCall
from Sprout.tools.spec import ToolSpec

#: Marks in the prompt that identify which stage is asking. The strategy
#: planner and the agent loop both go through ``chat``, so the model has to
#: tell them apart the same way a real one would — from the prompt.
_PLAN_MARKER = "output_schema"


class FakeModel:
    """Scripted responses: a plan, then edits, then a summary.

    ``edits`` maps a path to the content the model "writes" when asked to
    implement the requirement. ``fail_with`` makes the verification fail on
    purpose, so the refusal path can be tested without a broken repository.
    """

    def __init__(
        self,
        *,
        edits: dict[str, str] | None = None,
        plan_steps: Sequence[str] = (),
        name: str = "fake",
        calls: list[str] | None = None,
    ) -> None:
        self.name = name
        self.model = name
        #: Which edits the scripted model will perform, path -> content.
        self.edits = dict(edits or {})
        #: Step descriptions for the strategy planner's structured output.
        self.plan_steps = tuple(plan_steps)
        #: Records each prompt kind, so tests can assert the stages ran.
        self.calls = calls if calls is not None else []
        self._written: set[str] = set()

    async def chat(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[ToolSpec] = ()
    ) -> LLMResponse:
        prompt = "\n".join(m.content or "" for m in messages)

        if _PLAN_MARKER in prompt:
            self.calls.append("plan")
            return LLMResponse(
                content=json.dumps(
                    {
                        "mode": "modify",
                        "strategy": "scripted",
                        "steps": [
                            {"description": text, "kind": "analysis"}
                            for text in self.plan_steps
                        ],
                        "test_files": [],
                        "risks": [],
                    },
                    ensure_ascii=False,
                ),
                finish_reason="stop",
                model=self.name,
            )

        # Anything else is the agent loop. Write each pending edit once, then
        # answer, which is what lets the loop finish instead of spinning.
        available = {spec.name for spec in tools}
        for path, content in self.edits.items():
            if path in self._written:
                continue
            if "sandbox_write_file" not in available:
                continue
            self._written.add(path)
            self.calls.append(f"write:{path}")
            return LLMResponse(
                content=None,
                tool_calls=(
                    ToolCall(
                        id=f"call-{len(self._written)}",
                        name="sandbox_write_file",
                        arguments={"path": path, "content": content},
                    ),
                ),
                finish_reason="tool_use",
                model=self.name,
            )

        self.calls.append("answer")
        return LLMResponse(
            content="Implemented the requirement.",
            finish_reason="stop",
            model=self.name,
        )


def plan_for(prompt: str) -> dict[str, Any] | None:
    """Parse the structured plan out of a planner prompt, for assertions."""
    match = re.search(r'"requirement":\s*"([^"]*)"', prompt)
    return {"requirement": match.group(1)} if match else None


__all__ = ["FakeModel", "plan_for"]

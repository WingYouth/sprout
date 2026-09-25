"""MCP prompt adapter: remote prompts become PromptTemplates."""

from __future__ import annotations

from typing import Any

from Sprout.registry.prompts import PromptArgument, PromptTemplate


def to_prompt_template(prompt: Any) -> PromptTemplate:
    arguments = tuple(
        PromptArgument(
            name=getattr(argument, "name", ""),
            description=getattr(argument, "description", "") or "",
            required=bool(getattr(argument, "required", False)),
        )
        for argument in getattr(prompt, "arguments", None) or ()
    )
    template = ", ".join(
        "{" + argument.name + "}" for argument in arguments
    ) or "{input}"
    return PromptTemplate(
        name=prompt.name,
        template=template,
        description=prompt.description or "",
        arguments=arguments,
    )

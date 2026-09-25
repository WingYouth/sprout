"""Interactive intent-recognition runner.

Run:
    uv run python src/Sprout/tests/intent_recognition_repl.py

Type one sentence per line. Empty line or Ctrl-D exits.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from Sprout.config.loader import load_settings
from Sprout.message.models import Message
from Sprout.runtime.factory import create_runtime
from Sprout.runtime.lifecycle import managed
from Sprout.runtime.runtime import _INTENT_EVENTS


async def _recognize(runtime, text: str) -> dict[str, object]:
    session = await runtime.create_session("intent-repl")
    message = Message(text, channel="intent-repl", user_id="intent-repl", session_id=session.id)
    context = await runtime._contexts.build(  # noqa: SLF001 - this is a manual test runner
        message=message,
        session=session,
        tools=runtime.tools.list(),
        skills=runtime.skills.list(),
    )
    classification = await runtime._classify_intent_with_llm(message, context)  # noqa: SLF001
    intent = str(classification.get("intent") or "conversation")
    trigger_event = str(
        classification.get("trigger_event")
        or _INTENT_EVENTS.get(intent, f"intent.{intent}.requested")
    )
    confidence = classification.get("confidence", 0.0)
    similar_context = await runtime._similar_context_for_intent(message)  # noqa: SLF001
    return {
        "input": text,
        "intent": intent,
        "event": trigger_event,
        "confidence": confidence,
        "reason": classification.get("reason", ""),
        "similar_context": similar_context,
    }


async def _run(*, config: str | None, json_only: bool) -> None:
    settings = load_settings(config)
    runtime = create_runtime(settings)
    async with managed(runtime):
        if not json_only:
            print("intent repl started. Type a sentence, empty line to exit.")
        while True:
            try:
                text = await asyncio.to_thread(input, "input> " if not json_only else "")
            except EOFError:
                break
            text = text.strip()
            if not text:
                break
            output = await _recognize(runtime, text)
            if json_only:
                print(json.dumps(output, ensure_ascii=False))
            else:
                print(f"output> {json.dumps(output, ensure_ascii=False, indent=2)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None, help="Path to sprout.toml")
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Print one compact JSON object per input line.",
    )
    args = parser.parse_args()
    asyncio.run(_run(config=args.config, json_only=args.jsonl))


if __name__ == "__main__":
    main()

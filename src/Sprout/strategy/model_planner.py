"""LLM-backed strategy planning over verified project evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from Sprout.llm.client import invoke_model
from Sprout.llm.messages import LLMMessage
from Sprout.strategy.models import ChangeMode, PlanStep, StepKind, StrategyPlan

if TYPE_CHECKING:
    from Sprout.llm.base import ModelProvider

#: Per-bucket evidence cap for the prompt. The full report is unbounded.
_MAX_EVIDENCE = 20


class ModelStrategyPlanner:
    """Ask the configured natural-language model to make the strategy decision."""

    async def refine(
        self,
        plan: StrategyPlan,
        model: ModelProvider,
    ) -> StrategyPlan:
        prompt = self._prompt(plan)
        response = await invoke_model(
            model,
            (LLMMessage.system(self._system_prompt()), LLMMessage.user(prompt)),
        )
        data = self._parse_json(response.text)
        if data is None:
            return replace(
                plan,
                model_strategy="模型未返回可解析的战略 JSON，已保留证据分析结果。",
                model_name=getattr(model, "model", getattr(model, "name", "unknown")),
            )
        return self._merge(plan, data, getattr(model, "model", getattr(model, "name", "unknown")))

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是 Sprout 的软件演化战略规划器。只能基于用户需求和项目证据制定战略，"
            "不能假设不存在的接口或数据库。需求模糊时也必须给出最可能的架构落点、"
            "第一版实施路径和待确认问题，不能只返回 unknown 或要求用户重新描述。"
            "必须只返回 JSON，不要 Markdown。"
        )

    @staticmethod
    def _prompt(plan: StrategyPlan) -> str:
        return json.dumps(
            {
                "requirement": plan.requirement.text,
                "source": plan.requirement.source.value,
                # Only the strongest evidence, capped: a full scan of a real
                # project is ~1000 entries and made this prompt ~68k tokens.
                "evidence": {
                    "interfaces": list(plan.impact.interfaces[:_MAX_EVIDENCE]),
                    "databases": list(plan.impact.databases[:_MAX_EVIDENCE]),
                    "tests": list(plan.impact.tests[:_MAX_EVIDENCE]),
                    "related_code": list(plan.impact.related_code[:_MAX_EVIDENCE]),
                    "top_items": [
                        {"path": item.path, "category": item.category,
                         "reason": item.reason, "confidence": item.confidence}
                        for item in plan.impact.top_items(_MAX_EVIDENCE)
                    ],
                },
                "current_local_plan": {
                    "mode": plan.mode.value,
                    "test_files": list(plan.test_files),
                },
                "output_schema": {
                    "mode": "add|modify|mixed|unknown",
                    "strategy": "简明战略说明",
                    "steps": [
                        {
                            "description": "该步骤要做什么",
                            "kind": "analysis|edit|test|other",
                            "target_paths": ["该步骤涉及的文件路径"],
                            "acceptance": "如何判断该步骤完成",
                        }
                    ],
                    "test_files": ["测试文件路径"],
                    "risks": ["风险或需要人工确认的事项"],
                    "questions": ["仍需确认的问题"],
                },
                "step_kind_rules": {
                    "analysis": "只读调查，不改文件；同类步骤会被并行执行",
                    "edit": "写或改代码",
                    "test": "新增或更新测试",
                    "other": "无法归类时使用",
                },
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any] | None:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _merge(plan: StrategyPlan, data: dict[str, Any], model_name: str) -> StrategyPlan:
        mode_value = data.get("mode", plan.mode.value)
        try:
            mode = ChangeMode(str(mode_value))
        except ValueError:
            mode = plan.mode
        if mode is ChangeMode.UNKNOWN and plan.mode is not ChangeMode.UNKNOWN:
            mode = plan.mode
        parsed_steps = ModelStrategyPlanner._steps(data.get("steps"))
        # ``implementation_steps`` stays the human-readable projection, so
        # existing consumers (CLI, to_dict, strategy_tool) are unaffected.
        steps = (
            tuple(step.description for step in parsed_steps)
            or ModelStrategyPlanner._strings(data.get("steps"))
            or plan.implementation_steps
        )
        tests = ModelStrategyPlanner._strings(data.get("test_files")) or plan.test_files
        risks = ModelStrategyPlanner._strings(data.get("risks")) or plan.risks
        questions = ModelStrategyPlanner._strings(data.get("questions"))
        if questions:
            risks = (*risks, *(f"待确认: {question}" for question in questions))
        strategy = str(data.get("strategy", "")).strip()
        return replace(
            plan,
            mode=mode,
            implementation_steps=steps,
            steps=parsed_steps or plan.steps,
            test_files=tests,
            risks=risks,
            model_strategy=strategy,
            model_name=model_name,
        )

    @staticmethod
    def _steps(value: object) -> tuple[PlanStep, ...]:
        """Parse the structured ``steps`` array.

        Accepts a plain string array too (the pre-``PlanStep`` shape, and what
        a model may still emit), degrading each entry to ``kind=OTHER`` with no
        target paths rather than dropping it.
        """
        if not isinstance(value, list):
            return ()
        parsed: list[PlanStep] = []
        for entry in value:
            if isinstance(entry, str):
                text = entry.strip()
                if text:
                    parsed.append(PlanStep(description=text))
                continue
            if not isinstance(entry, dict):
                continue
            description = str(entry.get("description", "")).strip()
            if not description:
                continue
            try:
                kind = StepKind(str(entry.get("kind", "")).strip().lower())
            except ValueError:
                kind = StepKind.OTHER
            parsed.append(
                PlanStep(
                    description=description,
                    kind=kind,
                    target_paths=ModelStrategyPlanner._strings(entry.get("target_paths")),
                    acceptance=str(entry.get("acceptance", "")).strip(),
                )
            )
        return tuple(parsed)

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

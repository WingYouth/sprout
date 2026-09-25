"""One selectable approval menu shared by interactive CLI workflows."""

from __future__ import annotations

import sys

import questionary
from prompt_toolkit.styles import Style

from Sprout.cli.i18n import L

APPROVE = "approve"
APPROVE_SIMILAR = "approve_similar"
REJECT = "reject"
DEFER = "defer"
QUIT = "quit"
APPROVE_WITH_FAILURES = "approve_with_failures"


def approval_select_style() -> Style:
    return Style.from_dict(
        {
            "qmark": "fg:#a855f7 bold",
            "question": "bold",
            "answer": "fg:#a855f7 bold",
            "pointer": "fg:#a855f7 bold",
            "highlighted": "fg:#a855f7 bold",
            "instruction": "fg:ansidefault",
            "text": "fg:ansidefault",
        }
    )


def _choices(
    *,
    allow_similar: bool,
    allow_quit: bool,
    allow_failures: bool = False,
    yes_no: bool = False,
) -> list[questionary.Choice]:
    choices: list[questionary.Choice] = []
    if yes_no:
        choices.append(
            questionary.Choice(
                L("是", "Yes"),
                APPROVE_WITH_FAILURES if allow_failures else APPROVE,
            )
        )
    elif allow_failures:
        choices.append(
            questionary.Choice(
                L("接受验证失败并融入", "Accept verification failures and apply"),
                APPROVE_WITH_FAILURES,
            )
        )
    else:
        choices.append(
            questionary.Choice(
                L("批准 / 继续", "Approve / continue"), APPROVE
            )
        )
    if allow_similar and not allow_failures:
        choices.append(
            questionary.Choice(
                L("批准同类操作", "Approve similar operations"), APPROVE_SIMILAR
            )
        )
    choices.append(
        questionary.Choice(L("否", "No"), REJECT)
        if yes_no
        else questionary.Choice(L("拒绝", "Reject"), REJECT)
    )
    if not yes_no:
        choices.append(questionary.Choice(L("稍后处理", "Decide later"), DEFER))
    if allow_quit:
        choices.append(questionary.Choice(L("退出当前运行", "Stop this run"), QUIT))
    return choices


async def ask_approval(
    message: str,
    *,
    allow_similar: bool = False,
    allow_quit: bool = False,
    allow_failures: bool = False,
    yes_no: bool = False,
) -> str | None:
    """Ask an approval question asynchronously; cancellation means defer."""
    if not sys.stdin.isatty():
        return None
    try:
        return await questionary.select(
            message,
            choices=_choices(
                allow_similar=allow_similar,
                allow_quit=allow_quit,
                allow_failures=allow_failures,
                yes_no=yes_no,
            ),
            style=approval_select_style(),
        ).ask_async()
    except (KeyboardInterrupt, EOFError):
        return None


def ask_approval_sync(
    message: str,
    *,
    allow_similar: bool = False,
    allow_quit: bool = False,
) -> str | None:
    """Synchronous counterpart used by the autonomous ``sprout run`` loop."""
    if not sys.stdin.isatty():
        return None
    try:
        return questionary.select(
            message,
            choices=_choices(
                allow_similar=allow_similar, allow_quit=allow_quit
            ),
            style=approval_select_style(),
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return None

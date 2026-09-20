"""Guided repair: walk through the report's issues and apply remedies one by one.

Nothing here runs without the user's confirmation (or an explicit ``--yes``).
Commands run in the foreground with the user's real environment so ``sudo`` can
prompt for a password. After each item the affected module is re-run and the
check re-evaluated, so the user sees whether the remedy actually worked.

``ask`` and ``runner`` are injectable so tests never prompt or spawn processes.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from gamedoctor.core.context import Context
from gamedoctor.core.doctor import run
from gamedoctor.core.report import Report
from gamedoctor.core.result import Check, Severity
from gamedoctor.platform.solutions import Step
from gamedoctor.reporters.console import GLYPH, STYLE, _render_check

Asker = Callable[[str, list[str], str], str]
Runner = Callable[[str], int]

# Remedies whose effect only shows after a re-login, replug or reboot.
_DEFERRED_HINTS = ("udev", "modules-load", "modprobe", "usermod", "steam-devices", "game-devices")


class UnknownCheckError(ValueError):
    pass


@dataclass
class FixItem:
    module: str
    check: Check

    @property
    def id(self) -> str:
        return self.check.id

    @property
    def runnable(self) -> bool:
        return bool(self.check.runnable_steps)


@dataclass
class FixSummary:
    fixed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    quit: bool = False

    @property
    def remaining(self) -> list[str]:
        return self.failing + self.skipped + self.manual

    @property
    def exit_code(self) -> int:
        return 0 if not self.remaining else 1


def running_as_root() -> bool:
    return os.geteuid() == 0


def plan(report: Report, *, ids: list[str] | None = None, include_notes: bool = False) -> list[FixItem]:
    """Select the checks ``gamedoctor fix`` should walk through.

    By default: every issue (WARNING and above) that has at least one remedy step, most
    severe first. ``include_notes`` adds INFO checks. ``ids`` restricts the selection to
    those check ids and raises :class:`UnknownCheckError` for ids the report does not know.
    """
    by_id: dict[str, FixItem] = {}
    for m in report.modules:
        for c in m.checks:
            by_id[c.id] = FixItem(m.name, c)

    if ids:
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise UnknownCheckError(", ".join(unknown))
        chosen = [by_id[i] for i in dict.fromkeys(ids)]
        return [it for it in chosen if it.check.severity != Severity.PASS]

    floor = Severity.INFO.rank if include_notes else Severity.WARNING.rank
    items = [it for it in by_id.values() if it.check.severity.rank >= floor and it.check.steps]
    return sorted(items, key=lambda it: -it.check.severity.rank)


def run_step(command: str) -> int:
    """Run one remedy in the foreground, inheriting the terminal (so sudo can prompt)."""
    try:
        return subprocess.run(command, shell=True).returncode
    except KeyboardInterrupt:
        return 130


def default_ask(prompt: str, choices: list[str], default: str) -> str:
    return Prompt.ask(prompt, choices=choices, default=default, show_choices=False)


def _describe(item: FixItem, console: Console) -> None:
    for line in _render_check(item.check, show_details=False):
        console.print(line, highlight=False)
    if item.check.explanation:
        console.print(f"    [dim]{escape(item.check.explanation)}[/]", highlight=False, soft_wrap=True)
    if item.check.recommendation:
        console.print(f"    {escape(item.check.recommendation)}", highlight=False, soft_wrap=True)
    console.print(f"    [dim]id: {escape(item.id)}  module: {escape(item.module)}[/]", highlight=False)


def print_plan(items: list[FixItem], console: Console) -> None:
    if not items:
        console.print("[green]Nothing to fix: no actionable issues found.[/]")
        return
    console.print(f"[bold]{len(items)} item(s) to walk through[/]\n")
    for item in items:
        _describe(item, console)
        for step in item.check.steps:
            for line in step.render():
                style = "bold" if step.runnable else "dim"
                console.print(f"      [{style}]{escape(line)}[/]", highlight=False)
        if not item.runnable:
            console.print("      [dim](manual step, nothing to run)[/]")
        console.print()


def _choose_option(step: Step, ask: Asker, console: Console) -> str | None:
    """Show the alternatives and return the chosen command, or None for skip/quit."""
    if step.note:
        console.print(f"    [dim]{escape(step.note)}[/]", highlight=False)
    for n, cmd in enumerate(step.options, 1):
        console.print(f"      [bold]{n}[/]) [bold]{escape(cmd)}[/]", highlight=False)
    choices = [str(n) for n in range(1, len(step.options) + 1)] + ["s", "q"]
    answer = ask("    Which one? [number/s(kip)/q(uit)]", choices, "s")
    if answer in ("s", "q"):
        return answer
    return step.options[int(answer) - 1]


def _recheck(item: FixItem, ctx_factory: Callable[[], Context]) -> Check | None:
    ctx = ctx_factory()
    fresh = run(ctx, [item.module], redact=False)
    for c in fresh.checks:
        if c.id == item.id:
            return c
    return None


def _may_need_relogin(item: FixItem, ran: list[str]) -> bool:
    haystack = " ".join(ran + [item.id]).lower()
    return any(h in haystack for h in _DEFERRED_HINTS)


def fix(
    report: Report,
    ctx_factory: Callable[[], Context],
    *,
    items: list[FixItem],
    ask: Asker = default_ask,
    runner: Runner = run_step,
    console: Console | None = None,
    yes: bool = False,
) -> FixSummary:
    console = console or Console(highlight=False)
    summary = FixSummary()

    if not items:
        print_plan(items, console)
        return summary

    for index, item in enumerate(items, 1):
        console.print(f"[bold]\\[{index}/{len(items)}][/]", highlight=False)
        _describe(item, console)
        console.print()

        if not item.runnable:
            for step in item.check.steps:
                for line in step.render():
                    console.print(f"      [dim]{escape(line)}[/]", highlight=False)
            console.print("    [dim]Manual step: nothing to run here.[/]\n")
            summary.manual.append(item.id)
            continue

        ran: list[str] = []
        skipped = False
        for step in item.check.steps:
            if not step.runnable:
                for line in step.render():
                    console.print(f"      [dim]{escape(line)}[/]", highlight=False)
                continue

            if step.options:
                if yes:
                    console.print("    [yellow]Several alternatives; --yes never picks one for you. Skipped.[/]")
                    skipped = True
                    break
                answer = _choose_option(step, ask, console)
                if answer == "q":
                    summary.quit = True
                    break
                if answer == "s" or answer is None:
                    skipped = True
                    break
                command = answer
            else:
                command = step.run
                console.print(f"      [bold]{escape(command)}[/]" + (f"   [dim]# {escape(step.note)}[/]" if step.note else ""), highlight=False)
                if step.needs_root:
                    console.print("      [dim]needs administrator rights (sudo will ask for your password)[/]")
                if not yes:
                    answer = ask("    Run this command? [y/N/s(kip)/q(uit)]", ["y", "n", "s", "q"], "n")
                    if answer == "q":
                        summary.quit = True
                        break
                    if answer in ("n", "s"):
                        skipped = True
                        break

            console.print(f"    [dim]$ {escape(command)}[/]", highlight=False)
            code = runner(command)
            ran.append(command)
            if code != 0:
                console.print(f"    [red]Command exited with status {code}.[/]")
            else:
                console.print("    [green]Done.[/]")

        if summary.quit:
            summary.skipped.append(item.id)
            summary.skipped += [it.id for it in items[index:]]
            console.print("\n[dim]Stopped. Remaining items were not touched.[/]")
            break

        if not ran:
            summary.skipped.append(item.id)
            console.print("    [dim]Skipped.[/]\n")
            continue

        after = _recheck(item, ctx_factory)
        if after is None or after.severity == Severity.PASS:
            console.print(f"    [green]{GLYPH[Severity.PASS]} Re-checked: {escape(item.id)} now passes.[/]\n")
            summary.fixed.append(item.id)
        else:
            style = STYLE[after.severity]
            console.print(
                f"    [{style}]{GLYPH[after.severity]} Re-checked: {escape(item.id)} is still "
                f"{after.severity.value}: {escape(after.title)}[/]",
                highlight=False,
            )
            if _may_need_relogin(item, ran):
                console.print("    [dim]This remedy may need a re-login, replug or reboot to take effect.[/]")
            console.print()
            summary.failing.append(item.id)

    _print_summary(summary, console)
    return summary


def _print_summary(summary: FixSummary, console: Console) -> None:
    console.print("[bold]Summary[/]")
    rows = [
        (summary.fixed, "fixed", "green"),
        (summary.skipped, "skipped", "dim"),
        (summary.failing, "still failing", "yellow"),
        (summary.manual, "manual only", "cyan"),
    ]
    for ids, label, style in rows:
        if ids:
            console.print(f"  [{style}]{len(ids):>3} {label}[/]  [dim]{escape(', '.join(ids))}[/]", highlight=False)
    if not summary.remaining:
        console.print("  [green]Everything selected is resolved.[/]")

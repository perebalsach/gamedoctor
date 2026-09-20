"""Human-readable rendering. One renderer produces Rich markup; the plain-text
report is the same content with markup stripped, so both always agree."""

from __future__ import annotations

import textwrap

from rich.console import Console
from rich.markup import escape
from rich.text import Text

from gamedoctor.core.report import Report
from gamedoctor.core.result import Check, Fact, ModuleResult, Severity

GLYPH = {
    Severity.PASS: "✓",
    Severity.INFO: "i",
    Severity.WARNING: "⚠",
    Severity.ERROR: "✗",
    Severity.CRITICAL: "!!",
}
STYLE = {
    Severity.PASS: "green",
    Severity.INFO: "cyan",
    Severity.WARNING: "yellow",
    Severity.ERROR: "red",
    Severity.CRITICAL: "bold red",
}
WIDTH = 72


def _glyph(fact: Fact) -> str:
    if fact.status is not None:
        return f"[{STYLE[fact.status]}]{GLYPH[fact.status]}[/]"
    if fact.absent:
        return "[dim]-[/]"
    return " "


def _render_module(m: ModuleResult) -> list[str]:
    lines = [f"[bold]{escape(m.title)}[/]"]
    if not m.facts:
        lines.append("  [dim]nothing to report[/]")
        return lines
    width = max(12, min(24, max(len(f.label) for f in m.facts) + 2))
    for f in m.facts:
        value = escape(f.value)
        if f.absent:
            value = f"[dim]{value}[/]"
        lines.append(f"  {escape(f.label):<{width}} {_glyph(f)} {value}")
    return lines


def _render_check(c: Check, *, show_details: bool) -> list[str]:
    style = STYLE[c.severity]
    lines = [f"  [{style}]{GLYPH[c.severity]}[/] [{style}]{escape(c.title)}[/]"]
    if not show_details:
        return lines
    if c.explanation:
        lines.append("")
        lines += ["    " + escape(l) for l in textwrap.wrap(c.explanation, WIDTH - 4)]
    if c.recommendation:
        lines.append("")
        lines += ["    " + escape(l) for l in textwrap.wrap(c.recommendation, WIDTH - 4)]
    if c.steps:
        lines.append("")
        lines.append("    [dim]Try:[/]")
        for step in c.steps:
            lines += [f"      [bold]{escape(line)}[/]" for line in step.render()]
    return lines


def render_lines(report: Report) -> list[str]:
    lines: list[str] = [f"[bold]Linux Game Doctor[/] [dim]{escape(report.version)}[/]"]
    if not report.privacy:
        lines.append("[yellow]Debug mode: paths and user names are NOT redacted in this output.[/]")
    lines.append("")
    for m in report.modules:
        lines += _render_module(m)
        lines.append("")

    issues = report.issues
    if issues:
        lines.append("[bold]Potential issues[/]")
        lines.append("")
        for c in issues:
            lines += _render_check(c, show_details=True)
            lines.append("")

    notes = report.notes
    if notes:
        lines.append("[bold]Notes[/]")
        lines.append("")
        for c in notes:
            lines += _render_check(c, show_details=True)
            lines.append("")

    s = report.summary
    lines.append("[bold]Overall status[/]")
    lines.append("")
    rows = [
        (s["pass"], "checks passed", "green"),
        (s["info"], "notes", "cyan"),
        (s["warning"], "warnings", "yellow"),
        (s["error"], "errors", "red"),
        (s["critical"], "critical", "bold red"),
    ]
    for count, label, style in rows:
        colour = style if count else "dim"
        lines.append(f"  [{colour}]{count:>3} {label}[/]")
    if report.debug_notes:
        lines.append("")
        lines.append("[bold]Debug traces[/]")
        for note in report.debug_notes:
            lines += ["  " + escape(l) for l in note.rstrip().splitlines()]
    return lines


def print_report(report: Report, console: Console | None = None) -> None:
    console = console or Console(highlight=False)
    for line in render_lines(report):
        console.print(line, highlight=False, soft_wrap=True)


def render_text(report: Report) -> str:
    plain = [Text.from_markup(line).plain for line in render_lines(report)]
    header = [
        f"Generated {report.generated_at} by gamedoctor {report.version}",
        "Personal paths are redacted." if report.privacy else "Debug report: paths are not redacted.",
        "",
    ]
    return "\n".join(header + plain) + "\n"

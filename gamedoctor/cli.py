"""``gamedoctor`` command line entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
import typer.core
from rich.console import Console

from gamedoctor import __version__
from gamedoctor.core import fixer
from gamedoctor.core.context import Context
from gamedoctor.core.doctor import UnknownModuleError, module_names, run
from gamedoctor.reporters.console import print_report, render_text
from gamedoctor.reporters.json import render_json


class _DefaultGroup(typer.core.TyperGroup):
    """Route ``gamedoctor [MODULES] [OPTIONS]`` to the ``check`` command.

    Only a registered sub-command name (or a top-level help flag) as the first argument
    selects a different command, so ``gamedoctor vulkan --json`` keeps working.
    """

    default_command = "check"

    def parse_args(self, ctx: typer.Context, args: list[str]) -> list[str]:
        if not args or (args[0] not in self.list_commands(ctx) and args[0] not in ("-h", "--help")):
            args = [self.default_command, *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=_DefaultGroup,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Linux Game Doctor collects the information that matters for gaming on this machine, "
        "detects common configuration problems and explains them. It never changes anything on "
        "its own. `gamedoctor fix` can apply remedies, but only the ones you confirm one by one."
    ),
)

DEFAULT_REPORT = "gamedoctor-report.txt"
DEFAULT_JSON = "gamedoctor-report.json"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"gamedoctor {__version__}")
        raise typer.Exit()


@app.command("check")
def check(
    modules: Annotated[
        Optional[list[str]],
        typer.Argument(help="Only run these modules (default: all). See --list-modules.", show_default=False),
    ] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Print the report as JSON to stdout instead of text.")] = False,
    report: Annotated[bool, typer.Option("--report", help=f"Also save a plain-text report to {DEFAULT_REPORT}.")] = False,
    output: Annotated[
        Optional[Path],
        typer.Option("-o", "--output", help="File to write when using --report or --json.", show_default=False),
    ] = None,
    debug: Annotated[bool, typer.Option("--debug", help="Do not redact paths/user names; include internal tracebacks.")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable coloured output.")] = False,
    list_modules: Annotated[bool, typer.Option("--list-modules", help="List available diagnostic modules and exit.")] = False,
    version: Annotated[
        Optional[bool],
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit."),
    ] = None,
) -> None:
    """Run the default diagnostic suite (or only the given MODULES)."""
    if list_modules:
        for name in module_names():
            typer.echo(name)
        raise typer.Exit()

    if debug:
        Console(stderr=True).print(
            "[yellow]--debug: the report will contain your home directory path and user name. "
            "Review it before sharing.[/]",
            highlight=False,
        )

    ctx = Context(debug=debug)
    try:
        result = run(ctx, modules)
    except UnknownModuleError as exc:
        typer.echo(f"Unknown module '{exc}'. Available: {', '.join(module_names())}", err=True)
        raise typer.Exit(code=2)

    if json_out:
        text = render_json(result)
        if output:
            output.write_text(text)
            typer.echo(f"Report saved: {output}", err=True)
        else:
            sys.stdout.write(text)
        return

    console = Console(highlight=False, no_color=no_color or None, force_terminal=None if not no_color else False)
    print_report(result, console)

    if report:
        target = output or Path(DEFAULT_REPORT)
        target.write_text(render_text(result))
        console.print(f"\n[bold]Report saved:[/]\n  {target}")


@app.command("fix")
def fix(
    check_ids: Annotated[
        Optional[list[str]],
        typer.Argument(help="Only walk through these check ids (default: every issue).", show_default=False),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Run every remedy without asking. Steps with alternatives are skipped.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be proposed and exit without running anything.")] = False,
    include_notes: Annotated[bool, typer.Option("--all", help="Also offer remedies for INFO notes, not only issues.")] = False,
    debug: Annotated[bool, typer.Option("--debug", help="Include internal tracebacks.")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable coloured output.")] = False,
) -> None:
    """Walk through the detected issues and apply their remedies, one confirmation at a time.

    Each remedy is shown with the exact command before anything runs. Commands run in the foreground with your normal environment (sudo may ask for your password). After each item the check is re-run so you can see whether it now passes.
    """
    console = Console(highlight=False, no_color=no_color or None, force_terminal=None if not no_color else False)
    if fixer.running_as_root():
        console.print(
            "[red]Refusing to run as root.[/] Run `gamedoctor fix` as your normal user: remedies use "
            "sudo where needed, and user services (systemctl --user) must target your own session."
        )
        raise typer.Exit(code=2)

    ctx = Context(debug=debug)
    report = run(ctx, redact=False)
    try:
        items = fixer.plan(report, ids=check_ids, include_notes=include_notes)
    except fixer.UnknownCheckError as exc:
        known = ", ".join(sorted(c.id for c in report.checks))
        typer.echo(f"Unknown check id(s): {exc}. Known ids on this machine: {known}", err=True)
        raise typer.Exit(code=2)

    if dry_run:
        fixer.print_plan(items, console)
        raise typer.Exit(code=0 if not items else 1)

    if not yes and not sys.stdin.isatty():
        fixer.print_plan(items, console)
        if items:
            console.print("[yellow]Standard input is not a terminal; cannot ask for confirmation. Use --yes to run unattended.[/]")
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)

    summary = fixer.fix(report, lambda: Context(debug=debug), items=items, console=console, yes=yes)
    raise typer.Exit(code=summary.exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

"""The engine: resolves module dependencies, runs them, redacts, aggregates."""

from __future__ import annotations

import dataclasses
import traceback
from typing import Iterable

from gamedoctor.core.context import Context
from gamedoctor.core.privacy import Redactor
from gamedoctor.core.report import Report
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.diagnostics import ALL_DIAGNOSTICS, Diagnostic


class UnknownModuleError(ValueError):
    pass


def module_names() -> list[str]:
    return [d.name for d in ALL_DIAGNOSTICS]


def _resolve(selected: Iterable[str]) -> list[Diagnostic]:
    by_name = {d.name: d for d in ALL_DIAGNOSTICS}
    order: list[Diagnostic] = []
    seen: set[str] = set()

    def visit(name: str, chain: tuple[str, ...] = ()) -> None:
        if name in seen:
            return
        if name not in by_name:
            raise UnknownModuleError(name)
        if name in chain:
            raise RuntimeError(f"dependency cycle: {' -> '.join(chain + (name,))}")
        for dep in by_name[name].requires:
            visit(dep, chain + (name,))
        seen.add(name)
        order.append(by_name[name])

    for name in selected:
        visit(name)
    return order


def run(ctx: Context, only: Iterable[str] | None = None, *, redact: bool | None = None) -> Report:
    """Run the selected modules (default: all) and return the aggregated report.

    ``redact`` defaults to ``not ctx.debug``. ``gamedoctor fix`` passes ``False`` so the
    remedy commands keep real paths (they are executed, not shared).
    """
    if redact is None:
        redact = not ctx.debug
    wanted = list(only) if only else module_names()
    to_run = _resolve(wanted)
    results: dict[str, ModuleResult] = {}
    report = Report(privacy=redact)

    for diag in to_run:
        try:
            results[diag.name] = diag.run(ctx)
        except Exception as exc:  # a broken check must never take the whole report down
            res = ModuleResult(diag.name, diag.title)
            res.check(
                f"{diag.name}.internal-error",
                Severity.WARNING,
                f"The {diag.title} diagnostic failed to run",
                f"gamedoctor hit an internal error ({type(exc).__name__}: {exc}). "
                "Other modules are unaffected. Please report this with `gamedoctor --debug` output.",
            )
            if ctx.debug:
                report.debug_notes.append(traceback.format_exc())
            results[diag.name] = res

    # Present in canonical order, but only what was asked for.
    for diag in ALL_DIAGNOSTICS:
        if diag.name in wanted and diag.name in results:
            report.modules.append(results[diag.name])

    if report.privacy:
        _redact(report, Redactor(ctx.home, ctx.uid, ctx.env.get("USER")))
    return report


def _redact(report: Report, redactor: Redactor) -> None:
    for m in report.modules:
        for f in m.facts:
            f.value = redactor.redact(f.value)
            f.label = redactor.redact(f.label)
        for c in m.checks:
            c.title = redactor.redact(c.title)
            c.explanation = redactor.redact(c.explanation)
            c.recommendation = redactor.redact(c.recommendation)
            c.steps = [
                dataclasses.replace(
                    s,
                    run=redactor.redact(s.run),
                    note=redactor.redact(s.note),
                    options=tuple(redactor.redact(o) for o in s.options),
                )
                for s in c.steps
            ]

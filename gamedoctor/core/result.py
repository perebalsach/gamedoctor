"""Standardized result types shared by every diagnostic module."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from gamedoctor.platform.solutions import Step


class Severity(str, Enum):
    PASS = "pass"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _ORDER.index(self)

    @property
    def is_problem(self) -> bool:
        return self.rank >= Severity.WARNING.rank


_ORDER = [Severity.PASS, Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL]


@dataclass
class Fact:
    """One line of collected information, e.g. ``Kernel   6.17.2``.

    ``status`` adds a glyph (✓ ⚠ ✗). ``absent`` marks an optional component that is
    simply not installed; it is rendered neutrally, never as a problem.
    """

    label: str
    value: str
    status: Severity | None = None
    absent: bool = False


@dataclass
class Check:
    """One diagnostic verdict.

    ``PASS`` checks are counted in the summary but not listed as issues. Anything at
    ``WARNING`` or above is shown under "Potential issues" with its explanation.
    """

    id: str
    severity: Severity
    title: str
    explanation: str = ""
    recommendation: str = ""
    steps: list[Step] = field(default_factory=list)

    @property
    def runnable_steps(self) -> list[Step]:
        return [s for s in self.steps if s.runnable]


@dataclass
class ModuleResult:
    name: str
    title: str
    facts: list[Fact] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    def fact(
        self,
        label: str,
        value: str,
        status: Severity | None = None,
        *,
        absent: bool = False,
    ) -> Fact:
        f = Fact(label, value, status, absent)
        self.facts.append(f)
        return f

    def check(
        self,
        id: str,
        severity: Severity,
        title: str,
        explanation: str = "",
        recommendation: str = "",
        steps: list[Step] | None = None,
    ) -> Check:
        c = Check(id, severity, title, explanation, recommendation, list(steps or []))
        self.checks.append(c)
        return c

    def ok(self, id: str, title: str) -> Check:
        return self.check(id, Severity.PASS, title)

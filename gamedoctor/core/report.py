"""The aggregated report produced by one gamedoctor run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from gamedoctor import __version__
from gamedoctor.core.result import Check, ModuleResult, Severity


@dataclass
class Report:
    modules: list[ModuleResult] = field(default_factory=list)
    version: str = __version__
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    privacy: bool = True
    debug_notes: list[str] = field(default_factory=list)

    @property
    def checks(self) -> list[Check]:
        return [c for m in self.modules for c in m.checks]

    def checks_at(self, *severities: Severity) -> list[Check]:
        return [c for c in self.checks if c.severity in severities]

    @property
    def issues(self) -> list[Check]:
        """WARNING and above, most severe first (stable within a level)."""
        return sorted((c for c in self.checks if c.severity.is_problem), key=lambda c: -c.severity.rank)

    @property
    def notes(self) -> list[Check]:
        return self.checks_at(Severity.INFO)

    @property
    def summary(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for c in self.checks:
            counts[c.severity.value] += 1
        return counts

    @property
    def worst(self) -> Severity:
        return max((c.severity for c in self.checks), key=lambda s: s.rank, default=Severity.PASS)

    def to_dict(self) -> dict:
        return {
            "tool": "gamedoctor",
            "version": self.version,
            "generated_at": self.generated_at,
            "privacy": self.privacy,
            "summary": self.summary,
            "modules": [
                {
                    "name": m.name,
                    "title": m.title,
                    "facts": [asdict(f) for f in m.facts],
                    "checks": [asdict(c) for c in m.checks],
                }
                for m in self.modules
            ],
        }

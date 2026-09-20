from __future__ import annotations

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult


class Diagnostic:
    """One diagnostic module. Subclasses set ``name``/``title`` and implement ``run``.

    ``requires`` lists modules that must run first because this one reads their
    shared results from the context (e.g. proton needs steam's library list).
    """

    name: str = ""
    title: str = ""
    requires: tuple[str, ...] = ()

    def run(self, ctx: Context) -> ModuleResult:
        raise NotImplementedError

    def result(self) -> ModuleResult:
        return ModuleResult(self.name, self.title)

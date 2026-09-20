"""``gamedoctor fix`` executor: planning, prompting, running, re-checking.

No test here spawns a process or prompts: ``ask`` and ``runner`` are injected and the
re-check engine is monkeypatched.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from gamedoctor.core import fixer
from gamedoctor.core.fixer import FixItem, UnknownCheckError, fix, plan
from gamedoctor.core.report import Report
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.platform.solutions import Step


def _report() -> Report:
    vulkan = ModuleResult("vulkan", "Vulkan")
    vulkan.ok("vulkan.loader", "fine")
    vulkan.check("vulkan.icd.32bit.AMD", Severity.ERROR, "32-bit ICD missing", steps=[Step("sudo pacman -S lib32-vulkan-radeon")])
    gpu = ModuleResult("gpu", "GPU")
    gpu.check(
        "gpu.driver",
        Severity.CRITICAL,
        "No driver",
        steps=[Step(options=("sudo pacman -S nvidia-open", "sudo pacman -S nvidia"), note="pick")],
    )
    gpu.check("gpu.nvidia.modeset", Severity.WARNING, "modeset off", steps=[Step(note="add kernel param")])
    tools = ModuleResult("tools", "Tools")
    tools.check("gamemode.32bit", Severity.INFO, "32-bit gamemode missing", steps=[Step("sudo pacman -S lib32-gamemode")])
    tools.check("steam.ui", Severity.WARNING, "Steam setting", recommendation="Toggle it in Steam")
    return Report(modules=[vulkan, gpu, tools])


def _console() -> tuple[Console, callable]:
    console = Console(record=True, width=120, force_terminal=False, no_color=True, highlight=False)
    return console, lambda: console.export_text(clear=False)


class ScriptedAsk:
    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, choices: list[str], default: str) -> str:
        self.prompts.append(prompt)
        assert self.answers, f"unexpected prompt: {prompt}"
        answer = self.answers.pop(0)
        assert answer in choices, (answer, choices)
        return answer


class RecordingRunner:
    def __init__(self, codes: dict[str, int] | None = None):
        self.codes = codes or {}
        self.ran: list[str] = []

    def __call__(self, command: str) -> int:
        self.ran.append(command)
        return self.codes.get(command, 0)


def _patch_recheck(monkeypatch, outcome: dict[str, Severity]):
    """The re-run of a module yields the check at the severity given (default PASS)."""

    def fake_run(ctx, only=None, *, redact=None):
        assert redact is False
        m = ModuleResult(only[0], only[0])
        for cid, sev in outcome.items():
            m.check(cid, sev, f"{cid} after")
        return Report(modules=[m])

    monkeypatch.setattr(fixer, "run", fake_run)


# -- plan ---------------------------------------------------------------------


def test_plan_default_selects_issues_with_steps_most_severe_first():
    items = plan(_report())
    assert [it.id for it in items] == ["gpu.driver", "vulkan.icd.32bit.AMD", "gpu.nvidia.modeset"]
    assert items[0].module == "gpu"
    # steam.ui has no steps, gamemode.32bit is INFO


def test_plan_include_notes_adds_info_checks():
    ids = [it.id for it in plan(_report(), include_notes=True)]
    assert "gamemode.32bit" in ids
    assert ids[-1] == "gamemode.32bit"


def test_plan_with_ids_filters_and_rejects_unknown():
    items = plan(_report(), ids=["gamemode.32bit", "steam.ui"])
    assert [it.id for it in items] == ["gamemode.32bit", "steam.ui"]
    assert not items[1].runnable
    assert plan(_report(), ids=["vulkan.loader"]) == []  # already passes
    with pytest.raises(UnknownCheckError, match="nope.x"):
        plan(_report(), ids=["gpu.driver", "nope.x"])


# -- fix ----------------------------------------------------------------------


def test_fix_confirms_runs_and_rechecks_pass(monkeypatch):
    report = _report()
    items = plan(report, ids=["vulkan.icd.32bit.AMD"])
    ask = ScriptedAsk("y")
    runner = RecordingRunner()
    _patch_recheck(monkeypatch, {"vulkan.icd.32bit.AMD": Severity.PASS})
    console, text = _console()
    summary = fix(report, lambda: None, items=items, ask=ask, runner=runner, console=console)
    assert runner.ran == ["sudo pacman -S lib32-vulkan-radeon"]
    assert summary.fixed == ["vulkan.icd.32bit.AMD"]
    assert summary.exit_code == 0
    assert "now passes" in text()
    assert "needs administrator rights" in text()


def test_fix_reports_still_failing_and_relogin_hint(monkeypatch):
    m = ModuleResult("controllers", "Controllers")
    m.check("controller.uinput", Severity.WARNING, "not writable", steps=[Step("sudo pacman -S game-devices-udev")])
    report = Report(modules=[m])
    _patch_recheck(monkeypatch, {"controller.uinput": Severity.WARNING})
    console, text = _console()
    summary = fix(report, lambda: None, items=plan(report), ask=ScriptedAsk("y"), runner=RecordingRunner(), console=console)
    assert summary.failing == ["controller.uinput"]
    assert summary.exit_code == 1
    assert "still warning" in text()
    assert "re-login" in text()


def test_fix_skip_and_quit(monkeypatch):
    report = _report()
    items = plan(report)  # gpu.driver (options), vulkan..., modeset (manual)
    ask = ScriptedAsk("s", "q")
    runner = RecordingRunner()
    _patch_recheck(monkeypatch, {})
    console, _ = _console()
    summary = fix(report, lambda: None, items=items, ask=ask, runner=runner, console=console)
    assert runner.ran == []
    assert summary.quit
    assert summary.skipped == ["gpu.driver", "vulkan.icd.32bit.AMD", "gpu.nvidia.modeset"]
    assert summary.fixed == [] and summary.failing == []


def test_fix_option_menu_runs_chosen_alternative(monkeypatch):
    report = _report()
    items = plan(report, ids=["gpu.driver"])
    ask = ScriptedAsk("2")
    runner = RecordingRunner()
    _patch_recheck(monkeypatch, {"gpu.driver": Severity.PASS})
    console, text = _console()
    summary = fix(report, lambda: None, items=items, ask=ask, runner=runner, console=console)
    assert runner.ran == ["sudo pacman -S nvidia"]
    assert summary.fixed == ["gpu.driver"]
    assert "1) sudo pacman -S nvidia-open" in text()
    assert "Which one?" in ask.prompts[0]


def test_fix_manual_only_item_runs_nothing(monkeypatch):
    report = _report()
    items = plan(report, ids=["gpu.nvidia.modeset"])
    runner = RecordingRunner()
    _patch_recheck(monkeypatch, {})
    console, text = _console()
    summary = fix(report, lambda: None, items=items, ask=ScriptedAsk(), runner=runner, console=console)
    assert runner.ran == []
    assert summary.manual == ["gpu.nvidia.modeset"]
    assert "# add kernel param" in text()
    assert summary.exit_code == 1


def test_fix_yes_runs_without_prompting_but_never_guesses_options(monkeypatch):
    report = _report()
    items = plan(report, include_notes=True)
    runner = RecordingRunner()
    _patch_recheck(monkeypatch, {"vulkan.icd.32bit.AMD": Severity.PASS, "gamemode.32bit": Severity.PASS})
    console, text = _console()
    summary = fix(report, lambda: None, items=items, ask=ScriptedAsk(), runner=runner, console=console, yes=True)
    assert runner.ran == ["sudo pacman -S lib32-vulkan-radeon", "sudo pacman -S lib32-gamemode"]
    assert summary.skipped == ["gpu.driver"]
    assert summary.fixed == ["vulkan.icd.32bit.AMD", "gamemode.32bit"]
    assert summary.manual == ["gpu.nvidia.modeset"]
    assert "--yes never picks one" in text()


def test_fix_nonzero_exit_is_reported_and_continues(monkeypatch):
    m = ModuleResult("controllers", "Controllers")
    m.check(
        "controller.uinput",
        Severity.WARNING,
        "missing",
        steps=[Step("sudo modprobe uinput"), Step("echo uinput | sudo tee /etc/modules-load.d/uinput.conf", "permanent")],
    )
    report = Report(modules=[m])
    runner = RecordingRunner({"sudo modprobe uinput": 1})
    _patch_recheck(monkeypatch, {"controller.uinput": Severity.PASS})
    console, text = _console()
    summary = fix(report, lambda: None, items=plan(report), ask=ScriptedAsk("y", "y"), runner=runner, console=console)
    assert len(runner.ran) == 2
    assert "exited with status 1" in text()
    assert summary.fixed == ["controller.uinput"]


def test_fix_check_that_disappears_counts_as_fixed(monkeypatch):
    report = _report()
    items = plan(report, ids=["vulkan.icd.32bit.AMD"])
    _patch_recheck(monkeypatch, {})  # module re-run no longer reports the check at all
    console, _ = _console()
    summary = fix(report, lambda: None, items=items, ask=ScriptedAsk("y"), runner=RecordingRunner(), console=console)
    assert summary.fixed == ["vulkan.icd.32bit.AMD"]


def test_fix_with_nothing_to_do():
    console, text = _console()
    summary = fix(Report(), lambda: None, items=[], ask=ScriptedAsk(), runner=RecordingRunner(), console=console)
    assert summary.exit_code == 0
    assert "Nothing to fix" in text()


def test_recheck_uses_fresh_context_and_unredacted_run(monkeypatch):
    created = []
    calls = []

    def fake_run(ctx, only=None, *, redact=None):
        calls.append((ctx, only, redact))
        return Report(modules=[ModuleResult("vulkan", "Vulkan")])

    monkeypatch.setattr(fixer, "run", fake_run)
    report = _report()
    items = plan(report, ids=["vulkan.icd.32bit.AMD"])

    def factory():
        created.append(object())
        return created[-1]

    console, _ = _console()
    fix(report, factory, items=items, ask=ScriptedAsk("y"), runner=RecordingRunner(), console=console)
    assert len(created) == 1
    assert calls == [(created[0], ["vulkan"], False)]

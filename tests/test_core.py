import json
from pathlib import Path

from gamedoctor.core.doctor import _resolve, module_names
from gamedoctor.core.privacy import Redactor
from gamedoctor.core.report import Report
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.platform import detect_family, suggest
from gamedoctor.platform.solutions import SOLUTIONS, Step
from gamedoctor.reporters.console import render_text
from gamedoctor.reporters.json import render_json


def test_redactor_replaces_home_and_runtime_dir():
    red = Redactor(Path("/home/pere"), 1000, "pere")
    assert red.redact("/home/pere/.steam/root") == "$HOME/.steam/root"
    assert red.redact("/run/user/1000/bus") == "$XDG_RUNTIME_DIR/bus"
    assert red.redact("/mnt/games") == "/mnt/games"


def test_dependency_resolution_runs_prerequisites_first():
    order = [d.name for d in _resolve(["proton"])]
    assert order.index("steam") < order.index("proton")
    assert order.index("system") < order.index("steam")
    assert set(module_names()) >= {"system", "gpu", "vulkan", "steam", "proton", "tools", "audio", "filesystem"}


def test_report_summary_and_rendering():
    m = ModuleResult("demo", "Demo")
    m.fact("Thing", "ok", Severity.PASS)
    m.fact("Optional", "not installed", absent=True)
    m.ok("demo.ok", "Fine")
    m.check("demo.warn", Severity.WARNING, "Something is off", "Because reasons.", steps=[Step("do-this")])
    m.check("demo.note", Severity.INFO, "Just so you know")
    report = Report(modules=[m])
    assert report.summary["pass"] == 1
    assert report.summary["warning"] == 1
    assert report.worst == Severity.WARNING
    text = render_text(report)
    assert "Potential issues" in text
    assert "Something is off" in text
    assert "do-this" in text
    assert "[bold]" not in text
    data = render_json(report)
    assert '"id": "demo.warn"' in data


def test_platform_family_and_solutions():
    assert detect_family({"ID": "cachyos", "ID_LIKE": "arch"}) == "arch"
    assert detect_family({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}) == "debian"
    assert detect_family({"ID": "nobara"}) == "fedora"
    assert detect_family({"ID": "gentoo"}) == "unknown"
    assert suggest("vulkan.icd.32bit.AMD", "arch") == [Step("sudo pacman -S lib32-vulkan-radeon")]
    assert suggest("vulkan.icd.32bit.AMD", "unknown") == []
    immutable = suggest("vulkan.icd.32bit.AMD", "arch", immutable=True)
    assert immutable and not immutable[0].runnable
    assert immutable[0].render()[0].startswith("#")


def test_every_solution_is_a_well_formed_step():
    for key, families in SOLUTIONS.items():
        for family, steps in families.items():
            assert steps, (key, family)
            for step in steps:
                assert isinstance(step, Step), (key, family)
                assert step.run or step.note or step.options, (key, family)
                # Placeholders must never end up in something we would execute.
                for cmd in step.commands:
                    assert "<" not in cmd and ">" not in cmd, (key, family, cmd)
                    assert not cmd.startswith("#"), (key, family, cmd)


def test_step_rendering_and_flags():
    assert Step("sudo pacman -S foo").render() == ["sudo pacman -S foo"]
    assert Step("sudo pacman -S foo", "or bar").render() == ["sudo pacman -S foo   # or bar"]
    assert Step(note="do it by hand").render() == ["# do it by hand"]
    opt = Step(options=("sudo pacman -S a", "sudo pacman -S b"), note="pick one")
    assert opt.render() == ["# pick one", "sudo pacman -S a", "sudo pacman -S b"]
    assert opt.runnable and opt.needs_root
    assert Step("systemctl --user restart x").runnable
    assert not Step("systemctl --user restart x").needs_root
    assert not Step(note="x").runnable
    assert Step("echo u | sudo tee /etc/x").needs_root


def test_json_report_serialises_steps():
    m = ModuleResult("demo", "Demo")
    m.check("demo.warn", Severity.WARNING, "Off", steps=[Step("a", "n"), Step(options=("b", "c"))])
    data = json.loads(render_json(Report(modules=[m])))
    steps = data["modules"][0]["checks"][0]["steps"]
    assert steps == [
        {"run": "a", "note": "n", "options": []},
        {"run": "", "note": "", "options": ["b", "c"]},
    ]


def test_console_renders_steps_under_try():
    m = ModuleResult("demo", "Demo")
    m.check("demo.warn", Severity.WARNING, "Off", steps=[Step("sudo apt install x", "note"), Step(note="manual")])
    text = render_text(Report(modules=[m]))
    assert "    Try:\n      sudo apt install x   # note\n      # manual" in text

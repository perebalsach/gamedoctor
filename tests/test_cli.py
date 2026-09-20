"""Command line surface: default-command routing and the ``fix`` entry point."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from gamedoctor import cli
from gamedoctor.core import fixer
from gamedoctor.core.report import Report
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.platform.solutions import Step

runner = CliRunner()


def _canned_report(*_, **__) -> Report:
    m = ModuleResult("vulkan", "Vulkan")
    m.ok("vulkan.loader", "fine")
    m.check("vulkan.icd.32bit.AMD", Severity.ERROR, "32-bit ICD missing", steps=[Step("sudo pacman -S lib32-vulkan-radeon")])
    return Report(modules=[m])


@pytest.fixture(autouse=True)
def _not_root(monkeypatch):
    monkeypatch.setattr(fixer, "running_as_root", lambda: False)


def test_list_modules_routes_to_check():
    result = runner.invoke(cli.app, ["--list-modules"])
    assert result.exit_code == 0
    assert "vulkan" in result.output.split()


def test_module_argument_routes_to_check_with_json(monkeypatch):
    monkeypatch.setattr(cli, "run", _canned_report)
    result = runner.invoke(cli.app, ["vulkan", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    steps = [c["steps"] for m in data["modules"] for c in m["checks"]]
    assert steps == [[], [{"run": "sudo pacman -S lib32-vulkan-radeon", "note": "", "options": []}]]


def test_explicit_check_command_still_works():
    result = runner.invoke(cli.app, ["check", "--list-modules"])
    assert result.exit_code == 0
    assert "system" in result.output.split()


def test_unknown_module_exit_code_2():
    result = runner.invoke(cli.app, ["nosuchmodule"])
    assert result.exit_code == 2
    assert "Unknown module" in result.output


def test_top_level_help_lists_both_commands():
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output and "fix" in result.output


def test_fix_dry_run_lists_plan(monkeypatch):
    monkeypatch.setattr(cli, "run", _canned_report)
    result = runner.invoke(cli.app, ["fix", "--dry-run", "--no-color"])
    assert result.exit_code == 1
    assert "vulkan.icd.32bit.AMD" in result.output
    assert "sudo pacman -S lib32-vulkan-radeon" in result.output


def test_fix_unknown_check_id_exit_code_2(monkeypatch):
    monkeypatch.setattr(cli, "run", _canned_report)
    result = runner.invoke(cli.app, ["fix", "nope.x"])
    assert result.exit_code == 2
    assert "Unknown check id" in result.output


def test_fix_refuses_root(monkeypatch):
    monkeypatch.setattr(fixer, "running_as_root", lambda: True)
    result = runner.invoke(cli.app, ["fix"])
    assert result.exit_code == 2
    assert "Refusing to run as root" in result.output


def test_fix_without_tty_prints_plan_and_exits_1(monkeypatch):
    monkeypatch.setattr(cli, "run", _canned_report)
    result = runner.invoke(cli.app, ["fix", "--no-color"])  # CliRunner stdin is never a tty
    assert result.exit_code == 1
    assert "Use --yes" in result.output


def test_fix_yes_invokes_executor(monkeypatch):
    monkeypatch.setattr(cli, "run", _canned_report)
    captured = {}

    def fake_fix(report, ctx_factory, *, items, console, yes):
        captured["ids"] = [it.id for it in items]
        captured["yes"] = yes
        return fixer.FixSummary(fixed=captured["ids"])

    monkeypatch.setattr(fixer, "fix", fake_fix)
    result = runner.invoke(cli.app, ["fix", "--yes"])
    assert result.exit_code == 0, result.output
    assert captured == {"ids": ["vulkan.icd.32bit.AMD"], "yes": True}

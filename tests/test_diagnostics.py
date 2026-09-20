import json
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.diagnostics.environment import gaming_variables
from gamedoctor.diagnostics.proton import inspect_tool
from gamedoctor.diagnostics.steam import find_installs, installed_runtimes


def _ctx(tmp_path: Path) -> Context:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return Context({"HOME": str(home), "PATH": "/nonexistent"})


def _make_steam(root: Path, extra_lib: Path | None = None, missing: str | None = None) -> None:
    (root / "steamapps" / "common").mkdir(parents=True)
    (root / "steam.sh").write_text("#!/bin/sh\n")
    entries = [f'\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t}}\n']
    if extra_lib:
        (extra_lib / "steamapps").mkdir(parents=True)
        entries.append(f'\t"1"\n\t{{\n\t\t"path"\t\t"{extra_lib}"\n\t}}\n')
    if missing:
        entries.append(f'\t"2"\n\t{{\n\t\t"path"\t\t"{missing}"\n\t}}\n')
    (root / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n' + "".join(entries) + "}\n")


def test_find_native_steam_with_libraries(tmp_path: Path):
    ctx = _ctx(tmp_path)
    root = ctx.home / ".local/share/Steam"
    extra = tmp_path / "mnt/games"
    _make_steam(root, extra, "/mnt/unplugged")
    (ctx.home / ".steam").mkdir()
    (ctx.home / ".steam/root").symlink_to(root)
    installs = find_installs(ctx)
    assert len(installs) == 1  # symlink and real dir are the same install
    inst = installs[0]
    assert inst.kind == "native"
    assert [p.resolve() for p in inst.libraries] == [root.resolve(), extra.resolve()]
    assert inst.missing_libraries == ["/mnt/unplugged"]


def test_flatpak_and_native_are_distinct(tmp_path: Path):
    ctx = _ctx(tmp_path)
    _make_steam(ctx.home / ".local/share/Steam")
    _make_steam(ctx.home / ".var/app/com.valvesoftware.Steam/.local/share/Steam")
    kinds = sorted(i.kind for i in find_installs(ctx))
    assert kinds == ["flatpak", "native"]


def test_installed_runtimes(tmp_path: Path):
    lib = tmp_path / "lib"
    (lib / "steamapps/common/SteamLinuxRuntime_sniper").mkdir(parents=True)
    (lib / "steamapps/common/SteamLinuxRuntime").mkdir(parents=True)
    assert set(installed_runtimes([lib])) == {"sniper", "scout"}


def test_inspect_proton_tool(tmp_path: Path):
    ctx = _ctx(tmp_path)
    good = tmp_path / "GE-Proton10-15"
    (good / "files").mkdir(parents=True)
    (good / "proton").write_text("#!/usr/bin/env python3\n")
    (good / "version").write_text("1723000000 GE-Proton10-15\n")
    (good / "toolmanifest.vdf").write_text('"manifest"\n{\n\t"version"\t"2"\n\t"require_tool_appid"\t"1628350"\n}\n')
    (good / "compatibilitytool.vdf").write_text(
        '"compatibilitytools"\n{\n\t"compat_tools"\n\t{\n\t\t"GE-Proton10-15"\n\t\t{\n\t\t\t"install_path"\t"."\n\t\t}\n\t}\n}\n'
    )
    tool = inspect_tool(ctx, good, "Custom")
    assert tool.valid
    assert tool.version == "GE-Proton10-15"
    assert tool.runtime == "sniper"
    assert tool.name == "GE-Proton10-15"

    broken = tmp_path / "Proton 9.0"
    broken.mkdir()
    tool = inspect_tool(ctx, broken, "Valve")
    assert not tool.valid
    assert any("proton" in p for p in tool.problems)


def test_gaming_variables_filter():
    env = {"PATH": "/usr/bin", "DXVK_HUD": "fps", "PROTON_LOG": "1", "LD_PRELOAD": "x.so", "VK_ICD_FILENAMES": "/a.json", "HOME": "/h"}
    found = gaming_variables(env)
    assert set(found) == {"DXVK_HUD", "PROTON_LOG", "LD_PRELOAD"}

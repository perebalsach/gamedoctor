"""Proton versions (Valve and custom), their integrity and runtime requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.core.util import parse_vdf, vdf_get
from gamedoctor.diagnostics.base import Diagnostic

RUNTIME_BY_APPID = {"1628350": "sniper", "1391110": "soldier", "1070560": "scout", "4183110": "steamrt4"}


@dataclass
class ProtonTool:
    name: str
    path: Path
    source: str  # Valve | Custom
    version: str | None = None
    runtime: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.problems


def inspect_tool(ctx: Context, path: Path, source: str, name: str | None = None) -> ProtonTool:
    tool = ProtonTool(name or path.name, path, source)
    if not path.is_dir():
        tool.problems.append("directory does not exist")
        return tool
    if not (path / "proton").exists():
        tool.problems.append("missing 'proton' launcher script")
    if not (path / "toolmanifest.vdf").exists():
        tool.problems.append("missing toolmanifest.vdf")
    if source == "Custom" and not (path / "compatibilitytool.vdf").exists():
        tool.problems.append("missing compatibilitytool.vdf")
    if not (path / "files").is_dir() and not (path / "dist").is_dir():
        tool.problems.append("missing 'files' directory (incomplete download?)")

    version_line = ctx.read_line(path / "version")
    if version_line:
        tool.version = version_line.split()[-1]

    manifest = ctx.read(path / "toolmanifest.vdf")
    if manifest:
        appid = vdf_get(parse_vdf(manifest), "manifest", "require_tool_appid")
        if isinstance(appid, str):
            tool.runtime = RUNTIME_BY_APPID.get(appid, f"appid {appid}")

    if source == "Custom" and not name:
        compat = ctx.read(path / "compatibilitytool.vdf")
        if compat:
            tools = vdf_get(parse_vdf(compat), "compatibilitytools", "compat_tools") or {}
            if isinstance(tools, dict) and tools:
                tool.name = next(iter(tools))
    return tool


def discover(ctx: Context) -> list[ProtonTool]:
    tools: list[ProtonTool] = []
    seen: set[Path] = set()

    def add(tool: ProtonTool) -> None:
        real = tool.path.resolve()
        if real not in seen:
            seen.add(real)
            tools.append(tool)

    for lib in ctx.steam_libraries:
        common = lib / "steamapps" / "common"
        if common.is_dir():
            for d in sorted(common.glob("Proton*")):
                if d.is_dir():
                    add(inspect_tool(ctx, d, "Valve"))

    for cdir, source in compat_tool_dirs(ctx):
        if not cdir.is_dir():
            continue
        for entry in sorted(cdir.iterdir()):
            if entry.is_dir():
                add(inspect_tool(ctx, entry, source))
            elif entry.suffix == ".vdf":
                text = ctx.read(entry) or ""
                compat = vdf_get(parse_vdf(text), "compatibilitytools", "compat_tools") or {}
                for name, info in compat.items():
                    if isinstance(info, dict) and info.get("install_path"):
                        add(inspect_tool(ctx, (cdir / info["install_path"]).resolve(), source, name))
    return tools


def compat_tool_dirs(ctx: Context) -> list[tuple[Path, str]]:
    """Every directory Steam scans for third-party compatibility tools."""
    dirs: list[tuple[Path, str]] = []
    for inst in ctx.steam_installs:
        dirs.append((inst.root / "compatibilitytools.d", "Custom"))
    for extra in (ctx.env.get("STEAM_EXTRA_COMPAT_TOOLS_PATHS") or "").split(":"):
        if extra:
            dirs.append((Path(extra), "Custom"))
    for data in ctx.data_dirs() + [Path("/usr/share"), Path("/usr/local/share")]:
        dirs.append((data / "steam" / "compatibilitytools.d", "System"))
    seen: set[Path] = set()
    unique: list[tuple[Path, str]] = []
    for d, source in dirs:
        if d not in seen:
            seen.add(d)
            unique.append((d, source))
    return unique


def default_compat_tool(ctx: Context, root: Path) -> tuple[bool, str | None]:
    """(config found, name of the default Steam Play tool or None if not enabled for all titles)."""
    text = ctx.read(root / "config" / "config.vdf")
    if not text:
        return False, None
    mapping = vdf_get(parse_vdf(text), "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")
    if not isinstance(mapping, dict):
        return True, None
    entry = mapping.get("0")
    if isinstance(entry, dict) and entry.get("name"):
        return True, entry["name"]
    return True, None


class ProtonDiagnostic(Diagnostic):
    name = "proton"
    title = "Proton"
    requires = ("steam",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        if not ctx.steam_installs:
            r.fact("Proton", "skipped (Steam not detected)", absent=True)
            return r

        tools = discover(ctx)
        ctx.proton_tools = tools
        runtimes = getattr(ctx, "steam_runtimes", {})

        if not tools:
            r.fact("Proton", "no versions installed", absent=True)
            r.check(
                "proton.installed",
                Severity.INFO,
                "No Proton version is installed yet",
                "Steam downloads Proton the first time you install or launch a Windows game with "
                "Steam Play enabled. Until then only native Linux games can run.",
                "Steam > Settings > Compatibility > Enable Steam Play for all other titles.",
            )
        else:
            r.ok("proton.installed", f"{len(tools)} Proton version(s) installed")

        for tool in tools:
            label = tool.source
            detail = tool.version or ""
            if tool.runtime:
                detail = f"{detail}  [{tool.runtime}]".strip()
            if tool.valid:
                r.fact(label, f"{tool.name}  {detail}".rstrip(), Severity.PASS)
            else:
                r.fact(label, f"{tool.name}  ({'; '.join(tool.problems)})", Severity.WARNING)
                r.check(
                    f"proton.broken.{tool.name}",
                    Severity.WARNING,
                    f"Proton installation looks incomplete: {tool.name}",
                    f"{tool.path} is {'; '.join(tool.problems)}. Games configured to use it will fail to "
                    "launch with no visible error, or Steam will silently fall back to another version.",
                    "Re-download it (Valve versions: Steam > Library > Tools, or delete the folder and let "
                    "Steam reinstall; custom versions: reinstall with ProtonUp-Qt / ProtonPlus).",
                )

        missing_rt: dict[str, list[str]] = {}
        for tool in tools:
            if tool.runtime and tool.runtime in ("sniper", "soldier", "scout") and tool.runtime not in runtimes:
                missing_rt.setdefault(tool.runtime, []).append(tool.name)
        for rt, names in missing_rt.items():
            r.check(
                f"proton.runtime.{rt}",
                Severity.WARNING,
                f"Steam Linux Runtime '{rt}' required by {', '.join(names)} is not installed",
                f"These Proton versions run inside the '{rt}' container runtime, which is a separate Steam "
                "download. Steam normally fetches it automatically when a game first uses the tool. If a "
                "game exits immediately with this Proton version, the runtime download is the first "
                "suspect.",
                f"In Steam, search your Library (with Tools enabled) for 'Steam Linux Runtime {rt}' and install it, "
                "or launch any game with this Proton version to trigger the download.",
            )
        if tools and not missing_rt:
            r.ok("proton.runtime", "Required Steam Linux Runtimes are installed")

        for inst in ctx.steam_installs:
            found, default = default_compat_tool(ctx, inst.root)
            if not found:
                continue
            if default:
                known = {t.name for t in tools} | {t.path.name for t in tools}
                installed = default in known or any(default.replace("_", " ").lower() in n.lower().replace("_", " ").replace("-", " ") for n in known)
                # Valve's internal ids: proton_experimental -> "Proton - Experimental", proton_9 -> "Proton 9.0", proton_hotfix
                valve_alias = default.lower().removeprefix("proton_").replace("_", " ")
                installed = installed or any(valve_alias in n.lower().replace("-", " ").replace("  ", " ") for n in known)
                r.fact("Default (Steam Play)", default, Severity.PASS if installed else Severity.WARNING)
                if installed:
                    r.ok("proton.steamplay", "Steam Play is enabled for all titles")
                else:
                    r.check(
                        "proton.steamplay.default-missing",
                        Severity.WARNING,
                        f"The default Steam Play tool '{default}' is not installed",
                        "Steam is configured to run all Windows games with a compatibility tool that no "
                        "longer exists on disk (uninstalled custom Proton, or a Valve version Steam has "
                        "not downloaded yet). Affected games may fail to launch or silently run with a "
                        "different Proton.",
                        "Steam > Settings > Compatibility: pick an installed Proton version as the default.",
                    )
            else:
                r.fact("Default (Steam Play)", "only Valve-tested titles", absent=True)
                r.check(
                    "proton.steamplay",
                    Severity.INFO,
                    "Steam Play is not enabled for all titles",
                    "Without this setting, Steam only offers Proton for games Valve has explicitly "
                    "tested. Other Windows games show no Play button (or 'not available on this platform') "
                    "on Linux.",
                    "Steam > Settings > Compatibility > Enable Steam Play for all other titles.",
                )
        return r

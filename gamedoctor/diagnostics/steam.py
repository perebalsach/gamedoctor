"""Steam installations (native, Flatpak, Snap), library folders and runtimes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.core.util import parse_vdf, vdf_get
from gamedoctor.diagnostics.base import Diagnostic

FLATPAK_ID = "com.valvesoftware.Steam"

RUNTIME_DIRS = {
    "SteamLinuxRuntime_sniper": "sniper",
    "SteamLinuxRuntime_soldier": "soldier",
    "SteamLinuxRuntime_4": "steamrt4",
    "SteamLinuxRuntime": "scout",
}


@dataclass
class SteamInstall:
    kind: str  # native | flatpak | snap
    root: Path
    libraries: list[Path] = field(default_factory=list)
    missing_libraries: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return {"native": "Native", "flatpak": "Flatpak", "snap": "Snap"}[self.kind]


def find_installs(ctx: Context) -> list[SteamInstall]:
    flatpak_home = ctx.home / ".var" / "app" / FLATPAK_ID
    candidates = [
        ("native", ctx.home / ".steam" / "root"),
        ("native", ctx.user_data_dir() / "Steam"),
        ("native", ctx.home / ".steam" / "steam"),
        ("native", ctx.home / ".steam" / "debian-installation"),
        ("flatpak", flatpak_home / ".local" / "share" / "Steam"),
        ("flatpak", flatpak_home / "data" / "Steam"),
        ("snap", ctx.home / "snap" / "steam" / "common" / ".local" / "share" / "Steam"),
    ]
    installs: list[SteamInstall] = []
    seen: set[Path] = set()
    for kind, path in candidates:
        if not path.is_dir():
            continue
        real = path.resolve()
        if real in seen:
            continue
        if not ((real / "steamapps").is_dir() or (real / "steam.sh").exists() or (real / "ubuntu12_32").is_dir()):
            continue
        seen.add(real)
        inst = SteamInstall(kind, real)
        inst.libraries, inst.missing_libraries = library_folders(ctx, real)
        installs.append(inst)
    return installs


def library_folders(ctx: Context, root: Path) -> tuple[list[Path], list[str]]:
    libs: list[Path] = [root]
    missing: list[str] = []
    for vdf in (root / "steamapps" / "libraryfolders.vdf", root / "config" / "libraryfolders.vdf"):
        text = ctx.read(vdf)
        if not text:
            continue
        folders = vdf_get(parse_vdf(text), "libraryfolders") or {}
        for key, entry in folders.items():
            path = entry.get("path") if isinstance(entry, dict) else (entry if key.isdigit() else None)
            if not path:
                continue
            p = Path(path)
            if (p / "steamapps").is_dir():
                libs.append(p)
            else:
                missing.append(path)
        break
    unique: list[Path] = []
    seen: set[Path] = set()
    for p in libs:
        real = p.resolve()
        if real not in seen:
            seen.add(real)
            unique.append(p)
    return unique, missing


def installed_runtimes(libraries: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for lib in libraries:
        common = lib / "steamapps" / "common"
        if not common.is_dir():
            continue
        for entry in common.glob("SteamLinuxRuntime*"):
            name = RUNTIME_DIRS.get(entry.name, entry.name.removeprefix("SteamLinuxRuntime_").lower())
            found.setdefault(name, entry)
    return found


class SteamDiagnostic(Diagnostic):
    name = "steam"
    title = "Steam"
    requires = ("system",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        installs = find_installs(ctx)
        ctx.steam_installs = installs
        all_libs: list[Path] = []
        for inst in installs:
            for lib in inst.libraries:
                if lib.resolve() not in {p.resolve() for p in all_libs}:
                    all_libs.append(lib)
        ctx.steam_libraries = all_libs
        ctx.steam_runtimes = installed_runtimes(all_libs)

        if not installs:
            binary = ctx.which("steam")
            r.fact("Installation", "not detected" + (f" (launcher found at {binary})" if binary else ""), absent=True)
            r.check(
                "steam.installed",
                Severity.INFO,
                "Steam was not detected",
                "No Steam data directory was found for this user. Steam and Proton checks were skipped. "
                "If Steam is installed but has never been started, run it once and try again.",
            )
            return r

        r.ok("steam.installed", f"Steam detected ({', '.join(i.label for i in installs)})")
        for inst in installs:
            r.fact("Installation", f"{inst.label}  {inst.root}", Severity.PASS)
            beta = ctx.read_line(inst.root / "package" / "beta")
            if beta:
                r.fact("Client channel", beta)
            for lib in inst.libraries:
                if lib.resolve() != inst.root:
                    r.fact("Library", str(lib), Severity.PASS)
            for missing in inst.missing_libraries:
                r.fact("Library", f"{missing}  (not available)", Severity.WARNING)
                r.check(
                    "steam.library.missing",
                    Severity.WARNING,
                    f"Steam library folder is not available: {missing}",
                    "Steam has a library configured at this path but there is no steamapps folder there. "
                    "Usually the drive is not mounted (or is mounted somewhere else). Games installed in "
                    "that library will show as needing to be reinstalled and their Proton prefixes will "
                    "be unreachable until it is mounted again.",
                    "Mount the drive at the original location, or remove the library in Steam > Settings > Storage.",
                )

        if len(installs) > 1:
            r.check(
                "steam.multiple",
                Severity.INFO,
                "More than one Steam installation found",
                "Both a "
                + " and a ".join(i.label for i in installs)
                + " Steam exist. They keep separate games, Proton versions and settings. Make sure you "
                "troubleshoot the one you actually launch.",
            )
        for inst in installs:
            if inst.kind == "flatpak":
                r.check(
                    "steam.flatpak",
                    Severity.INFO,
                    "Steam is installed as a Flatpak",
                    "Flatpak Steam runs in a sandbox with its own runtime and drivers (provided by the "
                    "org.freedesktop.Platform.GL extensions, updated with `flatpak update`). Game libraries "
                    "outside your home folder need an explicit permission: "
                    f"flatpak override --user --filesystem=/path/to/library {FLATPAK_ID}",
                )
            if inst.kind == "snap":
                r.check(
                    "steam.snap",
                    Severity.INFO,
                    "Steam is installed as a Snap",
                    "The Snap package is sandboxed and has historically had issues with external drives, "
                    "controllers and some Proton features. If you hit problems that others do not, the "
                    "native .deb or Flatpak versions are worth trying.",
                )

        runtimes = ctx.steam_runtimes
        if runtimes:
            r.fact("Steam Runtime", ", ".join(sorted(runtimes)), Severity.PASS)
        else:
            r.fact("Steam Runtime", "no container runtime downloaded yet", absent=True)
        return r

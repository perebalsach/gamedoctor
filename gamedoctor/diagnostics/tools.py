"""Optional gaming utilities: GameMode, MangoHud, Gamescope, vkBasalt, Wine, launchers.

Missing optional tools are reported as plain facts, never as problems.
"""

from __future__ import annotations

import re
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.diagnostics.base import Diagnostic

_VERSION = re.compile(r"v?(\d+\.\d+(?:\.\d+)?(?:-\w+)?)")


def _version(text: str) -> str | None:
    m = _VERSION.search(text or "")
    return m.group(1) if m else None


class ToolsDiagnostic(Diagnostic):
    name = "tools"
    title = "Runtime tools"
    requires = ("system", "vulkan")

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        self._gamemode(ctx, r)
        self._mangohud(ctx, r)
        self._gamescope(ctx, r)
        self._vkbasalt(ctx, r)
        self._wine(ctx, r)
        self._launchers(ctx, r)
        return r

    # -- GameMode ----------------------------------------------------------------
    def _gamemode(self, ctx: Context, r: ModuleResult) -> None:
        daemon = ctx.which("gamemoded")
        lib = ctx.find_library("libgamemodeauto.so.0")
        if not daemon and not lib:
            r.fact("GameMode", "not installed", absent=True)
            return
        version = _version(ctx.run(["gamemoded", "-v"], timeout=5).text) if daemon else None
        label = f"installed{f' {version}' if version else ''}"

        if not daemon:
            r.fact("GameMode", f"{label}, daemon missing", Severity.WARNING)
            r.check(
                "gamemode.daemon",
                Severity.WARNING,
                "GameMode library is installed but the gamemoded daemon is missing",
                "libgamemodeauto is present, so games may request GameMode, but there is no daemon to "
                "answer. Requests fail silently and GameMode does nothing.",
            )
            return

        status = ctx.run(["gamemoded", "-s"], timeout=8)
        if status.ok:
            r.fact("GameMode", f"{label}, daemon responding", Severity.PASS)
            r.ok("gamemode.daemon", "GameMode daemon responds")
        else:
            has_bus = bool(ctx.env.get("DBUS_SESSION_BUS_ADDRESS")) or Path(f"/run/user/{ctx.uid}/bus").exists()
            r.fact("GameMode", f"{label}, daemon not responding", Severity.WARNING)
            r.check(
                "gamemode.daemon",
                Severity.WARNING,
                "GameMode is installed but the daemon is not responding",
                "gamemoded is started on demand over the user D-Bus session. It did not answer, so "
                "gamemoderun and games that request GameMode will run without it. "
                + (
                    "No D-Bus session bus was found in this environment, which alone explains it if you are running gamedoctor over SSH. "
                    if not has_bus
                    else "Common causes: the user service failed to start, or a broken gamemode.ini."
                ),
                steps=ctx.solution("gamemode.daemon"),
            )
        if 32 not in lib:
            r.fact("GameMode 32-bit", "not installed", absent=True)
            r.check(
                "gamemode.32bit",
                Severity.INFO,
                "32-bit GameMode library is not installed",
                "gamemoderun works for 64-bit games. 32-bit games (and some Proton games that spawn "
                "32-bit processes) will log an error about libgamemodeauto.so.0 and skip GameMode. "
                "Harmless, but noisy.",
                steps=ctx.solution("gamemode.32bit"),
            )

    # -- MangoHud ----------------------------------------------------------------
    def _mangohud(self, ctx: Context, r: ModuleResult) -> None:
        layers = [l for l in ctx.vulkan_layers if "MANGOHUD" in l.name.upper()]
        binary = ctx.which("mangohud")
        if not layers and not binary:
            r.fact("MangoHud", "not installed", absent=True)
            return
        version = _version(ctx.run(["mangohud", "--version"], timeout=5).text) if binary else None
        archs = set().union(*(l.archs for l in layers)) if layers else set()
        r.fact("MangoHud", f"installed{f' {version}' if version else ''}", Severity.PASS)
        if layers and 32 not in archs:
            r.fact("MangoHud 32-bit", "not installed", absent=True)
            r.check(
                "mangohud.32bit",
                Severity.INFO,
                "32-bit MangoHud layer is not installed",
                "The overlay will not appear in 32-bit games, and 32-bit Vulkan apps print a loader "
                "warning. Only matters if you use MangoHud with 32-bit titles.",
                steps=ctx.solution("mangohud.32bit"),
            )

    # -- Gamescope ----------------------------------------------------------------
    def _gamescope(self, ctx: Context, r: ModuleResult) -> None:
        if not ctx.which("gamescope"):
            r.fact("Gamescope", "not installed", absent=True)
            return
        version = _version(ctx.run(["gamescope", "--version"], timeout=5).text)
        r.fact("Gamescope", f"installed{f' {version}' if version else ''}", Severity.PASS)

    # -- vkBasalt ------------------------------------------------------------------
    def _vkbasalt(self, ctx: Context, r: ModuleResult) -> None:
        layers = [l for l in ctx.vulkan_layers if "VKBASALT" in l.name.upper()]
        if layers:
            r.fact("vkBasalt", "installed", Severity.PASS)
        else:
            r.fact("vkBasalt", "not installed", absent=True)

    # -- Wine -----------------------------------------------------------------------
    def _wine(self, ctx: Context, r: ModuleResult) -> None:
        if not ctx.which("wine"):
            r.fact("Wine (system)", "not installed", absent=True)
            return
        out = ctx.run(["wine", "--version"], timeout=8).text.strip()
        r.fact("Wine (system)", out.splitlines()[0] if out else "installed", Severity.PASS)

    # -- Launchers -------------------------------------------------------------------
    def _launchers(self, ctx: Context, r: ModuleResult) -> None:
        apps = ctx.home / ".var" / "app"
        launchers = [
            ("Lutris", ["lutris"], "net.lutris.Lutris"),
            ("Heroic", ["heroic"], "com.heroicgameslauncher.hgl"),
            ("Bottles", ["bottles"], "com.usebottles.bottles"),
        ]
        for label, binaries, flatpak_id in launchers:
            native = any(ctx.which(b) for b in binaries)
            flatpak = (apps / flatpak_id).is_dir()
            if native or flatpak:
                how = " + ".join(x for x, ok in (("native", native), ("Flatpak", flatpak)) if ok)
                r.fact(label, f"installed ({how})", Severity.PASS)

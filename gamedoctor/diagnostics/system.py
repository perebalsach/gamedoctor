"""Distribution, kernel, desktop and session basics."""

from __future__ import annotations

import os
import re

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.core.util import human_size
from gamedoctor.diagnostics.base import Diagnostic

_DESKTOP_NAMES = {
    "kde": "KDE Plasma",
    "plasma": "KDE Plasma",
    "gnome": "GNOME",
    "ubuntu": "GNOME",
    "x-cinnamon": "Cinnamon",
    "cinnamon": "Cinnamon",
    "xfce": "Xfce",
    "lxqt": "LXQt",
    "lxde": "LXDE",
    "mate": "MATE",
    "budgie": "Budgie",
    "deepin": "Deepin",
    "pantheon": "Pantheon",
    "cosmic": "COSMIC",
    "hyprland": "Hyprland",
    "sway": "Sway",
    "niri": "niri",
    "i3": "i3",
    "enlightenment": "Enlightenment",
    "gamescope": "Gamescope session (Steam gaming mode)",
}


def detect_desktop(ctx: Context) -> str | None:
    if "gamescope-session" in ctx.processes or "gamescope-session-plus" in ctx.processes:
        return _DESKTOP_NAMES["gamescope"]
    raw = ctx.env.get("XDG_CURRENT_DESKTOP") or ctx.env.get("DESKTOP_SESSION") or ""
    parts = [p for p in raw.split(":") if p]
    for part in parts:
        if part.lower() in _DESKTOP_NAMES:
            return _DESKTOP_NAMES[part.lower()]
    return parts[-1] if parts else None


def desktop_version(ctx: Context, desktop: str | None) -> str | None:
    if not desktop:
        return None
    if desktop.startswith("KDE"):
        res = ctx.run(["plasmashell", "--version"], timeout=5)
    elif desktop == "GNOME":
        res = ctx.run(["gnome-shell", "--version"], timeout=5)
    else:
        return None
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", res.stdout) if res.ok else None
    return m.group(1) if m else None


def detect_session(ctx: Context) -> str:
    raw = (ctx.env.get("XDG_SESSION_TYPE") or "").lower()
    if raw in ("wayland", "x11"):
        return raw
    if ctx.env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if ctx.env.get("DISPLAY"):
        return "x11"
    return "none"


class SystemDiagnostic(Diagnostic):
    name = "system"
    title = "System"

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        osr = ctx.os_release
        os_name = osr.get("PRETTY_NAME") or osr.get("NAME") or "Unknown Linux"
        version = osr.get("VERSION_ID") or ""
        if version and version not in os_name:
            os_name = f"{os_name} {version}"
        r.fact("OS", os_name)
        if ctx.immutable:
            r.fact("OS type", "image-based (immutable) system")

        uname = os.uname()
        r.fact("Kernel", uname.release)
        r.fact("Architecture", uname.machine)

        cpu = self._cpu_model(ctx)
        if cpu:
            r.fact("CPU", cpu)
        mem = self._memory(ctx)
        if mem:
            r.fact("Memory", mem)

        desktop = detect_desktop(ctx)
        dver = desktop_version(ctx, desktop)
        r.fact("Desktop", f"{desktop} {dver}".strip() if desktop else "unknown")

        session = detect_session(ctx)
        ctx.session = session
        r.fact("Session", {"wayland": "Wayland", "x11": "X11", "none": "no graphical session"}[session])

        if os.path.exists("/.flatpak-info"):
            r.fact("Sandbox", "gamedoctor is running inside a Flatpak sandbox", Severity.WARNING)
            r.check(
                "system.sandboxed",
                Severity.WARNING,
                "gamedoctor is running inside a Flatpak sandbox",
                "The results describe the sandbox, not your host system. Drivers, Steam and "
                "services on the host are not visible from here. Run gamedoctor from a normal shell.",
            )

        if uname.machine != "x86_64":
            r.check(
                "system.arch",
                Severity.WARNING,
                f"Unsupported CPU architecture for Steam and Proton ({uname.machine})",
                "Steam, Proton and nearly all commercial games are built for x86_64. On this "
                "architecture they can only run through emulation layers such as FEX or Box64.",
            )
        else:
            r.ok("system.arch", "CPU architecture is x86_64")

        if session == "none":
            r.check(
                "system.graphical-session",
                Severity.WARNING,
                "No graphical session detected",
                "Neither DISPLAY nor WAYLAND_DISPLAY is set. gamedoctor was probably started "
                "over SSH or from a text console. Checks that need a display (OpenGL, GameMode, "
                "audio) may report problems that do not exist in your desktop session.",
                "Run gamedoctor from a terminal inside your desktop session.",
            )
        else:
            r.ok("system.graphical-session", f"Graphical session detected ({session})")

        if session == "wayland":
            xwayland = ctx.which("Xwayland")
            r.fact("XWayland", "available" if xwayland else "not found", Severity.PASS if xwayland else Severity.WARNING)
            if xwayland:
                r.ok("display.xwayland", "XWayland is available")
            else:
                r.check(
                    "display.xwayland",
                    Severity.WARNING,
                    "XWayland is not installed",
                    "You are in a Wayland session, but the Xwayland binary was not found. Steam, "
                    "Proton/Wine games and most native games still use X11 and need XWayland to "
                    "open a window on Wayland.",
                    steps=ctx.solution("display.xwayland"),
                )

        if uname.machine == "x86_64":
            libc = ctx.find_library("libc.so.6")
            has32 = 32 in libc
            r.fact("32-bit libraries", "available" if has32 else "not found", Severity.PASS if has32 else Severity.WARNING)
            if has32:
                r.ok("system.multilib", "32-bit C library is installed")
            else:
                r.check(
                    "system.multilib",
                    Severity.WARNING,
                    "No 32-bit system libraries found",
                    "The native Steam client and many games still contain 32-bit components, "
                    "which need 32-bit versions of the C library and graphics drivers. Without "
                    "them native Steam will not start. (Not required if you only use the Flatpak "
                    "version of Steam, which bundles its own.)",
                    steps=ctx.solution("system.multilib"),
                )
        return r

    @staticmethod
    def _cpu_model(ctx: Context) -> str | None:
        text = ctx.read("/proc/cpuinfo") or ""
        for line in text.splitlines():
            if line.lower().startswith("model name"):
                return re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
        return None

    @staticmethod
    def _memory(ctx: Context) -> str | None:
        text = ctx.read("/proc/meminfo") or ""
        m = re.search(r"MemTotal:\s+(\d+) kB", text)
        return human_size(int(m.group(1)) * 1024) if m else None

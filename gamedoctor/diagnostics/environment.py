"""Gaming-related environment variables set globally in the user's session."""

from __future__ import annotations

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.diagnostics.base import Diagnostic

_PREFIXES = ("DXVK_", "VKD3D_", "PROTON_", "RADV_", "ANV_", "NVK_", "MESA_", "WINE", "STEAM_", "SDL_", "__GL_", "__NV_", "VK_", "AMD_", "GAMEMODE", "MANGOHUD", "LIBGL_")
_EXACT = {"ENABLE_VKBASALT", "DRI_PRIME", "LD_PRELOAD", "LD_LIBRARY_PATH", "__GLX_VENDOR_LIBRARY_NAME", "ENABLE_GAMESCOPE_WSI", "GAMESCOPE_WAYLAND_DISPLAY"}
_IGNORE = {"STEAM_RUNTIME", "STEAMSCRIPT", "STEAM_COMPAT_CLIENT_INSTALL_PATH", "SDL_VIDEO_DRIVER"}  # noise set by Steam itself
# handled by the vulkan module with GPU knowledge
_VULKAN_HANDLED = {"VK_DRIVER_FILES", "VK_ICD_FILENAMES", "VK_ADD_DRIVER_FILES"}


def gaming_variables(env: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in sorted(env.items()):
        if key in _IGNORE or key in _VULKAN_HANDLED:
            continue
        if key in _EXACT or key.startswith(_PREFIXES):
            out[key] = value
    return out


class EnvironmentDiagnostic(Diagnostic):
    name = "environment"
    title = "Environment"
    requires = ("gpu",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        found = gaming_variables(ctx.env)
        if not found:
            r.fact("Gaming variables", "none set globally", absent=True)
            r.ok("environment.clean", "No global gaming environment overrides")
            return r

        for key, value in found.items():
            shown = value if len(value) <= 80 else value[:77] + "..."
            r.fact(key, shown or "(empty)")

        r.check(
            "environment.globals",
            Severity.INFO,
            f"{len(found)} gaming-related variable(s) are set in the environment",
            "These apply to every game started from this environment, not just the one you are "
            "debugging, and they are invisible in Steam's per-game launch options. Note that Steam "
            "started from a desktop menu may not see variables set only in your shell profile.",
        )

        if found.get("LD_PRELOAD"):
            r.check(
                "environment.ld-preload",
                Severity.WARNING,
                "LD_PRELOAD is set globally",
                f"LD_PRELOAD='{found['LD_PRELOAD']}' injects a library into every program. Stale entries "
                "(MangoHud, GameMode, an uninstalled overlay) are a classic cause of games crashing on "
                "start with 'cannot be preloaded' errors.",
                "Set MANGOHUD=1 / gamemoderun per game instead of a global preload.",
            )
        if found.get("LIBGL_ALWAYS_SOFTWARE", "").lower() in ("1", "true", "yes"):
            r.check(
                "environment.software-gl",
                Severity.ERROR,
                "LIBGL_ALWAYS_SOFTWARE forces OpenGL software rendering",
                "Every OpenGL application, including the Steam client, renders on the CPU while this is set.",
                "Unset LIBGL_ALWAYS_SOFTWARE.",
            )
        if found.get("__GLX_VENDOR_LIBRARY_NAME") or found.get("__NV_PRIME_RENDER_OFFLOAD") or found.get("DRI_PRIME"):
            r.check(
                "environment.gpu-selection",
                Severity.INFO,
                "A GPU selection variable is set globally",
                "DRI_PRIME / __NV_PRIME_RENDER_OFFLOAD / __GLX_VENDOR_LIBRARY_NAME change which GPU renders. "
                "Set globally they also affect the desktop and can break the compositor on some setups; "
                "they are normally used per game.",
            )
        proton_vars = [k for k in found if k.startswith("PROTON_")]
        if proton_vars:
            r.check(
                "environment.proton-globals",
                Severity.INFO,
                f"Proton options are set globally: {', '.join(proton_vars)}",
                "PROTON_* variables are meant for per-game launch options. Set globally they change the "
                "behaviour of every Proton game, which makes problems hard to reproduce for others.",
            )
        if found.get("WINEPREFIX"):
            r.check(
                "environment.wineprefix",
                Severity.INFO,
                "WINEPREFIX is set globally",
                "This affects plain Wine only; Proton manages its own prefixes. It is harmless for Steam "
                "but confusing when troubleshooting Lutris or Bottles.",
            )
        return r

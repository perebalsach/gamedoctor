"""GPU hardware, kernel drivers and OpenGL."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.core.util import PCI_VENDORS, human_size, lookup_pci_name, pretty_gpu_name
from gamedoctor.diagnostics.base import Diagnostic

_PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids")


@dataclass
class GPU:
    slot: str
    vendor_id: str
    device_id: str
    vendor: str
    name: str
    driver: str | None
    vram: int | None = None
    boot_vga: bool = False
    card: str | None = None

    @property
    def software_renderer(self) -> bool:
        return False


def enumerate_gpus(ctx: Context) -> list[GPU]:
    gpus: list[GPU] = []
    pci_ids: str | None = None
    for dev in sorted(Path("/sys/bus/pci/devices").glob("*")):
        cls = (ctx.read_line(dev / "class") or "").lower()
        if not cls.startswith("0x03"):
            continue
        vendor_id = (ctx.read_line(dev / "vendor") or "").lower()
        device_id = (ctx.read_line(dev / "device") or "").lower()
        vendor = PCI_VENDORS.get(vendor_id, "Unknown")
        driver = (dev / "driver").resolve().name if (dev / "driver").exists() else None
        vram_raw = ctx.read_line(dev / "mem_info_vram_total")
        vram = int(vram_raw) if vram_raw and vram_raw.isdigit() else None
        card = None
        if (dev / "drm").is_dir():
            cards = sorted(p.name for p in (dev / "drm").glob("card*"))
            card = cards[0] if cards else None

        name = None
        if pci_ids is None:
            pci_ids = next((ctx.read(p) or "" for p in _PCI_IDS if Path(p).exists()), "")
        if pci_ids:
            name = pretty_gpu_name(lookup_pci_name(pci_ids, vendor_id, device_id), vendor)
        if not name:
            res = ctx.run(["lspci", "-mm", "-s", dev.name], timeout=5)
            if res.ok:
                try:
                    fields = shlex.split(res.stdout.strip())
                    if len(fields) >= 4:
                        name = pretty_gpu_name(fields[3], vendor)
                except ValueError:
                    pass
        if not name:
            name = f"{vendor} device {device_id}"
        gpus.append(GPU(dev.name, vendor_id, device_id, vendor, name, driver, vram, ctx.read_line(dev / "boot_vga") == "1", card))
    return gpus


def nvidia_userspace_version(ctx: Context) -> str | None:
    lib = ctx.find_library("libGLX_nvidia.so.0").get(64)
    if not lib:
        return None
    target = Path(lib).resolve().name
    m = re.search(r"\.so\.(\d+\.\d+(?:\.\d+)?)$", target)
    return m.group(1) if m else None


class GpuDiagnostic(Diagnostic):
    name = "gpu"
    title = "GPU"
    requires = ("system",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        gpus = enumerate_gpus(ctx)
        ctx.gpus = gpus

        if not gpus:
            r.fact("Device", "no GPU detected", Severity.CRITICAL)
            r.check(
                "gpu.detected",
                Severity.CRITICAL,
                "No GPU was detected",
                "No PCI display controller was found in /sys. gamedoctor cannot assess graphics "
                "drivers. On virtual machines this usually means no GPU is passed through; on "
                "real hardware it indicates a very unusual setup.",
            )
            self._opengl(ctx, r)
            return r

        r.ok("gpu.detected", f"{len(gpus)} GPU(s) detected")
        multi = len(gpus) > 1
        for idx, gpu in enumerate(gpus):
            prefix = f"GPU {idx} " if multi else ""
            tag = " (primary)" if multi and gpu.boot_vga else ""
            r.fact(f"{prefix}Device".strip(), gpu.name + tag)
            if gpu.driver:
                r.fact(f"{prefix}Kernel driver".strip(), gpu.driver, Severity.PASS)
            else:
                r.fact(f"{prefix}Kernel driver".strip(), "none bound", Severity.ERROR)
            if gpu.vram:
                r.fact(f"{prefix}VRAM".strip(), human_size(gpu.vram))

            cid = f"gpu.driver.{idx}" if multi else "gpu.driver"
            if not gpu.driver:
                r.check(
                    cid,
                    Severity.ERROR,
                    f"No kernel driver is bound to {gpu.name}",
                    "The GPU is present but no driver claimed it, so it cannot be used for "
                    "rendering. For NVIDIA cards this usually means the driver package is not "
                    "installed, the kernel module failed to build for the running kernel, or "
                    "the module is blacklisted. Check `dmesg` for driver errors.",
                    steps=ctx.solution("gpu.nvidia.driver") if gpu.vendor == "NVIDIA" else [],
                )
            else:
                r.ok(cid, f"{gpu.name} is driven by {gpu.driver}")

            if gpu.vendor == "NVIDIA":
                self._nvidia(ctx, r, gpu, idx if multi else None)
            elif gpu.vendor == "AMD" and gpu.driver == "radeon":
                r.check(
                    "gpu.amd.radeon",
                    Severity.INFO,
                    f"{gpu.name} uses the legacy 'radeon' kernel driver",
                    "The radeon driver has no Vulkan support. GCN 1/2 cards (HD 7000 / R9 200 "
                    "series) can use amdgpu instead by booting with radeon.si_support=0 "
                    "amdgpu.si_support=1 (or the cik_ variants), which enables RADV.",
                )

        if multi:
            names = ", ".join(g.name for g in gpus)
            r.check(
                "gpu.multiple",
                Severity.INFO,
                "Multiple GPUs detected",
                f"This system has {len(gpus)} GPUs ({names}). Games use the GPU selected by the "
                "compositor/driver by default, which on laptops is usually the integrated one. "
                "To run a game on the other GPU use DRI_PRIME=1 (Mesa) or prime-run / "
                "__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia (NVIDIA) in the "
                "game's launch options.",
            )

        self._opengl(ctx, r)
        return r

    def _nvidia(self, ctx: Context, r: ModuleResult, gpu: GPU, idx: int | None) -> None:
        prefix = f"GPU {idx} " if idx is not None else ""
        if gpu.driver == "nouveau":
            r.check(
                "gpu.nvidia.nouveau",
                Severity.WARNING,
                f"{gpu.name} uses the open-source nouveau driver",
                "nouveau provides Vulkan through Mesa's NVK driver, which works on Turing and newer "
                "GPUs but is still maturing. Most Linux gaming guides recommend NVIDIA's own driver "
                "(nvidia-open for RTX 20xx / GTX 16xx and newer) for performance and game "
                "compatibility. If games are slow or fail to start, the driver is the first thing "
                "to look at.",
                steps=ctx.solution("gpu.nvidia.driver"),
            )
            return
        if gpu.driver != "nvidia":
            return

        kernel_ver = ctx.read_line("/sys/module/nvidia/version")
        user_ver = nvidia_userspace_version(ctx)
        if kernel_ver:
            r.fact(f"{prefix}Driver version".strip(), kernel_ver, Severity.PASS)
        if kernel_ver and user_ver and kernel_ver != user_ver:
            r.check(
                "gpu.nvidia.version-mismatch",
                Severity.ERROR,
                "NVIDIA kernel module and user-space driver versions differ",
                f"The loaded kernel module is {kernel_ver} but the installed libraries are "
                f"{user_ver}. This almost always happens after a driver update without a reboot. "
                "Until they match, Vulkan and OpenGL will fail to initialise and games will not "
                "start.",
                "Reboot the system.",
            )
        elif kernel_ver and user_ver:
            r.ok("gpu.nvidia.version-mismatch", "NVIDIA kernel and user-space driver versions match")

        modeset = ctx.read_line("/sys/module/nvidia_drm/parameters/modeset")
        if modeset is not None:
            on = modeset.strip().upper() in ("Y", "1")
            r.fact(f"{prefix}DRM modeset".strip(), "enabled" if on else "disabled", Severity.PASS if on else Severity.WARNING)
            if not on and ctx.session == "wayland":
                r.check(
                    "gpu.nvidia.modeset",
                    Severity.WARNING,
                    "NVIDIA DRM kernel mode setting is disabled in a Wayland session",
                    "Wayland compositors need nvidia_drm.modeset=1 to drive an NVIDIA GPU properly. "
                    "Without it you may see a black screen, no hardware acceleration, or the "
                    "compositor falling back to software rendering. Recent driver packages enable "
                    "it by default; this system does not.",
                    steps=ctx.solution("gpu.nvidia.modeset"),
                )
            elif on:
                r.ok("gpu.nvidia.modeset", "NVIDIA DRM kernel mode setting is enabled")

    def _opengl(self, ctx: Context, r: ModuleResult) -> None:
        if ctx.session == "none":
            r.fact("OpenGL", "not tested (no display)")
            return
        if not ctx.which("glxinfo"):
            r.fact("OpenGL", "not tested (glxinfo not installed)")
            return
        res = ctx.run(["glxinfo", "-B"], timeout=15)
        if not res.ok:
            r.fact("OpenGL", "query failed", Severity.INFO)
            detail = (res.stderr or res.stdout).strip().splitlines()
            r.check(
                "gpu.opengl.query",
                Severity.INFO,
                "glxinfo could not query OpenGL",
                "This can be normal when gamedoctor runs without access to the display server "
                "(for example from a different session). If games do start, ignore this. "
                + (f"glxinfo said: {detail[-1]}" if detail else ""),
            )
            return
        renderer = self._grab(res.stdout, r"OpenGL renderer string:\s*(.+)")
        version = self._grab(res.stdout, r"OpenGL core profile version string:\s*(.+)") or self._grab(
            res.stdout, r"OpenGL version string:\s*(.+)"
        )
        mesa = re.search(r"Mesa (\d+\.\d+(?:\.\d+)?[^\s)]*)", res.stdout)
        gl_short = version.split()[0] if version else "unknown"
        if renderer:
            r.fact("OpenGL renderer", renderer)
        if mesa:
            r.fact("Mesa", mesa.group(1), Severity.PASS)
        software = bool(renderer and re.search(r"llvmpipe|softpipe|swrast", renderer, re.I))
        r.fact("OpenGL", gl_short, Severity.ERROR if software else Severity.PASS)
        if software:
            r.check(
                "gpu.opengl.software",
                Severity.ERROR,
                "OpenGL is using a CPU software renderer",
                f"The OpenGL renderer is '{renderer}', which is Mesa's software fallback. Your GPU "
                "driver is not being used for OpenGL. Native OpenGL games will run extremely "
                "slowly. Common causes: missing Mesa/NVIDIA user-space driver for this GPU, a "
                "kernel/user-space driver mismatch, or LIBGL_ALWAYS_SOFTWARE set.",
            )
        else:
            r.ok("gpu.opengl.software", "OpenGL is hardware accelerated")

    @staticmethod
    def _grab(text: str, pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

"""Vulkan loader, drivers (ICDs) for both architectures, layers and devices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.core.util import PCI_VENDORS, elf_class, parse_vulkaninfo_summary
from gamedoctor.diagnostics.base import Diagnostic

# (substring of the library file name, driver name, GPU vendor, is software renderer)
_ICD_LIBS: list[tuple[str, str, str | None, bool]] = [
    ("libvulkan_radeon", "RADV", "AMD", False),
    ("amdvlk", "AMDVLK", "AMD", False),
    ("libvulkan_intel_hasvk", "HASVK", "Intel", False),
    ("libvulkan_intel", "ANV", "Intel", False),
    ("libvulkan_nouveau", "NVK", "NVIDIA", False),
    ("libGLX_nvidia", "NVIDIA", "NVIDIA", False),
    ("nvidia", "NVIDIA", "NVIDIA", False),
    ("libvulkan_lvp", "llvmpipe (software)", None, True),
    ("libvulkan_swrast", "swrast (software)", None, True),
    ("libvulkan_virtio", "Venus (virtio)", "virtio", False),
    ("libvulkan_freedreno", "Turnip", "Qualcomm", False),
    ("libvulkan_panfrost", "PanVK", "ARM", False),
    ("libvulkan_broadcom", "V3DV", "Broadcom", False),
    ("libvulkan_asahi", "Honeykrisp", "Apple", False),
    ("libvulkan_dzn", "Dozen", None, False),
]

_HW_VENDORS = ("AMD", "NVIDIA", "Intel")


@dataclass
class ICD:
    manifest: Path
    library: str
    name: str
    vendor: str | None
    software: bool
    arch: int | None  # 32, 64 or None when the library could not be found
    path: Path | None
    api_version: str = ""

    @property
    def hardware(self) -> bool:
        return not self.software and self.arch is not None


@dataclass
class Layer:
    manifest: Path
    name: str
    library: str
    archs: set[int] = field(default_factory=set)
    enable_env: dict[str, str] = field(default_factory=dict)
    disable_env: dict[str, str] = field(default_factory=dict)

    @property
    def broken(self) -> bool:
        return bool(self.library) and not self.archs


def classify_library(library: str) -> tuple[str, str | None, bool]:
    base = Path(library).name
    for needle, name, vendor, software in _ICD_LIBS:
        if needle in base:
            return name, vendor, software
    return base, None, False


def resolve_library(ctx: Context, library: str, base_dir: Path) -> dict[int, Path]:
    """Return {arch: path} for every architecture the library resolves to."""
    if "/" in library:
        p = Path(library) if library.startswith("/") else (base_dir / library)
        cls = elf_class(p)
        return {cls: p} if cls else {}
    out: dict[int, Path] = {}
    for arch, path in ctx.find_library(library).items():
        cls = elf_class(path) or arch
        out.setdefault(cls, Path(path))
    for d in (ctx.env.get("LD_LIBRARY_PATH") or "").split(":"):
        if d and (Path(d) / library).exists():
            cls = elf_class(Path(d) / library)
            if cls:
                out.setdefault(cls, Path(d) / library)
    return out


def manifest_dirs(ctx: Context, kind: str) -> list[Path]:
    """Search path used by the Vulkan loader for ``icd.d`` / ``implicit_layer.d``."""
    dirs: list[Path] = []
    for d in ctx.config_dirs():
        dirs.append(d / "vulkan" / kind)
    dirs.append(ctx.user_config_dir() / "vulkan" / kind)
    for d in ctx.data_dirs():
        dirs.append(d / "vulkan" / kind)
    dirs.append(ctx.user_data_dir() / "vulkan" / kind)
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def _manifests(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.glob("*.json")))
    return files


def load_icds(ctx: Context) -> tuple[list[ICD], str | None]:
    override = ctx.env.get("VK_DRIVER_FILES") or ctx.env.get("VK_ICD_FILENAMES")
    if override:
        sources = [Path(p) for p in override.split(":") if p]
    else:
        sources = manifest_dirs(ctx, "icd.d")
    add = ctx.env.get("VK_ADD_DRIVER_FILES")
    if add:
        sources += [Path(p) for p in add.split(":") if p]

    icds: list[ICD] = []
    for manifest in _manifests(sources):
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            icds.append(ICD(manifest, "", manifest.name, None, False, None, None))
            continue
        icd = data.get("ICD") or {}
        library = icd.get("library_path") or ""
        name, vendor, software = classify_library(library)
        resolved = resolve_library(ctx, library, manifest.parent) if library else {}
        if not resolved:
            icds.append(ICD(manifest, library, name, vendor, software, None, None, icd.get("api_version", "")))
        for arch, path in sorted(resolved.items(), reverse=True):
            icds.append(ICD(manifest, library, name, vendor, software, arch, path, icd.get("api_version", "")))
    return icds, override


def load_layers(ctx: Context) -> list[Layer]:
    layers: list[Layer] = []
    for manifest in _manifests(manifest_dirs(ctx, "implicit_layer.d")):
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        entries = data.get("layers") or ([data["layer"]] if "layer" in data else [])
        for entry in entries:
            library = entry.get("library_path") or ""
            archs = set(resolve_library(ctx, library, manifest.parent)) if library else set()
            layers.append(
                Layer(
                    manifest,
                    entry.get("name", manifest.stem),
                    library,
                    archs,
                    entry.get("enable_environment") or {},
                    entry.get("disable_environment") or {},
                )
            )
    return layers


class VulkanDiagnostic(Diagnostic):
    name = "vulkan"
    title = "Vulkan"
    requires = ("system", "gpu", "steam")

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        gpu_vendors = {g.vendor for g in ctx.gpus if g.vendor in _HW_VENDORS}
        steam_present = bool(ctx.steam_installs)

        # -- loader ------------------------------------------------------------
        loader = ctx.find_library("libvulkan.so.1")
        instance_version, devices, vk_err = self._vulkaninfo(ctx)
        if 64 in loader:
            r.fact("Loader (64-bit)", f"{instance_version or 'found'}  {loader[64]}", Severity.PASS)
            r.ok("vulkan.loader", "Vulkan loader (64-bit) is installed")
        else:
            r.fact("Loader (64-bit)", "not found", Severity.CRITICAL)
            r.check(
                "vulkan.loader",
                Severity.CRITICAL,
                "The Vulkan loader (libvulkan.so.1) is not installed",
                "Every Vulkan application, including Proton's DXVK and VKD3D translation layers, "
                "starts by loading libvulkan.so.1. Without it no game can use Vulkan.",
                steps=ctx.solution("vulkan.loader"),
            )
        if 32 in loader:
            r.fact("Loader (32-bit)", str(loader[32]), Severity.PASS)
            r.ok("vulkan.loader.32bit", "Vulkan loader (32-bit) is installed")
        elif 64 in loader:
            r.fact("Loader (32-bit)", "not found", Severity.WARNING)
            r.check(
                "vulkan.loader.32bit",
                Severity.WARNING,
                "The 32-bit Vulkan loader is not installed",
                "Steam's container runtime ships its own 32-bit loader, so Proton games are "
                "usually fine. But 32-bit Vulkan applications run outside Steam (Lutris, Bottles, "
                "plain Wine, older native games) will fail to initialise Vulkan.",
                steps=ctx.solution("vulkan.loader.32bit"),
            )

        # -- ICDs ------------------------------------------------------------
        icds, override = load_icds(ctx)
        ctx_layers = load_layers(ctx)
        ctx.vulkan_layers = ctx_layers

        hw64 = [i for i in icds if i.hardware and i.arch == 64]
        hw32 = [i for i in icds if i.hardware and i.arch == 32]
        sw64 = [i for i in icds if i.software and i.arch == 64]
        broken = [i for i in icds if i.arch is None]

        for icd in [i for i in icds if i.arch == 64]:
            r.fact("Driver (64-bit)", f"{icd.name}  {icd.path}", Severity.PASS if not icd.software else None)
        for icd in [i for i in icds if i.arch == 32]:
            r.fact("Driver (32-bit)", f"{icd.name}  {icd.path}", Severity.PASS if not icd.software else None)
        if not icds:
            r.fact("Drivers", "no Vulkan driver manifests found", Severity.CRITICAL)

        if override:
            names = ", ".join(sorted({i.name for i in icds if i.arch is not None})) or "none (nothing usable)"
            r.fact("Driver override", override, Severity.WARNING)
            r.check(
                "vulkan.env.driver-override",
                Severity.WARNING,
                "A Vulkan driver override is set in the environment",
                f"VK_DRIVER_FILES / VK_ICD_FILENAMES is set to '{override}', so the loader ignores "
                f"every other installed driver and uses only: {names}. "
                + (
                    "Your system also has a different GPU vendor, which this override makes unusable. "
                    if gpu_vendors and not gpu_vendors.issubset({i.vendor for i in icds})
                    else ""
                )
                + "Overrides like this are usually left over from troubleshooting.",
                "Remove the variable from your shell profile / environment.d unless you set it on purpose.",
            )

        for icd in broken:
            r.check(
                f"vulkan.icd.broken.{icd.manifest.stem}",
                Severity.WARNING,
                f"Vulkan driver manifest points to a missing library ({icd.manifest.name})",
                f"{icd.manifest} references '{icd.library}', which does not exist. The loader "
                "skips it, but the stale manifest usually means a driver package was removed or "
                "half-installed and can cause confusing errors in game logs.",
                "Reinstall the driver package that owns the file, or delete the manifest if the driver is gone.",
            )

        # -- per-vendor driver presence --------------------------------------------
        vendors_to_check = sorted(gpu_vendors) if gpu_vendors else []
        if not vendors_to_check and not ctx.gpus:
            vendors_to_check = []
        for vendor in vendors_to_check:
            v64 = [i for i in hw64 if i.vendor == vendor]
            v32 = [i for i in hw32 if i.vendor == vendor]
            if not v64:
                sev = Severity.CRITICAL if not hw64 else Severity.ERROR
                r.check(
                    f"vulkan.icd.64bit.{vendor}",
                    sev,
                    f"No Vulkan driver installed for your {vendor} GPU",
                    f"This system has a {vendor} GPU, but no 64-bit Vulkan driver for it was found in "
                    "the loader's search path. "
                    + (
                        f"Only these drivers exist: {', '.join(sorted({i.name for i in hw64}))}. "
                        if hw64
                        else "Games using Vulkan, DXVK or VKD3D cannot run on this GPU. "
                    )
                    + ("A CPU software renderer (llvmpipe) is installed and would be used instead, which is unusably slow for games." if sw64 else ""),
                    steps=ctx.solution(f"vulkan.icd.64bit.{vendor}"),
                )
            else:
                r.ok(f"vulkan.icd.64bit.{vendor}", f"64-bit Vulkan driver for {vendor} found ({', '.join(i.name for i in v64)})")
                if not v32:
                    r.check(
                        f"vulkan.icd.32bit.{vendor}",
                        Severity.ERROR if steam_present else Severity.WARNING,
                        f"32-bit Vulkan driver for your {vendor} GPU not found",
                        f"Your 64-bit Vulkan driver ({', '.join(i.name for i in v64)}) is installed, but "
                        "no 32-bit build of it was found. Many Windows games run through Proton contain "
                        "32-bit components (launchers, older titles, anti-cheat helpers) and some native "
                        "Linux games are 32-bit. Those need a 32-bit Vulkan driver and will fail to start "
                        "or fall back to software rendering without one."
                        + (" Steam and Proton are installed on this system, so this is likely to affect you." if steam_present else ""),
                        steps=ctx.solution(f"vulkan.icd.32bit.{vendor}"),
                    )
                else:
                    r.ok(f"vulkan.icd.32bit.{vendor}", f"32-bit Vulkan driver for {vendor} found ({', '.join(i.name for i in v32)})")
            if len({i.name for i in v64}) > 1:
                names = " and ".join(sorted({i.name for i in v64}))
                r.check(
                    f"vulkan.icd.conflict.{vendor}",
                    Severity.WARNING,
                    f"Multiple Vulkan drivers installed for {vendor} ({names})",
                    "Both drivers are enumerated as separate Vulkan devices for the same GPU. Games "
                    "usually pick the first one, which is not always the one you expect, and some "
                    "titles misbehave when two devices share a GPU. Most users keep one driver.",
                    "For AMD, RADV is the default choice; AMD_VULKAN_ICD=RADV selects it explicitly. "
                    "Otherwise uninstall the driver you do not use.",
                )

        if not gpu_vendors and ctx.gpus and not hw64:
            r.check(
                "vulkan.icd.64bit",
                Severity.CRITICAL,
                "No hardware Vulkan driver found",
                "No Vulkan driver for a physical GPU is installed. Only "
                + (", ".join(i.name for i in sw64) if sw64 else "no drivers")
                + " were found.",
            )

        # -- devices as seen by the loader ----------------------------------
        if devices:
            for i, dev in enumerate(devices):
                dname = dev.get("deviceName", "unknown device")
                dtype = dev.get("deviceType", "")
                drv = dev.get("driverName", "")
                info = dev.get("driverInfo", "")
                api = dev.get("apiVersion", "")
                cpu = "CPU" in dtype
                detail = ", ".join(x for x in (f"{drv} {info}".strip(), f"Vulkan {api}" if api else "") if x)
                r.fact(f"Device {i}", f"{dname}  ({detail})", Severity.WARNING if cpu else Severity.PASS)
            hw_devices = [d for d in devices if "CPU" not in d.get("deviceType", "")]
            if hw_devices:
                r.ok("vulkan.device", f"Vulkan hardware acceleration works ({len(hw_devices)} device(s))")
            else:
                r.check(
                    "vulkan.device",
                    Severity.CRITICAL,
                    "No hardware Vulkan device detected, only a CPU software renderer",
                    "The only Vulkan device the loader can create is '"
                    + devices[0].get("deviceName", "llvmpipe")
                    + "', which renders on the CPU. Games using DXVK or VKD3D will fail or run at a "
                    "few frames per second. Your GPU's Vulkan driver is either not installed or not "
                    "working (kernel module not loaded, version mismatch, wrong driver for this GPU).",
                )
            seen_vendors = {PCI_VENDORS.get(d.get("vendorID", "").lower(), "") for d in hw_devices}
            for vendor in vendors_to_check:
                if any(i.vendor == vendor for i in hw64) and vendor not in seen_vendors:
                    r.check(
                        f"vulkan.device.{vendor}",
                        Severity.ERROR,
                        f"The {vendor} Vulkan driver is installed but reports no device",
                        f"A 64-bit Vulkan driver for {vendor} exists, yet vulkaninfo does not list a "
                        f"{vendor} device. The driver failed to initialise. Typical causes: the kernel "
                        "module is not loaded or does not match the user-space driver (reboot after "
                        "driver updates), the GPU is powered off (laptop hybrid graphics), or the "
                        "installed driver does not support this GPU generation.",
                        "Check `dmesg | grep -iE 'nvidia|amdgpu|i915|xe'` for driver errors and reboot if you recently updated.",
                    )
        elif ctx.which("vulkaninfo"):
            r.fact("Devices", "vulkaninfo found no usable device", Severity.ERROR)
            if hw64:
                r.check(
                    "vulkan.device",
                    Severity.ERROR,
                    "Vulkan drivers are installed but no device could be created",
                    "vulkaninfo failed to enumerate any Vulkan device even though driver(s) "
                    f"({', '.join(sorted({i.name for i in hw64}))}) are installed."
                    + (f" It reported: {vk_err}" if vk_err else "")
                    + " This usually means the kernel driver is not loaded or does not match the "
                    "user-space driver. Rebooting after a driver update fixes the most common case.",
                )
        else:
            r.fact("vulkaninfo", "not installed", absent=True)
            r.check(
                "vulkan.tools",
                Severity.INFO,
                "vulkaninfo is not installed",
                "gamedoctor could only inspect driver files, not ask the loader which devices actually "
                "work. Installing vulkan-tools gives a more reliable Vulkan diagnosis.",
                steps=ctx.solution("vulkan.tools"),
            )

        # -- layers ---------------------------------------------------------------
        if ctx_layers:
            r.fact("Implicit layers", ", ".join(sorted({l.name for l in ctx_layers})))
        for layer in [l for l in ctx_layers if l.broken]:
            r.check(
                f"vulkan.layer.broken.{layer.manifest.stem}",
                Severity.WARNING,
                f"Implicit Vulkan layer '{layer.name}' points to a missing library",
                f"{layer.manifest} references '{layer.library}', which does not exist. Implicit layers "
                "are loaded by every Vulkan application, so a broken one produces loader errors at "
                "every game start and can prevent Vulkan from initialising.",
                "Reinstall the package that provides the layer (MangoHud, vkBasalt, OBS, ...) or delete the stale manifest.",
            )
        for layer in ctx_layers:
            for var, val in layer.enable_env.items():
                if ctx.env.get(var) == val:
                    r.check(
                        f"vulkan.layer.enabled.{var}",
                        Severity.INFO,
                        f"{var}={val} is set globally, enabling the '{layer.name}' layer for every Vulkan app",
                        "This is fine if intentional, but an overlay or post-processing layer that is always "
                        "on is a frequent cause of crashes in specific games and of confusing bug reports.",
                    )
        return r

    @staticmethod
    def _vulkaninfo(ctx: Context) -> tuple[str | None, list[dict[str, str]], str | None]:
        if not ctx.which("vulkaninfo"):
            return None, [], None
        res = ctx.run(["vulkaninfo", "--summary"], timeout=25)
        instance, devices = parse_vulkaninfo_summary(res.stdout)
        err = None
        if not res.ok:
            lines = [l.strip() for l in (res.stderr + res.stdout).splitlines() if "ERROR" in l or "error" in l.lower()]
            err = lines[-1][:200] if lines else (res.error or f"exit code {res.returncode}")
        return instance, devices, err

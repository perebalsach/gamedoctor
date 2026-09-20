"""Small parsing helpers with no system side effects (easy to unit test)."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|(//[^\n]*)|(\[[^\]]*\])|([^\s"{}]+)')


def parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def parse_vdf(text: str) -> dict:
    """Parse Valve's KeyValues text format into nested dicts (values are strings)."""
    tokens: list[tuple[str, str]] = []
    for m in _VDF_TOKEN.finditer(text):
        if m.group(1) is not None:
            tokens.append(("str", m.group(1).replace('\\"', '"').replace("\\\\", "\\")))
        elif m.group(2):
            tokens.append(("brace", m.group(2)))
        elif m.group(5):
            tokens.append(("str", m.group(5)))
    pos = 0

    def block() -> dict:
        nonlocal pos
        out: dict = {}
        while pos < len(tokens):
            kind, val = tokens[pos]
            if kind == "brace":
                pos += 1
                if val == "}":
                    return out
                continue
            key = val
            pos += 1
            if pos >= len(tokens):
                out[key] = ""
                break
            kind2, val2 = tokens[pos]
            if kind2 == "brace" and val2 == "{":
                pos += 1
                out[key] = block()
            elif kind2 == "str":
                out[key] = val2
                pos += 1
            else:
                out[key] = ""
        return out

    return block()


def vdf_get(node, *path: str, default=None):
    """Case-insensitive nested lookup: vdf_get(d, "InstallConfigStore", "Software", ...)."""
    for key in path:
        if not isinstance(node, dict):
            return default
        match = next((v for k, v in node.items() if k.lower() == key.lower()), None)
        if match is None:
            return default
        node = match
    return node


def elf_class(path: str | Path) -> int | None:
    """Return 32 or 64 for an ELF file, None if unreadable or not ELF."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(5)
    except OSError:
        return None
    if len(head) < 5 or head[:4] != b"\x7fELF":
        return None
    return {1: 32, 2: 64}.get(head[4])


def parse_ldconfig(text: str) -> dict[str, dict[int, str]]:
    """Parse ``ldconfig -p`` into {soname: {64: path, 32: path}}."""
    out: dict[str, dict[int, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if "=>" not in line or "(" not in line:
            continue
        name, _, rest = line.partition(" ")
        flags, _, path = rest.partition("=>")
        arch = 64 if "x86-64" in flags or "AArch64" in flags or "64bit" in flags else 32
        out.setdefault(name, {}).setdefault(arch, path.strip())
    return out


@dataclass
class Mount:
    mount_point: str
    fstype: str
    source: str
    options: list[str]

    def has(self, opt: str) -> bool:
        return opt in self.options


def _unescape_mount(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def parse_mountinfo(text: str) -> list[Mount]:
    mounts: list[Mount] = []
    for line in text.splitlines():
        if " - " not in line:
            continue
        left, _, right = line.partition(" - ")
        lf = left.split()
        rf = right.split()
        if len(lf) < 6 or len(rf) < 2:
            continue
        opts = lf[5].split(",")
        if len(rf) >= 3:
            opts += rf[2].split(",")
        mounts.append(Mount(_unescape_mount(lf[4]), rf[0], _unescape_mount(rf[1]), opts))
    return mounts


def mount_for(mounts: list[Mount], path: str | Path) -> Mount | None:
    real = str(Path(path).resolve())
    best: Mount | None = None
    for m in mounts:
        mp = m.mount_point
        if real == mp or real.startswith(mp.rstrip("/") + "/") or mp == "/":
            if best is None or len(mp) > len(best.mount_point):
                best = m
    return best


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit in ("B", "KiB", "MiB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"


def parse_vulkaninfo_summary(text: str) -> tuple[str | None, list[dict[str, str]]]:
    """Parse ``vulkaninfo --summary``: returns (instance_version, [device dicts])."""
    instance = None
    devices: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_devices = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Vulkan Instance Version:"):
            instance = line.split(":", 1)[1].strip()
        elif line.startswith("Devices:"):
            in_devices = True
        elif in_devices and re.match(r"^GPU\d+:$", line):
            current = {}
            devices.append(current)
        elif in_devices and current is not None and "=" in line:
            key, _, value = line.partition("=")
            current[key.strip()] = value.strip()
    return instance, devices


PCI_VENDORS = {
    "0x1002": "AMD",
    "0x1022": "AMD",
    "0x10de": "NVIDIA",
    "0x8086": "Intel",
    "0x1af4": "virtio",
    "0x15ad": "VMware",
    "0x1234": "QEMU",
    "0x1a03": "ASPEED",
    "0x102b": "Matrox",
}


def lookup_pci_name(pci_ids_text: str, vendor: str, device: str) -> str | None:
    """Find a device name in pci.ids content. vendor/device like '0x10de'/'0x2786'."""
    v = vendor.lower().removeprefix("0x").zfill(4)
    d = device.lower().removeprefix("0x").zfill(4)
    in_vendor = False
    for line in pci_ids_text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith("\t"):
            in_vendor = line[:4].lower() == v
            continue
        if in_vendor and not line.startswith("\t\t"):
            body = line.strip()
            if body[:4].lower() == d:
                return body[4:].strip()
    return None


def pretty_gpu_name(raw: str | None, vendor_name: str) -> str | None:
    """'AD104 [GeForce RTX 4070]' -> 'NVIDIA GeForce RTX 4070'."""
    if not raw:
        return None
    m = re.search(r"\[([^\]]+)\]", raw)
    name = m.group(1) if m else raw
    name = name.strip()
    if vendor_name and not name.lower().startswith(vendor_name.lower()):
        name = f"{vendor_name} {name}"
    return name

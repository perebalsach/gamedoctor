"""Distribution knowledge: family detection and distro-specific remedies.

Diagnostics stay distro-independent; they only reference a solution *key* and
the platform layer turns it into commands for the running distribution.
"""

from __future__ import annotations

from gamedoctor.platform.solutions import SOLUTIONS, Step

_FAMILIES: dict[str, set[str]] = {
    "arch": {"arch", "archlinux", "cachyos", "manjaro", "endeavouros", "garuda", "steamos", "artix", "arcolinux"},
    "debian": {"debian", "ubuntu", "linuxmint", "pop", "zorin", "elementary", "neon", "kali", "raspbian", "tuxedo"},
    "fedora": {"fedora", "nobara", "bazzite", "rhel", "centos", "almalinux", "rocky", "ultramarine"},
    "suse": {"opensuse", "opensuse-tumbleweed", "opensuse-leap", "opensuse-slowroll", "sles", "sled"},
}

_IMMUTABLE_IDS = {"steamos", "bazzite", "silverblue", "kinoite", "aurora", "bluefin"}


def detect_family(os_release: dict[str, str]) -> str:
    ids = [os_release.get("ID", "").lower()]
    ids += os_release.get("ID_LIKE", "").lower().split()
    for candidate in ids:
        for family, members in _FAMILIES.items():
            if candidate in members or candidate == family:
                return family
    return "unknown"


def is_immutable(os_release: dict[str, str]) -> bool:
    import os

    if os_release.get("ID", "").lower() in _IMMUTABLE_IDS:
        return True
    variant = os_release.get("VARIANT_ID", "").lower()
    if variant in _IMMUTABLE_IDS:
        return True
    return os.path.exists("/run/ostree-booted")


def suggest(key: str, family: str, *, immutable: bool = False) -> list[Step]:
    entry = SOLUTIONS.get(key)
    if not entry:
        return []
    if immutable:
        return list(entry.get("immutable", []))
    return list(entry.get(family, entry.get("any", [])))

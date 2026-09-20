"""Remedies per distribution family, keyed by a stable issue key.

Keep this table free of diagnostic logic: it maps *what is missing* to *how to
install it here*. Contributors can extend it without touching the checks.

Every remedy is a :class:`Step`. ``gamedoctor fix`` executes runnable steps after
the user confirms each one; note-only steps are shown as manual instructions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One remedy line.

    ``run`` is a shell command (executed through ``sh -c``). An empty ``run`` with a
    ``note`` is a manual/informational step. ``options`` lists mutually exclusive
    commands the user has to choose between; ``note`` then explains the choice.
    """

    run: str = ""
    note: str = ""
    options: tuple[str, ...] = ()

    @property
    def runnable(self) -> bool:
        return bool(self.run) or bool(self.options)

    @property
    def commands(self) -> tuple[str, ...]:
        """All commands this step may execute (one of them for ``options``)."""
        if self.options:
            return self.options
        return (self.run,) if self.run else ()

    @property
    def needs_root(self) -> bool:
        return any(c.startswith("sudo ") or " sudo " in c for c in self.commands)

    def render(self) -> list[str]:
        """Display lines, e.g. ``["sudo pacman -S foo   # note"]`` or ``["# note"]``."""
        if self.options:
            lines = [f"# {self.note}"] if self.note else []
            return lines + list(self.options)
        if self.run:
            return [f"{self.run}   # {self.note}" if self.note else self.run]
        return [f"# {self.note}"] if self.note else []


_IMMUTABLE_NOTE = [
    Step(note="This system is image-based. Graphics drivers ship with the OS image;"),
    Step(note="check for a system update instead of installing packages."),
]

_DEBIAN_I386 = Step("sudo dpkg --add-architecture i386 && sudo apt update")

_NVIDIA_DEBIAN = Step(
    options=("sudo ubuntu-drivers install", "sudo apt install nvidia-driver"),
    note="ubuntu-drivers on Ubuntu; nvidia-driver on Debian (non-free repo)",
)
_NVIDIA_SUSE = Step(note="See https://en.opensuse.org/SDB:NVIDIA_drivers")

SOLUTIONS: dict[str, dict[str, list[Step]]] = {
    "vulkan.loader": {
        "arch": [Step("sudo pacman -S vulkan-icd-loader")],
        "debian": [Step("sudo apt install libvulkan1")],
        "fedora": [Step("sudo dnf install vulkan-loader")],
        "suse": [Step("sudo zypper install libvulkan1")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.loader.32bit": {
        "arch": [Step("sudo pacman -S lib32-vulkan-icd-loader")],
        "debian": [_DEBIAN_I386, Step("sudo apt install libvulkan1:i386")],
        "fedora": [Step("sudo dnf install vulkan-loader.i686")],
        "suse": [Step("sudo zypper install libvulkan1-32bit")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.tools": {
        "arch": [Step("sudo pacman -S vulkan-tools")],
        "debian": [Step("sudo apt install vulkan-tools")],
        "fedora": [Step("sudo dnf install vulkan-tools")],
        "suse": [Step("sudo zypper install vulkan-tools")],
        "immutable": [Step(note="vulkaninfo is usually preinstalled on image-based systems.")],
    },
    "vulkan.icd.64bit.AMD": {
        "arch": [Step("sudo pacman -S vulkan-radeon")],
        "debian": [Step("sudo apt install mesa-vulkan-drivers")],
        "fedora": [Step("sudo dnf install mesa-vulkan-drivers")],
        "suse": [Step("sudo zypper install libvulkan_radeon")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.icd.64bit.Intel": {
        "arch": [Step("sudo pacman -S vulkan-intel")],
        "debian": [Step("sudo apt install mesa-vulkan-drivers")],
        "fedora": [Step("sudo dnf install mesa-vulkan-drivers")],
        "suse": [Step("sudo zypper install libvulkan_intel")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.icd.64bit.NVIDIA": {
        "arch": [Step("sudo pacman -S nvidia-utils", "or nvidia-open + nvidia-utils")],
        "debian": [_NVIDIA_DEBIAN],
        "fedora": [Step("sudo dnf install akmod-nvidia xorg-x11-drv-nvidia", "RPM Fusion")],
        "suse": [_NVIDIA_SUSE],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.icd.32bit.AMD": {
        "arch": [Step("sudo pacman -S lib32-vulkan-radeon")],
        "debian": [_DEBIAN_I386, Step("sudo apt install mesa-vulkan-drivers:i386")],
        "fedora": [Step("sudo dnf install mesa-vulkan-drivers.i686")],
        "suse": [Step("sudo zypper install libvulkan_radeon-32bit")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.icd.32bit.Intel": {
        "arch": [Step("sudo pacman -S lib32-vulkan-intel")],
        "debian": [_DEBIAN_I386, Step("sudo apt install mesa-vulkan-drivers:i386")],
        "fedora": [Step("sudo dnf install mesa-vulkan-drivers.i686")],
        "suse": [Step("sudo zypper install libvulkan_intel-32bit")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "vulkan.icd.32bit.NVIDIA": {
        "arch": [Step("sudo pacman -S lib32-nvidia-utils")],
        "debian": [
            _DEBIAN_I386,
            Step(note="Install libnvidia-gl-<version>:i386 matching your driver version (sudo apt install ...)"),
        ],
        "fedora": [Step("sudo dnf install xorg-x11-drv-nvidia-libs.i686", "RPM Fusion")],
        "suse": [Step(note="Install the 32-bit NVIDIA G0x packages matching your driver")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "system.multilib": {
        "arch": [
            Step(note="Enable the [multilib] repository in /etc/pacman.conf, then:"),
            Step("sudo pacman -Syu lib32-glibc"),
        ],
        "debian": [_DEBIAN_I386, Step("sudo apt install libc6:i386")],
        "fedora": [Step("sudo dnf install glibc.i686")],
        "suse": [Step("sudo zypper install glibc-32bit")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "display.xwayland": {
        "arch": [Step("sudo pacman -S xorg-xwayland")],
        "debian": [Step("sudo apt install xwayland")],
        "fedora": [Step("sudo dnf install xorg-x11-server-Xwayland")],
        "suse": [Step("sudo zypper install xwayland")],
        "immutable": _IMMUTABLE_NOTE,
    },
    "gamemode.32bit": {
        "arch": [Step("sudo pacman -S lib32-gamemode")],
        "debian": [Step("sudo apt install libgamemode0:i386")],
        "fedora": [Step("sudo dnf install gamemode.i686")],
        "suse": [Step("sudo zypper install libgamemode0-32bit")],
    },
    "mangohud.32bit": {
        "arch": [Step("sudo pacman -S lib32-mangohud")],
        "debian": [Step("sudo apt install mangohud:i386")],
        "fedora": [Step("sudo dnf install mangohud.i686")],
        "suse": [Step("sudo zypper install mangohud-32bit")],
    },
    "gpu.nvidia.driver": {
        "arch": [
            Step(
                options=("sudo pacman -S nvidia-open", "sudo pacman -S nvidia"),
                note="nvidia-open for Turing (RTX 20xx / GTX 16xx) or newer; nvidia for older GPUs",
            )
        ],
        "debian": [_NVIDIA_DEBIAN],
        "fedora": [Step("sudo dnf install akmod-nvidia", "RPM Fusion")],
        "suse": [_NVIDIA_SUSE],
        "immutable": _IMMUTABLE_NOTE,
    },
    "gpu.nvidia.modeset": {
        "any": [
            Step(note="Add the kernel parameter  nvidia_drm.modeset=1"),
            Step(note="or create /etc/modprobe.d/nvidia.conf with:  options nvidia_drm modeset=1"),
            Step(note="then regenerate the initramfs and reboot."),
        ],
        "immutable": [Step(note="Add the kernel parameter nvidia_drm.modeset=1 with your bootloader tool.")],
    },
    "controller.udev": {
        "arch": [Step("sudo pacman -S game-devices-udev", "or: steam-devices")],
        "debian": [Step("sudo apt install steam-devices")],
        "fedora": [Step("sudo dnf install steam-devices")],
        "suse": [Step("sudo zypper install steam-devices")],
        "immutable": [
            Step(note="The udev rules ship with the OS image; replug the controller or check for a system update.")
        ],
    },
    "controller.uinput.load": {
        "any": [
            Step("sudo modprobe uinput"),
            Step("echo uinput | sudo tee /etc/modules-load.d/uinput.conf", "make it permanent"),
        ],
        "immutable": [Step("sudo modprobe uinput")],
    },
    "audio.session-manager": {
        "any": [Step("systemctl --user enable --now wireplumber")],
    },
    "audio.pulse-compat": {
        "any": [Step("systemctl --user enable --now pipewire-pulse")],
    },
    "audio.server": {
        "any": [Step("systemctl --user enable --now pipewire pipewire-pulse wireplumber")],
    },
    "gamemode.daemon": {
        "any": [
            Step("gamemoded -t", "run the daemon's self-test to see why it fails"),
            Step("systemctl --user restart gamemoded", "only if your distribution ships the user unit"),
        ],
    },
}

"""Game controllers: evdev detection, kernel driver, and the device permissions
Steam Input and games need (evdev node, hidraw node, /dev/uinput)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.diagnostics.base import Diagnostic

BUS_NAMES = {0x03: "USB", 0x05: "Bluetooth", 0x06: "virtual", 0x19: "platform"}

# Vendors whose controllers Steam talks to over hidraw for full support (gyro, rumble, lightbar, touchpad).
HIDRAW_VENDORS = {0x054C: "Sony", 0x057E: "Nintendo", 0x28DE: "Valve", 0x045E: "Microsoft"}
VENDOR_NAMES = {
    0x054C: "Sony",
    0x057E: "Nintendo",
    0x28DE: "Valve",
    0x045E: "Microsoft",
    0x046D: "Logitech",
    0x2DC8: "8BitDo",
    0x0079: "DragonRise",
    0x0E6F: "PDP",
    0x1532: "Razer",
    0x24C6: "PowerA",
    0x3537: "GameSir",
    0x0F0D: "Hori",
    0x044F: "Thrustmaster",
    0x1038: "SteelSeries",
}
STEAM_VIRTUAL = (0x28DE, 0x11FF)  # Steam Input's emulated Xbox 360 pad

BTN_JOYSTICK = 0x120
BTN_GAMEPAD_FIRST, BTN_GAMEPAD_LAST = 0x130, 0x13E
ABS_X = 0


@dataclass
class Controller:
    name: str
    vendor: int
    product: int
    bus: int
    event_node: Path
    driver: str | None = None
    hidraw_nodes: list[Path] = field(default_factory=list)
    js_node: Path | None = None
    virtual: bool = False
    event_ok: bool = True
    hidraw_ok: bool = True

    @property
    def is_steam_virtual(self) -> bool:
        return (self.vendor, self.product) == STEAM_VIRTUAL

    @property
    def bus_name(self) -> str:
        return BUS_NAMES.get(self.bus, f"bus 0x{self.bus:02x}")

    @property
    def display_name(self) -> str:
        brand = VENDOR_NAMES.get(self.vendor)
        if brand and brand.lower() not in self.name.lower():
            return f"{brand} {self.name}"
        return self.name


def has_bit(mask: str, bit: int) -> bool:
    """Test a bit in a sysfs capability bitmask (space-separated hex words, most significant first)."""
    words = mask.split()
    if not words:
        return False
    index = bit // 64
    if index >= len(words):
        return False
    try:
        word = int(words[-1 - index], 16)
    except ValueError:
        return False
    return bool(word >> (bit % 64) & 1)


def looks_like_gamepad(key_mask: str, abs_mask: str) -> bool:
    if not has_bit(abs_mask, ABS_X):
        return False
    if has_bit(key_mask, BTN_JOYSTICK):
        return True
    return any(has_bit(key_mask, b) for b in range(BTN_GAMEPAD_FIRST, BTN_GAMEPAD_LAST + 1))


def _read_hex(ctx: Context, path: Path) -> int:
    try:
        return int(ctx.read_line(path) or "0", 16)
    except ValueError:
        return 0


def enumerate_controllers(ctx: Context, sys_input: Path = Path("/sys/class/input"), dev: Path = Path("/dev")) -> list[Controller]:
    controllers: list[Controller] = []
    seen: set[str] = set()
    for event in sorted(sys_input.glob("event*"), key=lambda p: int(p.name[5:]) if p.name[5:].isdigit() else 0):
        device = event / "device"
        key_mask = ctx.read_line(device / "capabilities" / "key") or ""
        abs_mask = ctx.read_line(device / "capabilities" / "abs") or ""
        if not looks_like_gamepad(key_mask, abs_mask):
            continue
        name = ctx.read_line(device / "name") or "Unknown controller"
        vendor = _read_hex(ctx, device / "id" / "vendor")
        product = _read_hex(ctx, device / "id" / "product")
        bus = _read_hex(ctx, device / "id" / "bustype")
        uniq = ctx.read_line(device / "uniq") or ""
        phys = ctx.read_line(device / "phys") or ""
        identity = f"{vendor:04x}:{product:04x}:{uniq or phys or event.name}"
        if identity in seen:
            continue
        seen.add(identity)

        real = device.resolve()  # .../<hid or usb interface>/input/inputN
        parent = real.parent.parent  # the HID or USB interface device that owns the input node
        driver = (parent / "driver").resolve().name if (parent / "driver").exists() else None
        hidraws = [dev / h.name for h in sorted((parent / "hidraw").glob("hidraw*"))] if (parent / "hidraw").is_dir() else []
        js = next((dev / "input" / j.name for j in device.glob("js*")), None)
        ctrl = Controller(
            name=name,
            vendor=vendor,
            product=product,
            bus=bus,
            event_node=dev / "input" / event.name,
            driver=driver,
            hidraw_nodes=hidraws,
            js_node=js,
            virtual="/virtual/" in str(real) or bus == 0x06,
        )
        ctrl.event_ok = os.access(ctrl.event_node, os.R_OK | os.W_OK) if ctrl.event_node.exists() else False
        ctrl.hidraw_ok = all(os.access(h, os.R_OK | os.W_OK) for h in hidraws) if hidraws else True
        controllers.append(ctrl)
    return controllers


class ControllersDiagnostic(Diagnostic):
    name = "controllers"
    title = "Controllers"
    requires = ("system", "steam")

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        controllers = enumerate_controllers(ctx)
        physical = [c for c in controllers if not c.is_steam_virtual]
        virtual = [c for c in controllers if c.is_steam_virtual]

        if not physical:
            r.fact("Controller", "none connected", absent=True)
        for i, c in enumerate(physical):
            slug = f"{c.vendor:04x}-{c.product:04x}-{i}"
            detail = ", ".join(x for x in (c.bus_name, f"driver {c.driver}" if c.driver else "") if x)
            status = Severity.PASS
            if not c.event_ok:
                status = Severity.ERROR
            elif not c.hidraw_ok:
                status = Severity.WARNING
            r.fact("Controller", f"{c.display_name}  ({detail})", status)

            if c.event_ok:
                r.ok(f"controller.access.{slug}", f"{c.display_name} is accessible")
            else:
                r.check(
                    f"controller.access.{slug}",
                    Severity.ERROR,
                    f"No permission to read {c.display_name} ({c.event_node})",
                    "The controller is detected by the kernel, but your user cannot open its input "
                    "device, so Steam, SDL and games will not see it at all. On a normal desktop login, "
                    "systemd-logind grants the active seat access to input devices automatically. This "
                    "fails when the session is not registered with logind (some display managers, "
                    "startx from a TTY, SSH, or running from a container).",
                    "Check `loginctl show-session $XDG_SESSION_ID -p Active` reports Active=yes. As a "
                    "workaround, add your user to the 'input' group and log in again.",
                )

            if c.hidraw_nodes and not c.hidraw_ok:
                r.check(
                    f"controller.hidraw.{slug}",
                    Severity.WARNING,
                    f"Steam cannot access the raw HID device of {c.display_name}",
                    f"Steam Input talks to {VENDOR_NAMES.get(c.vendor, 'this')} controllers directly over "
                    f"hidraw ({', '.join(str(h) for h in c.hidraw_nodes)}) for gyro, rumble, lightbar, "
                    "touchpad and, for some models, detection itself. The node is not accessible to your "
                    "user, so the controller may be missing in Steam or lose features. Games run through "
                    "SDL are affected the same way.",
                    "Install the udev rules that grant access to game devices, then replug the controller.",
                    steps=ctx.solution("controller.udev"),
                )
            elif c.hidraw_nodes:
                r.ok(f"controller.hidraw.{slug}", f"Raw HID access to {c.display_name} works")

            if c.bus == 0x05 and c.vendor == 0x045E and c.driver in (None, "hid-generic"):
                r.check(
                    f"controller.xbox-bt.{slug}",
                    Severity.INFO,
                    f"{c.display_name} is connected over Bluetooth with the generic HID driver",
                    "Xbox controllers over Bluetooth work with the kernel's generic driver, but rumble, "
                    "battery reporting and correct button mapping on older kernels need the xpadneo "
                    "driver. If the controller behaves oddly, that is the usual fix.",
                )

        if virtual:
            r.fact("Steam Input", f"active ({len(virtual)} virtual controller(s))", Severity.PASS)
            r.check(
                "controller.steam-input",
                Severity.INFO,
                "Steam Input is emulating a controller",
                "Steam is running and exposes the physical controller as a virtual Xbox 360 pad. Games "
                "launched from Steam see the virtual device while the real one is hidden. Tools like "
                "`evtest` or non-Steam games may then show two controllers or an unexpected one.",
            )

        self._uinput(ctx, r)
        return r

    def _uinput(self, ctx: Context, r: ModuleResult) -> None:
        uinput = Path("/dev/uinput")
        if not ctx.steam_installs:
            return
        if not uinput.exists():
            r.fact("uinput", "/dev/uinput missing", Severity.WARNING)
            r.check(
                "controller.uinput",
                Severity.WARNING,
                "/dev/uinput does not exist",
                "Steam Input creates its virtual controllers through the uinput kernel interface. "
                "Without it, controller remapping, Steam Deck-style configurations and support for "
                "PlayStation/Switch controllers in many games do not work. The module is usually "
                "loaded on demand; here it is missing entirely.",
                "Load the uinput module and make it load at boot.",
                steps=ctx.solution("controller.uinput.load"),
            )
        elif not os.access(uinput, os.W_OK):
            r.fact("uinput", "/dev/uinput not writable", Severity.WARNING)
            r.check(
                "controller.uinput",
                Severity.WARNING,
                "Your user cannot write to /dev/uinput",
                "Steam Input needs write access to /dev/uinput to create virtual controllers. Without "
                "it Steam falls back to passing the raw controller through, and remapping, "
                "gyro-to-mouse and per-game controller layouts silently stop working.",
                "Install the game-device udev rules (they tag /dev/uinput with 'uaccess'), then log out and in.",
                steps=ctx.solution("controller.udev"),
            )
        else:
            r.fact("uinput", "/dev/uinput writable (Steam Input can create virtual controllers)", Severity.PASS)
            r.ok("controller.uinput", "/dev/uinput is accessible")

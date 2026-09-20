import os
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.diagnostics.controllers import enumerate_controllers, has_bit, looks_like_gamepad

KEYBOARD_KEY = "1000000000007 ff9f207ac14057ff febeffdff"
CONSUMER_KEY = "733fff 0 0 483ffff17aff32d bfd4444600000"
# DualSense: BTN_SOUTH..BTN_THUMBR (0x130-0x13e) set -> word index 4 holds bits 256..319
GAMEPAD_KEY = "7fdb000000000000 0 0 0 0"
GAMEPAD_ABS = "3003f"


def test_has_bit_indexing():
    assert has_bit(GAMEPAD_KEY, 0x130)  # BTN_SOUTH
    assert not has_bit(GAMEPAD_KEY, 0x12f)
    assert has_bit("1", 0)
    assert not has_bit("", 5)
    assert not has_bit("zz", 1)


def test_keyboards_and_media_keys_are_not_gamepads():
    assert not looks_like_gamepad(KEYBOARD_KEY, "0")
    assert not looks_like_gamepad(CONSUMER_KEY, "0")
    assert not looks_like_gamepad(GAMEPAD_KEY, "0")  # no axes: e.g. a motion-sensor-less button box
    assert looks_like_gamepad(GAMEPAD_KEY, GAMEPAD_ABS)
    assert looks_like_gamepad("100000000 0 0 0 0", "1")  # BTN_JOYSTICK (0x120 = bit 288 -> word 4, bit 32)


def _fake_device(root: Path, n: int, name: str, vid: str, pid: str, bus: str, key: str, abs_: str, driver: str | None, hidraw: str | None, virtual=False):
    base = root / "sys/devices" / ("virtual/input" if virtual else f"pci0000:00/usb1/1-1/1-1:1.0/0003:{vid.upper()}:{pid.upper()}.0001")
    hid = base
    inp = hid / "input" / f"input{n}"
    (inp / "capabilities").mkdir(parents=True)
    (inp / "id").mkdir()
    (inp / "name").write_text(name + "\n")
    (inp / "uniq").write_text("aa:bb\n")
    (inp / "capabilities/key").write_text(key + "\n")
    (inp / "capabilities/abs").write_text(abs_ + "\n")
    (inp / "id/vendor").write_text(vid + "\n")
    (inp / "id/product").write_text(pid + "\n")
    (inp / "id/bustype").write_text(bus + "\n")
    (inp / f"js{n}").mkdir()
    if driver:
        drv = root / "sys/bus/hid/drivers" / driver
        drv.mkdir(parents=True, exist_ok=True)
        (hid / "driver").symlink_to(drv)
    if hidraw:
        (hid / "hidraw" / hidraw).mkdir(parents=True)
    # real layout: /sys/class/input/eventN -> .../inputN/eventN, and eventN/device -> inputN
    evdir = inp / f"event{n}"
    evdir.mkdir()
    (evdir / "device").symlink_to(inp)
    cls = root / "sys/class/input"
    cls.mkdir(parents=True, exist_ok=True)
    (cls / f"event{n}").symlink_to(evdir)
    dev = root / "dev/input"
    dev.mkdir(parents=True, exist_ok=True)
    (dev / f"event{n}").write_text("")
    if hidraw:
        (root / "dev" / hidraw).write_text("")


def test_enumerate_controllers_with_permissions(tmp_path: Path):
    _fake_device(tmp_path, 3, "Keyboard", "1234", "0001", "0003", KEYBOARD_KEY, "0", "hid-generic", None)
    _fake_device(tmp_path, 5, "DualSense Wireless Controller", "054c", "0ce6", "0003", GAMEPAD_KEY, GAMEPAD_ABS, "hid-playstation", "hidraw4")
    _fake_device(tmp_path, 7, "Microsoft X-Box 360 pad 0", "28de", "11ff", "0006", GAMEPAD_KEY, GAMEPAD_ABS, None, None, virtual=True)
    os.chmod(tmp_path / "dev/hidraw4", 0)

    ctx = Context({"HOME": str(tmp_path), "PATH": "/nonexistent"})
    found = enumerate_controllers(ctx, tmp_path / "sys/class/input", tmp_path / "dev")
    assert [c.name for c in found] == ["DualSense Wireless Controller", "Microsoft X-Box 360 pad 0"]
    ds = found[0]
    assert ds.display_name == "Sony DualSense Wireless Controller"
    assert ds.driver == "hid-playstation"
    assert ds.bus_name == "USB"
    assert ds.event_ok
    assert ds.hidraw_nodes == [tmp_path / "dev/hidraw4"]
    assert not ds.hidraw_ok
    assert ds.js_node == tmp_path / "dev/input/js5"
    steam = found[1]
    assert steam.is_steam_virtual and steam.virtual

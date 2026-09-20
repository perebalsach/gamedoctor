from pathlib import Path

from gamedoctor.core.util import (
    elf_class,
    human_size,
    lookup_pci_name,
    mount_for,
    parse_ldconfig,
    parse_mountinfo,
    parse_os_release,
    parse_vdf,
    parse_vulkaninfo_summary,
    pretty_gpu_name,
    vdf_get,
)


def test_parse_os_release():
    text = 'NAME="CachyOS Linux"\nPRETTY_NAME="CachyOS"\nID=cachyos\nID_LIKE=arch\n# comment\n'
    osr = parse_os_release(text)
    assert osr["PRETTY_NAME"] == "CachyOS"
    assert osr["ID_LIKE"] == "arch"


def test_parse_vdf_nested_and_case_insensitive_lookup():
    text = '''
"libraryfolders"
{
    "0"
    {
        "path"      "/home/u/.local/share/Steam"
        "apps"
        {
            "1245620"   "55123337185"
        }
    }
    "1"
    {
        "path"      "/mnt/games"    // trailing comment
    }
}
'''
    data = parse_vdf(text)
    folders = vdf_get(data, "LibraryFolders")
    assert folders["0"]["path"] == "/home/u/.local/share/Steam"
    assert folders["1"]["path"] == "/mnt/games"
    assert vdf_get(data, "libraryfolders", "0", "apps", "1245620") == "55123337185"
    assert vdf_get(data, "nope", default="x") == "x"


def test_parse_vdf_escaped_quotes():
    data = parse_vdf(r'"k" "a \"quoted\" value"')
    assert data["k"] == 'a "quoted" value'


def test_elf_class(tmp_path: Path):
    p32 = tmp_path / "lib32.so"
    p32.write_bytes(b"\x7fELF\x01" + b"\0" * 20)
    p64 = tmp_path / "lib64.so"
    p64.write_bytes(b"\x7fELF\x02" + b"\0" * 20)
    txt = tmp_path / "not.so"
    txt.write_text("hello")
    assert elf_class(p32) == 32
    assert elf_class(p64) == 64
    assert elf_class(txt) is None
    assert elf_class(tmp_path / "missing") is None


def test_parse_ldconfig():
    text = """\t3 libs found in cache `/etc/ld.so.cache'
\tlibvulkan.so.1 (libc6,x86-64) => /usr/lib/libvulkan.so.1
\tlibvulkan.so.1 (libc6) => /usr/lib32/libvulkan.so.1
\tlibc.so.6 (libc6,x86-64, OS ABI: Linux 4.4.0) => /usr/lib/libc.so.6
"""
    libs = parse_ldconfig(text)
    assert libs["libvulkan.so.1"] == {64: "/usr/lib/libvulkan.so.1", 32: "/usr/lib32/libvulkan.so.1"}
    assert libs["libc.so.6"] == {64: "/usr/lib/libc.so.6"}


def test_parse_mountinfo_and_lookup():
    text = (
        "40 1 0:33 /@ / rw,noatime shared:1 - btrfs /dev/nvme0n1p2 rw,compress=zstd:1\n"
        "90 40 8:17 / /mnt/games\\040drive rw,nosuid,noexec shared:50 - fuseblk /dev/sdb1 rw,user_id=0\n"
    )
    mounts = parse_mountinfo(text)
    assert mounts[1].mount_point == "/mnt/games drive"
    assert mounts[1].fstype == "fuseblk"
    assert mounts[1].has("noexec")
    assert mount_for(mounts, "/mnt/games drive/SteamLibrary").fstype == "fuseblk"
    assert mount_for(mounts, "/usr/lib").fstype == "btrfs"


def test_parse_vulkaninfo_summary():
    text = """==========
VULKANINFO
==========

Vulkan Instance Version: 1.4.357

Devices:
========
GPU0:
\tapiVersion         = 1.4.351
\tvendorID           = 0x10de
\tdeviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName         = NVIDIA GeForce RTX 4070
\tdriverName         = NVIDIA
GPU1:
\tdeviceType         = PHYSICAL_DEVICE_TYPE_CPU
\tdeviceName         = llvmpipe (LLVM 19.1.7, 256 bits)
"""
    version, devices = parse_vulkaninfo_summary(text)
    assert version == "1.4.357"
    assert len(devices) == 2
    assert devices[0]["deviceName"] == "NVIDIA GeForce RTX 4070"
    assert "CPU" in devices[1]["deviceType"]


def test_pci_lookup_and_pretty_name():
    ids = "# pci.ids\n10de  NVIDIA Corporation\n\t2786  AD104 [GeForce RTX 4070]\n\t\t1043 8875  Sub\n1002  AMD\n\t747e  Navi 32 [Radeon RX 7700 XT / 7800 XT]\n"
    assert lookup_pci_name(ids, "0x10de", "0x2786") == "AD104 [GeForce RTX 4070]"
    assert lookup_pci_name(ids, "0x1002", "0x747e").startswith("Navi 32")
    assert lookup_pci_name(ids, "0x1002", "0x0000") is None
    assert pretty_gpu_name("AD104 [GeForce RTX 4070]", "NVIDIA") == "NVIDIA GeForce RTX 4070"
    assert pretty_gpu_name("Radeon RX 7800 XT", "AMD") == "AMD Radeon RX 7800 XT"


def test_human_size():
    assert human_size(16 * 1024**3) == "16.0 GiB"
    assert human_size(512) == "512 B"

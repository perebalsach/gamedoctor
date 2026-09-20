import json
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.diagnostics.vulkan import classify_library, load_icds, load_layers


def _elf(path: Path, bits: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF" + bytes([1 if bits == 32 else 2]) + b"\0" * 20)


def _ctx(tmp_path: Path, ldconfig: dict) -> Context:
    env = {
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_DIRS": str(tmp_path / "share"),
        "XDG_CONFIG_DIRS": str(tmp_path / "etc"),
        "XDG_DATA_HOME": str(tmp_path / "home/.local/share"),
        "XDG_CONFIG_HOME": str(tmp_path / "home/.config"),
        "PATH": "/nonexistent",
    }
    ctx = Context(env)
    ctx.__dict__["ldconfig"] = ldconfig  # bypass the cached_property probe
    ctx.system_config_dirs = []  # isolate from the real /etc
    return ctx


def test_classify_library():
    assert classify_library("/usr/lib/libvulkan_radeon.so") == ("RADV", "AMD", False)
    assert classify_library("libGLX_nvidia.so.0") == ("NVIDIA", "NVIDIA", False)
    assert classify_library("/usr/lib/libvulkan_intel_hasvk.so")[0] == "HASVK"
    assert classify_library("/usr/lib/libvulkan_lvp.so")[2] is True


def test_bare_library_name_expands_to_both_architectures(tmp_path: Path):
    lib64 = tmp_path / "usr/lib/libGLX_nvidia.so.0"
    lib32 = tmp_path / "usr/lib32/libGLX_nvidia.so.0"
    _elf(lib64, 64)
    _elf(lib32, 32)
    icd_dir = tmp_path / "share/vulkan/icd.d"
    icd_dir.mkdir(parents=True)
    (icd_dir / "nvidia_icd.json").write_text(json.dumps({"ICD": {"library_path": "libGLX_nvidia.so.0", "api_version": "1.4.351"}}))
    ctx = _ctx(tmp_path, {"libGLX_nvidia.so.0": {64: str(lib64), 32: str(lib32)}})
    icds, override = load_icds(ctx)
    assert override is None
    assert sorted(i.arch for i in icds) == [32, 64]
    assert all(i.name == "NVIDIA" and i.vendor == "NVIDIA" and i.hardware for i in icds)


def test_absolute_paths_and_broken_manifest(tmp_path: Path):
    radv64 = tmp_path / "usr/lib/libvulkan_radeon.so"
    _elf(radv64, 64)
    icd_dir = tmp_path / "share/vulkan/icd.d"
    icd_dir.mkdir(parents=True)
    (icd_dir / "radeon_icd.x86_64.json").write_text(json.dumps({"ICD": {"library_path": str(radv64)}}))
    (icd_dir / "radeon_icd.i686.json").write_text(json.dumps({"ICD": {"library_path": str(tmp_path / "usr/lib32/libvulkan_radeon.so")}}))
    ctx = _ctx(tmp_path, {})
    icds, _ = load_icds(ctx)
    good = [i for i in icds if i.arch == 64]
    broken = [i for i in icds if i.arch is None]
    assert len(good) == 1 and good[0].name == "RADV"
    assert len(broken) == 1 and broken[0].manifest.name == "radeon_icd.i686.json"


def test_driver_override_env_replaces_search_path(tmp_path: Path):
    lvp = tmp_path / "usr/lib/libvulkan_lvp.so"
    _elf(lvp, 64)
    manifest = tmp_path / "custom/lvp.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"ICD": {"library_path": str(lvp)}}))
    ctx = _ctx(tmp_path, {})
    ctx.env["VK_DRIVER_FILES"] = str(manifest)
    icds, override = load_icds(ctx)
    assert override == str(manifest)
    assert [i.name for i in icds] == ["llvmpipe (software)"]
    assert icds[0].software


def test_layers_detect_missing_library(tmp_path: Path):
    layer_dir = tmp_path / "share/vulkan/implicit_layer.d"
    layer_dir.mkdir(parents=True)
    okay = tmp_path / "usr/lib/mangohud/libMangoHud.so"
    _elf(okay, 64)
    (layer_dir / "MangoHud.x86_64.json").write_text(
        json.dumps({"layer": {"name": "VK_LAYER_MANGOHUD_overlay_x86_64", "library_path": str(okay), "enable_environment": {"MANGOHUD": "1"}}})
    )
    (layer_dir / "stale.json").write_text(json.dumps({"layer": {"name": "VK_LAYER_stale", "library_path": "/nope/libstale.so"}}))
    layers = load_layers(_ctx(tmp_path, {}))
    by_name = {l.name: l for l in layers}
    assert by_name["VK_LAYER_MANGOHUD_overlay_x86_64"].archs == {64}
    assert not by_name["VK_LAYER_MANGOHUD_overlay_x86_64"].broken
    assert by_name["VK_LAYER_stale"].broken

"""Shared, lazily cached view of the machine that every diagnostic reads from.

Modules never shell out or read sysfs directly for shared facts; they ask the
context so that probes run once and results can be reused (and mocked in tests).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from gamedoctor.core.util import (
    Mount,
    mount_for,
    parse_ldconfig,
    parse_mountinfo,
    parse_os_release,
)
from gamedoctor.platform import detect_family, is_immutable, suggest
from gamedoctor.platform.solutions import Step


@dataclass
class CmdResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error: str = ""  # "not found", "timeout", ...

    @property
    def text(self) -> str:
        return self.stdout or self.stderr


class Context:
    def __init__(self, env: dict[str, str] | None = None, *, debug: bool = False):
        self.env: dict[str, str] = dict(os.environ if env is None else env)
        self.debug = debug
        self.home = Path(self.env.get("HOME") or Path.home())
        self.uid = os.getuid()

        # Results shared between modules (populated in dependency order).
        self.session: str = "unknown"
        self.gpus: list[Any] = []
        self.vulkan_layers: list[Any] = []
        self.steam_installs: list[Any] = []
        self.steam_libraries: list[Path] = []
        self.proton_tools: list[Any] = []

    # -- processes and files -------------------------------------------------

    def which(self, name: str) -> str | None:
        return shutil.which(name, path=self.env.get("PATH"))

    def run(self, args: list[str], timeout: float = 10, env: dict[str, str] | None = None) -> CmdResult:
        if self.which(args[0]) is None and not os.path.isabs(args[0]):
            return CmdResult(False, error="not found")
        run_env = dict(self.env)
        run_env["LC_ALL"] = "C"
        if env:
            run_env.update(env)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                env=run_env,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return CmdResult(False, error="timeout")
        except OSError as exc:
            return CmdResult(False, error=str(exc))
        return CmdResult(proc.returncode == 0, proc.stdout, proc.stderr, proc.returncode)

    def read(self, path: str | Path) -> str | None:
        try:
            return Path(path).read_text(errors="replace")
        except OSError:
            return None

    def read_line(self, path: str | Path) -> str | None:
        text = self.read(path)
        return text.strip().splitlines()[0].strip() if text and text.strip() else None

    # -- cached system probes ------------------------------------------------

    @cached_property
    def os_release(self) -> dict[str, str]:
        for candidate in ("/etc/os-release", "/usr/lib/os-release"):
            text = self.read(candidate)
            if text:
                return parse_os_release(text)
        return {}

    @cached_property
    def distro_family(self) -> str:
        return detect_family(self.os_release)

    @cached_property
    def immutable(self) -> bool:
        return is_immutable(self.os_release)

    @cached_property
    def ldconfig(self) -> dict[str, dict[int, str]]:
        res = self.run(["ldconfig", "-p"], timeout=15)
        if not res.ok:
            res = self.run(["/sbin/ldconfig", "-p"], timeout=15)
        return parse_ldconfig(res.stdout) if res.ok else {}

    def find_library(self, soname: str) -> dict[int, str]:
        """{64: path, 32: path} for a library known to the dynamic loader."""
        return dict(self.ldconfig.get(soname, {}))

    @cached_property
    def mounts(self) -> list[Mount]:
        text = self.read("/proc/self/mountinfo") or ""
        return parse_mountinfo(text)

    def mount_for(self, path: str | Path) -> Mount | None:
        return mount_for(self.mounts, path)

    @cached_property
    def processes(self) -> set[str]:
        """Command names of processes owned by the current user."""
        names: set[str] = set()
        try:
            pids = [p for p in os.listdir("/proc") if p.isdigit()]
        except OSError:
            return names
        for pid in pids:
            try:
                if os.stat(f"/proc/{pid}").st_uid != self.uid:
                    continue
                with open(f"/proc/{pid}/comm") as fh:
                    names.add(fh.read().strip())
            except OSError:
                continue
        return names

    @cached_property
    def kernel_modules(self) -> set[str]:
        text = self.read("/proc/modules") or ""
        return {line.split()[0] for line in text.splitlines() if line.strip()}

    def user_service_active(self, unit: str) -> bool | None:
        """True/False from systemd, None if systemd is unavailable."""
        res = self.run(["systemctl", "--user", "is-active", unit], timeout=5)
        if res.error == "not found" or (not res.ok and not res.stdout.strip()):
            return None
        return res.stdout.strip() == "active"

    # -- knowledge -----------------------------------------------------------

    def solution(self, key: str) -> list[Step]:
        return suggest(key, self.distro_family, immutable=self.immutable)

    # System-wide manifest locations the Vulkan loader always consults
    # (compile-time SYSCONFDIR / FALLBACK_DATA_DIRS). Tests override these.
    system_config_dirs: list[Path] = [Path("/etc")]
    fallback_data_dirs: list[Path] = [Path("/usr/local/share"), Path("/usr/share")]

    def data_dirs(self) -> list[Path]:
        raw = self.env.get("XDG_DATA_DIRS")
        if raw:
            return [Path(p) for p in raw.split(":") if p]
        return list(self.fallback_data_dirs)

    def config_dirs(self) -> list[Path]:
        raw = self.env.get("XDG_CONFIG_DIRS") or "/etc/xdg"
        dirs = [Path(p) for p in raw.split(":") if p]
        for extra in self.system_config_dirs:
            if extra not in dirs:
                dirs.append(extra)
        return dirs

    def user_data_dir(self) -> Path:
        return Path(self.env.get("XDG_DATA_HOME") or self.home / ".local" / "share")

    def user_config_dir(self) -> Path:
        return Path(self.env.get("XDG_CONFIG_HOME") or self.home / ".config")

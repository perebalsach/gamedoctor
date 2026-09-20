"""Filesystems holding Steam libraries (and $HOME): type, mount options, space."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.platform.solutions import Step
from gamedoctor.core.util import human_size
from gamedoctor.diagnostics.base import Diagnostic
from gamedoctor.diagnostics.steam import FLATPAK_ID

_NTFS = {"ntfs", "ntfs3", "ntfs-3g"}
_FAT = {"vfat", "exfat", "msdos", "fat"}
_NETWORK = {"nfs", "nfs4", "cifs", "smb3", "sshfs", "fuse.sshfs", "9p", "virtiofs"}

GiB = 1024**3


class FilesystemDiagnostic(Diagnostic):
    name = "filesystem"
    title = "Filesystem"
    requires = ("steam",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        targets: list[tuple[str, Path]] = [("Home", ctx.home)]
        for lib in ctx.steam_libraries:
            targets.append(("Steam library", lib))
        seen: set[Path] = set()
        for label, path in targets:
            try:
                real = path.resolve()
            except OSError:
                continue
            if real in seen or not real.exists():
                continue
            seen.add(real)
            self._inspect(ctx, r, label, path)
        self._flatpak_permissions(ctx, r)
        return r

    def _inspect(self, ctx: Context, r: ModuleResult, label: str, path: Path) -> None:
        mount = ctx.mount_for(path)
        fstype = mount.fstype if mount else "unknown"
        if fstype == "fuseblk":
            fstype = "fuseblk (NTFS via ntfs-3g?)"
        try:
            usage = shutil.disk_usage(path)
            free = usage.free
        except OSError:
            free = None
        writable = os.access(path, os.W_OK)
        opts = mount.options if mount else []

        flags = []
        if "noexec" in opts:
            flags.append("noexec")
        if "ro" in opts:
            flags.append("read-only")
        if not writable:
            flags.append("not writable")
        summary = fstype + (f", {human_size(free)} free" if free is not None else "") + (f"  [{', '.join(flags)}]" if flags else "")

        key = fstype.split()[0].lower()
        problem = key in _NTFS | _FAT or "noexec" in opts or "ro" in opts or not writable
        r.fact(label, f"{path}  ({summary})", Severity.WARNING if problem else Severity.PASS)

        slug = "home" if label == "Home" else f"library.{path.name or 'root'}"
        if key in _NTFS or key == "fuseblk":
            r.check(
                f"filesystem.ntfs.{slug}",
                Severity.WARNING,
                f"{label} is on an NTFS filesystem: {path}",
                "NTFS works for storing game files, but Proton prefixes (the compatdata folder with each "
                "game's virtual Windows installation) need symlinks, case handling and Unix permissions "
                "that NTFS emulates imperfectly. Typical symptoms: games that fail on first launch, "
                "'disk write error' in Steam, or prefixes that break after Windows boots the same drive.",
                "Keep Steam libraries with Proton games on a Linux filesystem (ext4, btrfs, xfs). If you must "
                "share a drive with Windows, mount it with the uid=,gid= options and move each library's "
                "steamapps/compatdata to a Linux filesystem, symlinking it back.",
            )
        elif key in _FAT:
            r.check(
                f"filesystem.fat.{slug}",
                Severity.ERROR,
                f"{label} is on a FAT/exFAT filesystem: {path}",
                "FAT and exFAT do not support symlinks or Unix permissions, both of which Proton and the "
                "Steam Linux Runtime require. Windows games installed here cannot create a working prefix.",
                "Reformat the drive as ext4 (or another Linux filesystem) or move the library elsewhere.",
            )
        elif key in _NETWORK:
            r.check(
                f"filesystem.network.{slug}",
                Severity.INFO,
                f"{label} is on a network filesystem ({fstype}): {path}",
                "Network storage works for some games but adds latency, and file locking or permission "
                "quirks can break Proton prefixes and shader caches.",
            )
        if "noexec" in opts:
            r.check(
                f"filesystem.noexec.{slug}",
                Severity.ERROR,
                f"{label} is mounted with 'noexec': {path}",
                "Nothing on this filesystem can be executed. Steam cannot start games, Proton or the "
                "runtime from here. This is a common default for removable drives and manual fstab entries.",
                "Remount without noexec (edit /etc/fstab, or change the drive's mount options in your desktop's disk tool).",
            )
        if "ro" in opts or not writable:
            r.check(
                f"filesystem.readonly.{slug}",
                Severity.ERROR,
                f"{label} is not writable: {path}",
                "Steam needs to write game files, shader caches and Proton prefixes here. A read-only "
                "mount (often the result of an unclean NTFS unmount or a hibernated Windows) or wrong "
                "ownership makes every install and launch fail.",
                "Check ownership (`ls -ld`) and the mount state (`findmnt`); for NTFS, disable Windows Fast Startup and run chkdsk from Windows.",
            )
        if free is not None:
            if free < 1 * GiB:
                r.check(
                    f"filesystem.space.{slug}",
                    Severity.ERROR,
                    f"{label} is almost out of space ({human_size(free)} free): {path}",
                    "Steam, Proton and shader caches need free space to run games. Below 1 GiB, updates and "
                    "first launches fail and the desktop session itself can misbehave.",
                )
            elif free < 10 * GiB:
                r.check(
                    f"filesystem.space.{slug}",
                    Severity.WARNING,
                    f"{label} is low on space ({human_size(free)} free): {path}",
                    "Shader pre-caching and game updates can need several GiB of temporary space. Low space "
                    "causes updates to fail or games to crash while compiling shaders.",
                )
            else:
                r.ok(f"filesystem.space.{slug}", f"{label} has enough free space")

    def _flatpak_permissions(self, ctx: Context, r: ModuleResult) -> None:
        flatpaks = [i for i in ctx.steam_installs if i.kind == "flatpak"]
        if not flatpaks:
            return
        allowed = ""
        res = ctx.run(["flatpak", "override", "--user", "--show", FLATPAK_ID], timeout=8)
        if res.ok:
            allowed = res.stdout
        for inst in flatpaks:
            for lib in inst.libraries:
                real = str(lib.resolve())
                if real.startswith(str(ctx.home)):
                    continue
                if allowed and (real in allowed or "host" in allowed or real.split("/")[1] in allowed):
                    continue
                r.check(
                    f"filesystem.flatpak.{lib.name}",
                    Severity.WARNING,
                    f"Flatpak Steam may not be allowed to access the library at {lib}",
                    "This Steam library is outside your home folder, and no Flatpak filesystem permission "
                    "covering it was found. The sandbox will then hide the drive from Steam and its games "
                    "appear as uninstalled.",
                    "Grant the Flatpak access to the library's location.",
                    steps=[Step(f"flatpak override --user --filesystem={real} {FLATPAK_ID}")],
                )

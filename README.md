# Linux Game Doctor

`gamedoctor` collects the information that matters for gaming on a Linux machine,
detects common configuration problems, explains them in plain language and
produces a report you can attach to a bug report or paste into Discord.

It **never changes anything on the system**. Running `gamedoctor` is always safe.
`gamedoctor fix` can apply the remedies it suggests, but only the ones you confirm
one by one, and it shows you the exact command first.

```text
$ gamedoctor

Linux Game Doctor 0.1.0

System
  OS                CachyOS
  Kernel            6.17.2-2-cachyos
  Desktop           KDE Plasma 6.4.0
  Session           Wayland
  ...

Potential issues

  ✗ 32-bit Vulkan driver for your AMD GPU not found

    Your 64-bit Vulkan driver (RADV) is installed, but no 32-bit build of
    it was found. Many Windows games run through Proton contain 32-bit
    components ...

    Try:
      sudo pacman -S lib32-vulkan-radeon

Overall status

   21 checks passed
    2 notes
    0 warnings
    1 errors
    0 critical
```

When you are ready to act on an issue, `gamedoctor fix` walks you through it:

```text
$ gamedoctor fix

[1/1]
  ✗ 32-bit Vulkan driver for your AMD GPU not found
    id: vulkan.icd.32bit.AMD  module: vulkan

      sudo pacman -S lib32-vulkan-radeon
      needs administrator rights (sudo will ask for your password)
    Run this command? [y/N/s(kip)/q(uit)] y
    $ sudo pacman -S lib32-vulkan-radeon
    ...
    Done.
    ✓ Re-checked: vulkan.icd.32bit.AMD now passes.

Summary
    1 fixed  vulkan.icd.32bit.AMD
  Everything selected is resolved.
```

## Install

Requires Python 3.12+ on Linux.

**Recommended — with [uv](https://docs.astral.sh/uv/getting-started/installation/):**

```bash
uv tool install .
```

This installs `gamedoctor` into an isolated environment and puts it on your
`PATH`. After that you can run `gamedoctor` from anywhere, no virtual
environment or `uv run` needed.

To run it once without installing:

```bash
uvx --from . gamedoctor
```

**Alternative — with pip:**

```bash
pip install --user .
```

Make sure `~/.local/bin` is on your `PATH` (it usually is on modern distros).
If `gamedoctor` is not found after install, add this to your shell profile:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Usage

### `gamedoctor check` (default)

`check` is the default command — you can omit it entirely.

```bash
gamedoctor [MODULES...] [OPTIONS]
gamedoctor check [MODULES...] [OPTIONS]
```

| Argument / Option | Description |
| --- | --- |
| `MODULES...` | Run only these modules (space-separated). Default: all. See `--list-modules`. |
| `--report` | Also save a plain-text report to `gamedoctor-report.txt`. |
| `--json` | Print the report as JSON to stdout instead of text. |
| `-o / --output FILE` | File to write when using `--report` or `--json`. |
| `--list-modules` | Print available module names and exit. |
| `--debug` | Disable privacy redaction (home path, user name); include internal tracebacks. Review before sharing. |
| `--no-color` | Disable coloured output. |
| `--version` | Show the version and exit. |
| `-h / --help` | Show help and exit. |

```bash
gamedoctor                        # full diagnostic, coloured output
gamedoctor vulkan steam           # only the vulkan and steam modules
gamedoctor --report               # also save gamedoctor-report.txt (share this)
gamedoctor --json                 # machine-readable JSON on stdout
gamedoctor --json -o report.json  # JSON written to a file
gamedoctor --list-modules         # show available module names
gamedoctor --debug                # no redaction, internal tracebacks
gamedoctor --no-color             # plain text, no ANSI colours
gamedoctor --version              # print version and exit
```

Exit codes: `0` on success, `2` for an unknown module or check id.

Reports are privacy-safe by default: your home directory becomes `$HOME`;
the hostname, user name and any identifiers are never collected.

### `gamedoctor fix`

```bash
gamedoctor fix [CHECK_IDS...] [OPTIONS]
```

| Argument / Option | Description |
| --- | --- |
| `CHECK_IDS...` | Only walk through these check ids (default: every issue). |
| `--all` | Also offer remedies for INFO notes, not only errors and warnings. |
| `--dry-run` | Show what would be proposed and exit without running anything. |
| `-y / --yes` | Run every remedy without asking. Steps with alternatives are skipped. |
| `--debug` | Include internal tracebacks. |
| `--no-color` | Disable coloured output. |
| `-h / --help` | Show help and exit. |

```bash
gamedoctor fix                          # walk through every issue, confirm each command
gamedoctor fix vulkan.icd.32bit.AMD     # only the given check id(s)
gamedoctor fix --all                    # also offer remedies for INFO notes
gamedoctor fix --dry-run                # show what would be proposed, run nothing
gamedoctor fix --yes                    # unattended; steps with alternatives are skipped
```

`fix` exits `1` when something selected is still unresolved (skipped, failing or manual).

For each issue `fix` shows the check, the exact command and why, then asks
`y/N/s(kip)/q(uit)`. Commands run in the foreground with your normal
environment, so `sudo` prompts for your password as usual. Afterwards the
affected module is re-run and you see whether the check now passes. Remedies
that only take effect after a re-login or replug (udev rules, kernel modules)
say so instead of being reported as failures.

What `fix` can apply in this version: package installs for your distribution
family, user services (`systemctl --user`), controller permissions (udev rules,
`uinput`) and Flatpak Steam filesystem overrides. Anything else (kernel
parameters, Steam settings, choosing between driver variants when running with
`--yes`) is shown as an instruction, never guessed. `fix` refuses to run as
root: remedies use `sudo` where needed and user services must target your own
session. On image-based systems (SteamOS, Bazzite, Silverblue) every remedy is
informational, so nothing executes.

## What it checks (v0.1)

| Module        | Collects                                            | Detects, for example                                              |
| ------------- | --------------------------------------------------- | ----------------------------------------------------------------- |
| `system`      | distro, kernel, CPU, RAM, desktop, session          | no XWayland on Wayland, missing 32-bit libraries, no display      |
| `gpu`         | GPUs, kernel driver, VRAM, OpenGL, Mesa             | unbound GPU, NVIDIA kernel/user-space mismatch, software OpenGL   |
| `vulkan`      | loader, ICDs per architecture, devices, layers      | missing 32-bit driver, llvmpipe only, stale manifests, overrides  |
| `steam`       | native/Flatpak/Snap installs, libraries, runtimes   | unmounted library folders, multiple installs                      |
| `proton`      | Valve and custom Proton versions, default tool      | incomplete installs, missing Steam Linux Runtime, Steam Play off  |
| `tools`       | GameMode, MangoHud, Gamescope, vkBasalt, Wine       | GameMode daemon not responding, missing 32-bit halves             |
| `audio`       | PipeWire / PulseAudio, WirePlumber, default output  | no session manager, no PulseAudio compatibility, dummy output     |
| `controllers` | connected gamepads, bus, kernel driver, Steam Input     | no permission on evdev/hidraw nodes, /dev/uinput missing          |
| `filesystem`  | filesystem type, mount options and space per library| NTFS/exFAT libraries, `noexec`, read-only, low disk space         |
| `environment` | gaming-related variables set globally               | `LD_PRELOAD`, forced software GL, global `PROTON_*` overrides     |

Missing *optional* tools (MangoHud, Gamescope...) are shown as facts, not problems.

## Roadmap

See `PROJECT_DESCRIPTION.md`. Next up (0.2): Markdown reports, hybrid-GPU and
PRIME diagnostics, deeper Flatpak Steam support.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, architecture notes and
instructions for adding new checks or distribution support.

## License

MIT

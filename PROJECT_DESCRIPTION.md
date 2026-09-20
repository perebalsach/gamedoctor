# Linux Game Doctor

## Project summary

**Linux Game Doctor** is an open-source diagnostic and troubleshooting tool for Linux gaming.

Its purpose is simple:

> Given a Linux machine, collect the information that matters for gaming, detect common configuration problems, explain them clearly, and generate a report that can be shared with developers, support teams, Discord communities, GitHub issues, or other players.

Instead of asking users to manually run ten different commands such as:

```bash
uname -a
lspci
vulkaninfo
glxinfo
systemctl --user status pipewire
systemctl status gamemoded
```

Linux Game Doctor would provide one command:

```bash
gamedoctor
```

and produce something like:

```text
Linux Game Doctor 0.1

System
  OS             CachyOS
  Kernel         6.17.2
  Desktop        KDE Plasma
  Session        Wayland
  Architecture   x86_64

GPU
  Device         AMD Radeon RX 7800 XT
  Driver         amdgpu
  Mesa           26.1.0
  Vulkan         1.4
  Vulkan ICD     RADV

Gaming

  Steam                  ✓ detected
  Steam Runtime          ✓ available
  Proton                 ✓ 4 versions
  Proton Experimental    ✓ installed
  GE-Proton              ✓ GE-Proton10-15

Runtime tools

  GameMode               ⚠ installed but service unavailable
  MangoHud               ✓ installed
  Gamescope              ✓ installed
  vkBasalt               - not installed

Audio

  PipeWire               ✓ running
  WirePlumber            ✓ running

Controllers

  DualSense Wireless     ✓ detected

Potential issues

  ⚠ GameMode is installed but not responding.

    Try:
      gamemoded -t

  ⚠ 32-bit Vulkan support could not be detected.

    Windows games running through Proton may require
    32-bit Vulkan drivers.

Overall status

  18 checks passed
   2 warnings
   0 critical errors

Report saved:
  gamedoctor-report.txt
```

The project should avoid trying to automatically "optimize Linux."

Its first responsibility is to **diagnose and explain**.

---

# 1. The problem

Linux gaming is significantly easier than it was several years ago, but troubleshooting is still fragmented.

When somebody says:

> "This game doesn't work on Linux."

the problem might be related to:

* Proton
* Wine
* Vulkan
* Mesa
* NVIDIA drivers
* 32-bit GPU libraries
* Wayland
* X11
* Gamescope
* Steam Runtime
* Flatpak permissions
* GameMode
* MangoHud
* PipeWire
* controller permissions
* kernel version
* environment variables
* Proton prefixes
* filesystem permissions
* NTFS-mounted game libraries
* missing libraries
* laptop hybrid graphics
* GPU selection
* overlays
* Steam launch options

Experienced Linux users usually know what information to ask for.

Less experienced users do not.

As a result, Linux troubleshooting often starts with twenty messages asking the user to provide their system configuration.

Linux Game Doctor should remove that friction.

---

# 2. Core project philosophy

Linux Game Doctor should follow several principles.

## Diagnose before modifying

The tool should initially make **no automatic system changes**.

Running:

```bash
gamedoctor
```

should be completely safe.

It should inspect the system and report findings.

Later versions might offer commands such as:

```bash
gamedoctor explain vulkan-32bit
```

or eventually:

```bash
gamedoctor fix gamemode
```

But automatic repair should never be the foundation of the project.

---

## Explain instead of dumping information

A normal Linux troubleshooting tool might say:

```text
libvulkan_radeon.so not found
```

Game Doctor should instead say:

```text
⚠ 32-bit Vulkan support was not detected.

Why this matters:

Many Windows games running through Proton contain
32-bit components and require 32-bit Vulkan drivers.

Your 64-bit Vulkan installation appears to work correctly.
```

Then optionally provide distro-specific help:

```text
CachyOS / Arch:

sudo pacman -S lib32-vulkan-radeon
```

The important distinction is:

**diagnostic → explanation → possible resolution**

rather than:

**command output → good luck**

---

# 3. Target users

There are several distinct audiences.

## Linux gamers

The primary audience.

Especially users running:

* SteamOS
* Bazzite
* CachyOS
* Arch
* Fedora
* Ubuntu
* Linux Mint
* Pop!_OS
* Nobara

Users could run Game Doctor before asking for help.

Instead of posting:

> "Helldivers won't start."

they post:

```text
GameDoctor report:
https://...
```

---

## Game developers

Developers could include Game Doctor in their support documentation.

For example:

> Experiencing problems running our game through Proton?
>
> Run:
>
> `gamedoctor --report`
>
> and attach the generated report to your bug report.

This provides developers with standardized Linux environment information.

---

## Open-source maintainers

Projects such as:

* Proton utilities
* launchers
* Linux gaming tools
* modding tools
* emulators

could ask users to attach a Game Doctor report to bug reports.

---

## QA teams

A QA engineer could run:

```bash
gamedoctor --json
```

before running Linux compatibility tests.

This records exactly what environment was used.

---

# 4. Basic usage

The primary command should remain extremely simple.

```bash
gamedoctor
```

This performs the default diagnostic suite.

Additional commands can gradually be introduced.

```bash
gamedoctor system
gamedoctor gpu
gamedoctor vulkan
gamedoctor steam
gamedoctor proton
gamedoctor audio
gamedoctor controller
```

For example:

```bash
gamedoctor vulkan
```

could output:

```text
Vulkan diagnostics

Loader
  Vulkan loader        ✓
  Version              1.4.321

64-bit

  RADV                  ✓
  AMD RX 7800 XT        ✓

32-bit

  RADV                  ✗

Detected problem:

32-bit Vulkan support is missing.

This can cause Proton games to fail during startup.
```

---

# 5. Diagnostic categories

The checks should be organized into modules.

## System

Collect:

```text
Distribution
Distribution version
Kernel
Architecture
Desktop environment
Display server
Session
Hostname optional / redacted
```

Example:

```text
OS            CachyOS
Kernel        6.17.2-2-cachyos
Desktop       KDE Plasma 6.4
Session       Wayland
Architecture  x86_64
```

---

# 6. GPU diagnostics

GPU configuration is one of the most important parts of Linux gaming.

Game Doctor should detect:

```text
GPU model
GPU vendor
kernel driver
userspace driver
Mesa version
Vulkan support
OpenGL support
VRAM where available
```

Example:

```text
GPU

AMD Radeon RX 7800 XT

Kernel driver
  amdgpu                   ✓

Mesa
  26.1.0                   ✓

Vulkan driver
  RADV                     ✓

OpenGL
  4.6                      ✓
```

NVIDIA checks should include:

```text
NVIDIA driver installed
NVIDIA kernel module loaded
NVIDIA driver version
Vulkan available
NVML available
```

Hybrid laptop support eventually becomes very interesting:

```text
GPU 0
  AMD Radeon 780M

GPU 1
  NVIDIA RTX 4070 Laptop

Game GPU
  NVIDIA RTX 4070

PRIME offloading
  ✓ available
```

---

# 7. Vulkan diagnostics

This should probably become one of the strongest parts of Game Doctor.

Check:

```text
Vulkan loader
Vulkan API version
Vulkan ICDs
32-bit Vulkan
64-bit Vulkan
GPU association
software renderers
multiple conflicting ICDs
```

Potential error:

```text
CRITICAL

No hardware Vulkan device detected.

Detected Vulkan device:

  llvmpipe

This is a CPU software renderer.

Games using DXVK or VKD3D may fail or perform extremely poorly.
```

That kind of explanation would be extremely useful for inexperienced users.

---

# 8. Steam diagnostics

Detect Steam installations.

Possible sources:

```text
native Steam
Flatpak Steam
SteamOS installation
```

Check:

```text
Steam installed
Steam executable
Steam library directories
Steam Runtime
compatibility tools
Steam environment
```

Example:

```text
Steam

Installation
  Native Steam               ✓

Path
  ~/.local/share/Steam

Libraries
  ~/Games/Steam
  /mnt/games/SteamLibrary

Steam Runtime
  sniper                     ✓
  soldier                    ✓
```

---

# 9. Proton diagnostics

Game Doctor should identify available Proton versions.

Example:

```text
Proton

Valve

  Proton 11
  Proton Experimental

Custom

  GE-Proton10-15
  GE-Proton10-14
```

Potential checks:

```text
missing compatibilitytools.d
broken Proton installations
invalid Proton directory
multiple Proton versions
Steam compatibility configuration
```

Later:

```bash
gamedoctor proton test
```

could run a very small known executable through Proton to verify that the basic Proton environment works.

This should probably live outside the MVP.

---

# 10. Steam library diagnostics

Game installation drives cause many Linux gaming problems.

Game Doctor could detect:

```text
Filesystem type
mount options
permissions
ownership
case sensitivity
available disk space
```

Example:

```text
Steam Library

/mnt/games

Filesystem
  NTFS                      ⚠

Mount options
  uid=1000
  exec                      ✓

Warning:

Proton prefixes stored on NTFS filesystems can cause
compatibility and permission issues.

Consider storing Proton prefixes on a Linux filesystem.
```

This could become a very valuable feature.

---

# 11. Wayland / X11

Check:

```text
session type
desktop compositor
XWayland
VRR support where detectable
Gamescope
```

Output:

```text
Display

Session
  Wayland                   ✓

Desktop
  KDE Plasma

XWayland
  available                 ✓

Gamescope
  installed                 ✓
```

The tool should avoid statements such as:

> Wayland is bad for gaming.

Instead, it should report factual compatibility information.

---

# 12. Gaming utilities

Detect common gaming tools.

```text
MangoHud
GameMode
Gamescope
vkBasalt
CoreCtrl
LACT
ProtonPlus
ProtonUp-Qt
```

Example:

```text
Gaming Tools

MangoHud
  installed                 ✓
  version                   0.8.x

GameMode
  installed                 ✓
  daemon                    ✓

Gamescope
  installed                 ✓
```

Avoid presenting these as requirements.

For example:

```text
MangoHud not installed
```

should not be a warning.

It is optional.

---

# 13. Audio

Check the Linux audio stack.

Primarily:

```text
PipeWire
WirePlumber
PulseAudio compatibility layer
default output
default input
```

Example:

```text
Audio

PipeWire
  running                   ✓

WirePlumber
  running                   ✓

PulseAudio compatibility
  available                 ✓
```

Game Doctor doesn't need to become an audio diagnostic suite.

Only detect common conditions that prevent game audio from functioning.

---

# 14. Controllers

Detect connected gaming devices.

Examples:

```text
Xbox controller
DualSense
DualShock
Steam Controller
Switch Pro Controller
generic USB controller
```

Check:

```text
device visible
evdev available
SDL detection eventually
permission problems
```

Example:

```text
Controllers

Sony DualSense Wireless Controller

USB Device
  detected                  ✓

Input device
  detected                  ✓

Permissions
  OK                        ✓
```

---

# 15. Environment variables

Linux gaming users often accumulate launch configuration.

Game Doctor could detect known variables:

```text
DXVK_*
VKD3D_*
PROTON_*
WINE*
MANGOHUD
GAMEMODERUNEXEC
RADV_*
AMD_VULKAN_ICD
VK_ICD_FILENAMES
```

If a dangerous or suspicious override exists:

```text
Warning

VK_ICD_FILENAMES is globally configured:

/usr/share/vulkan/icd.d/nvidia_icd.json

Your system also contains an AMD GPU.

This environment variable forces Vulkan to use only the
NVIDIA Vulkan driver.
```

This could catch some very difficult problems.

---

# 16. Severity system

Results should have clear severity levels.

```text
PASS
INFO
WARNING
ERROR
CRITICAL
```

For example:

```text
✓ PASS

Vulkan hardware acceleration works.


i INFO

MangoHud is not installed.
MangoHud is optional.


⚠ WARNING

GameMode is installed but not responding.


✗ ERROR

32-bit Vulkan support is unavailable.


!! CRITICAL

No hardware Vulkan driver was detected.
```

Internally:

```python
class Severity(Enum):
    INFO
    WARNING
    ERROR
    CRITICAL
```

The diagnostic engine shouldn't treat every missing optional tool as a problem.

---

# 17. Report formats

This should be one of the strongest features.

Game Doctor should support multiple formats.

Human-readable:

```bash
gamedoctor --report
```

produces:

```text
gamedoctor-report.txt
```

Markdown:

```bash
gamedoctor --markdown
```

useful for GitHub.

JSON:

```bash
gamedoctor --json
```

useful for automation.

Eventually:

```bash
gamedoctor --html
```

could generate an attractive self-contained report.

---

# 18. Privacy

Privacy should be designed into the project from day one.

A diagnostic report should NOT expose things such as:

```text
username
home directory
Steam account
IP addresses
Wi-Fi SSID
machine hostname
serial numbers
UUIDs
```

Instead:

```text
/home/pere/.steam
```

should become:

```text
$HOME/.steam
```

There should be two modes.

Default:

```bash
gamedoctor
```

privacy-safe.

Verbose:

```bash
gamedoctor --debug
```

includes more technical information but still warns before collecting sensitive information.

This could become a major trust advantage for the project.

---

# 19. Shareable reports

Eventually:

```bash
gamedoctor share
```

could create a temporary anonymous report.

Example:

```text
https://gamedoctor.dev/r/7H8K2F
```

The report could display:

```text
Linux Game Doctor Report

System
GPU
Vulkan
Steam
Proton
Audio
Controllers

Detected problems
```

This would make the project much more useful in:

```text
Discord
Reddit
GitHub
Steam forums
developer support tickets
```

However the first version should probably avoid requiring any server.

Start entirely local.

---

# 20. Game-specific diagnostics

A very interesting evolution would be:

```bash
gamedoctor game
```

or:

```bash
gamedoctor steam 1245620
```

Game Doctor could inspect a specific Steam game.

Example:

```text
ELDEN RING

Steam AppID
  1245620

Installed
  ✓

Filesystem
  ext4

Proton
  GE-Proton10-15

Prefix
  healthy

Vulkan
  available

Disk
  63 GB free
```

Eventually it could identify things such as:

```text
prefix missing
prefix permissions broken
wrong Proton version configured
invalid launch arguments
game on problematic filesystem
missing Vulkan architecture
```

This is where Linux Game Doctor could become significantly more powerful.

---

# 21. Plugin architecture

I would design the project around independent diagnostic modules.

Conceptually:

```text
GameDoctor
│
├── System
│
├── GPU
│
├── Vulkan
│
├── Steam
│
├── Proton
│
├── Filesystem
│
├── Audio
│
├── Controllers
│
└── GamingTools
```

Each module returns standardized checks.

Something like:

```python
DiagnosticResult(
    id="vulkan.32bit",
    status=Status.ERROR,
    title="32-bit Vulkan unavailable",
    description="...",
    explanation="...",
    recommendation="..."
)
```

This would make adding new checks extremely easy.

The architecture should favor:

> one diagnostic = one small test

instead of giant modules full of special cases.

---

# 22. Community-contributed diagnostics

This architecture opens an interesting open-source model.

Someone could contribute:

```text
checks/
    steam_flatpak.py
```

Another contributor:

```text
checks/
    nvidia_prime.py
```

Another:

```text
checks/
    arch_multilib.py
```

Another:

```text
checks/
    pipewire.py
```

This makes Game Doctor a good community project because contributors do not need to understand the entire codebase.

They can add one diagnostic.

---

# 23. Distribution-specific knowledge

The diagnostic engine should ideally remain distribution-independent.

For example:

```text
Problem:
32-bit Vulkan missing
```

is generic.

Solutions can then be distro-specific.

```text
Arch / CachyOS

sudo pacman -S lib32-vulkan-radeon

Ubuntu

sudo apt install mesa-vulkan-drivers:i386

Fedora

sudo dnf install mesa-vulkan-drivers.i686
```

Represent these separately.

Perhaps:

```yaml
issue:
  vulkan_32bit_missing

solutions:

  arch:
    package:
      lib32-vulkan-radeon

  ubuntu:
    package:
      mesa-vulkan-drivers:i386
```

That keeps the diagnostic logic clean.

---

# 24. Suggested technology

For the first version I would use:

```text
Python 3.12+
```

because this project mostly performs:

```text
process execution
system inspection
filesystem inspection
text parsing
JSON generation
```

Useful libraries:

```text
Typer
Rich
Pydantic
psutil
```

Structure:

```text
gamedoctor/

    cli.py

    core/
        doctor.py
        result.py
        report.py

    diagnostics/
        system.py
        gpu.py
        vulkan.py
        steam.py
        proton.py
        audio.py
        filesystem.py

    platform/
        arch.py
        ubuntu.py
        fedora.py

    reporters/
        console.py
        json.py
        markdown.py
```

Don't over-engineer the initial version.

---

# 25. MVP

I'd make **v0.1 intentionally small**.

Support:

```text
Linux system information

GPU detection

Vulkan detection

32/64-bit Vulkan detection

Steam detection

Proton detection

GameMode detection

MangoHud detection

Gamescope detection

PipeWire detection

basic filesystem detection

text report

JSON report
```

Commands:

```bash
gamedoctor

gamedoctor --json

gamedoctor --report
```

That's enough.

I would explicitly avoid initially implementing:

```text
GUI
web service
automatic fixes
game database
benchmarking
Steam API
ProtonDB integration
remote reports
performance monitoring
```

All of those can come later.

---

# 26. Version 0.2

Then add:

```text
distribution-specific recommendations

NVIDIA diagnostics

hybrid GPU diagnostics

Steam Flatpak support

controller detection

environment variable inspection

Markdown reports
```

---

# 27. Version 0.3

Game-specific diagnostics:

```bash
gamedoctor steam <appid>
```

plus:

```text
Steam library inspection

filesystem checks

Proton prefix validation

launch options

selected compatibility tool
```

This could be the version where the project becomes particularly interesting.

---

# 28. Version 1.0

I would define 1.0 as:

> Linux Game Doctor can reliably diagnose the majority of common environment-level problems preventing a Steam/Proton game from launching correctly.

Supported environment:

```text
Arch / CachyOS
SteamOS
Bazzite / Fedora
Ubuntu / Mint

AMD
NVIDIA
Intel

Steam native
Steam Flatpak

Wayland
X11
```

And:

```text
system
GPU
Vulkan
Steam
Proton
filesystem
audio
controllers
gaming environment
```

all have stable diagnostic APIs.

---

# 29. Long-term end goal

The long-term goal should not be:

> A program that configures Linux gaming.

It should become:

> **The standard diagnostic layer for Linux gaming.**

Ideally, when somebody reports:

> "Your game doesn't work on Linux."

the normal response eventually becomes:

```text
Run Game Doctor and attach the report.
```

Similar to tools developers already use in other ecosystems for collecting standardized diagnostic information.

Game developers could link it directly from their support pages.

Open-source projects could include:

```text
Please attach:

gamedoctor --markdown
```

inside their GitHub issue template.

Discord bots could understand Game Doctor reports.

Launchers could eventually invoke the diagnostic engine.

CI systems could use:

```bash
gamedoctor --json
```

to record machine configurations.

---

# 30. The bigger ecosystem

If Game Doctor succeeds, it could become the foundation for your other projects.

For example:

```text
                 Game Doctor Core
                        │
              Linux environment model
                        │
        ┌───────────────┼────────────────┐
        │               │                │
        ▼               ▼                ▼
   Game Doctor       ProtonQA         GamePerf
        │               │                │
   diagnostics      compatibility    performance
```

The system-information layer would be shared.

For example:

```python
machine.gpu
machine.vulkan
machine.kernel
machine.session
machine.steam
machine.proton
```

Then ProtonQA doesn't need to rediscover all that information.

---

# 31. What would make this project stand out

There are plenty of scripts that print Linux system information.

Game Doctor should **not** compete with them.

Its differentiator should be the knowledge encoded inside the checks.

Instead of:

```text
Vulkan: installed
```

it understands:

```text
Vulkan 64-bit works.

Vulkan 32-bit does not.

Steam is installed.

Proton is installed.

Therefore:

Windows games containing 32-bit Vulkan components
may fail under Proton.
```

That's much more valuable.

The product is not really the CLI.

The real product is:

> **a community-maintained knowledge base of Linux gaming problems represented as executable diagnostics.**

That is what could make Linux Game Doctor genuinely interesting as an open-source project.

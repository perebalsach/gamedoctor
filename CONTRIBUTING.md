# Contributing to Linux Game Doctor

## Dev setup

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync          # create venv and install all dependencies
uv run gamedoctor
uv run pytest
```

## Project layout

```
gamedoctor/
  cli.py                  # Typer entry point (check + fix commands)
  core/
    doctor.py             # orchestrates modules, builds the Report
    fixer.py              # plans and executes remedies
    result.py             # Fact, Check, Severity, Report types
    context.py            # Context passed to each diagnostic module
    report.py             # plain-text renderer
    privacy.py            # path/hostname redaction
    util.py               # shared helpers
  diagnostics/            # one file per module (system, gpu, vulkan, …)
  platform/
    solutions.py          # distro-specific Step lists keyed by check id
  reporters/
    console.py            # rich-based terminal output
    json.py               # JSON renderer
```

## Adding a check

Each module in `gamedoctor/diagnostics/` receives a `Context` and a result
builder `r`, and calls `r.fact()` for informational items or `r.check()` for
anything that can pass or fail:

```python
r.fact("MangoHud", "installed 0.8.1", Severity.PASS)
r.check(
    "vulkan.icd.32bit.AMD",
    Severity.ERROR,
    "32-bit Vulkan driver for your AMD GPU not found",
    explanation="Why this matters ...",
    steps=ctx.solution("vulkan.icd.32bit.AMD"),   # distro-specific, from platform/solutions.py
)
```

Keep diagnostics distribution-independent. `gamedoctor/platform/solutions.py`
maps a check id to a list of `Step`s per distribution family. The same steps
appear under "Try:" in the report and are executed by `gamedoctor fix`, so put
commands in steps rather than in the explanation text:

```python
Step("sudo pacman -S lib32-vulkan-radeon")                            # runnable
Step("sudo pacman -S nvidia-utils", "or nvidia-open + nvidia-utils")  # runnable, with a hint
Step(note="Enable the [multilib] repository in /etc/pacman.conf")     # manual instruction
Step(options=("sudo pacman -S nvidia-open", "sudo pacman -S nvidia"),
     note="nvidia-open for Turing or newer")                          # user picks one
```

Rules for steps:

- A runnable command must work as-is through `sh -c` — no `<placeholders>`;
  use a `note` to describe anything that needs to be filled in.
- Commands that require administrator rights must start with `sudo` so `fix`
  can warn the user before asking.

## Running the tests

```bash
uv run pytest            # full suite
uv run pytest -x -q      # stop on first failure, quiet output
```

The test suite does not touch the live system. Failure paths are exercised
through simulated or mocked data rather than relying on the dev machine's
configuration.

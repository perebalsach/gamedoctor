"""Audio stack: PipeWire / PulseAudio, session manager, PulseAudio compatibility."""

from __future__ import annotations

import re

from gamedoctor.core.context import Context
from gamedoctor.core.result import ModuleResult, Severity
from gamedoctor.diagnostics.base import Diagnostic


class AudioDiagnostic(Diagnostic):
    name = "audio"
    title = "Audio"
    requires = ("system",)

    def run(self, ctx: Context) -> ModuleResult:
        r = self.result()
        procs = ctx.processes
        pipewire = "pipewire" in procs or ctx.user_service_active("pipewire") is True
        pulse_native = "pulseaudio" in procs
        wireplumber = "wireplumber" in procs
        media_session = "pipewire-media-session" in procs or "pipewire-media-se" in procs
        pipewire_pulse = "pipewire-pulse" in procs or ctx.user_service_active("pipewire-pulse") is True

        pactl = ctx.run(["pactl", "info"], timeout=8) if ctx.which("pactl") else None
        server = None
        if pactl and pactl.ok:
            m = re.search(r"Server Name:\s*(.+)", pactl.stdout)
            server = m.group(1).strip() if m else None
            if server and "PipeWire" in server:
                pipewire = True
                pipewire_pulse = True

        if pipewire:
            ver = re.search(r"PipeWire ([\d.]+)", server or "")
            version = ver.group(1) if ver else self._pipewire_version(ctx)
            r.fact("PipeWire", f"running{f' {version}' if version else ''}", Severity.PASS)
            r.ok("audio.server", "PipeWire is running")
            if wireplumber:
                r.fact("WirePlumber", "running", Severity.PASS)
                r.ok("audio.session-manager", "WirePlumber is running")
            elif media_session:
                r.fact("Session manager", "pipewire-media-session (deprecated)", Severity.INFO)
                r.ok("audio.session-manager", "pipewire-media-session is running")
            else:
                r.fact("WirePlumber", "not running", Severity.WARNING)
                r.check(
                    "audio.session-manager",
                    Severity.WARNING,
                    "PipeWire is running without a session manager",
                    "PipeWire needs WirePlumber (or the older pipewire-media-session) to detect sound "
                    "cards and route audio. Without it there are no output devices and games are silent.",
                    steps=ctx.solution("audio.session-manager"),
                )
            if pipewire_pulse:
                r.fact("PulseAudio compatibility", "available (pipewire-pulse)", Severity.PASS)
                r.ok("audio.pulse-compat", "PulseAudio compatibility layer is available")
            else:
                r.fact("PulseAudio compatibility", "not running", Severity.WARNING)
                r.check(
                    "audio.pulse-compat",
                    Severity.WARNING,
                    "PipeWire's PulseAudio compatibility service is not running",
                    "Almost every game (through SDL, FMOD, Wine or Proton) talks to the PulseAudio API. "
                    "Without pipewire-pulse those games find no audio server and stay silent.",
                    steps=ctx.solution("audio.pulse-compat"),
                )
        elif pulse_native:
            r.fact("PulseAudio", "running (classic PulseAudio server)", Severity.PASS)
            r.ok("audio.server", "PulseAudio is running")
        else:
            r.fact("Audio server", "none detected", Severity.ERROR)
            r.check(
                "audio.server",
                Severity.ERROR,
                "No audio server is running",
                "Neither PipeWire nor PulseAudio is running for this user. Games will have no sound and "
                "some crash at startup when audio initialisation fails."
                + (" (If you are running gamedoctor over SSH, the desktop session's services may simply not be visible here.)" if ctx.session == "none" else ""),
                steps=ctx.solution("audio.server"),
            )
            return r

        if pactl is None:
            r.fact("Default output", "unknown (pactl not installed)")
        elif pactl.ok:
            sink = re.search(r"Default Sink:\s*(.+)", pactl.stdout)
            sink_name = sink.group(1).strip() if sink else ""
            if not sink_name or sink_name == "auto_null" or sink_name.startswith("@DEFAULT"):
                r.fact("Default output", "none (dummy output)", Severity.WARNING)
                r.check(
                    "audio.output",
                    Severity.WARNING,
                    "No audio output device is available",
                    "The default sink is a dummy/null device. Either no sound card was detected, the "
                    "device is disabled, or the session manager has not assigned one. Games will run "
                    "silently.",
                    "Check your output device in the desktop's sound settings, or run `wpctl status`.",
                )
            else:
                r.fact("Default output", sink_name, Severity.PASS)
                r.ok("audio.output", "An audio output device is available")
        else:
            r.fact("Default output", "unknown (pactl could not connect)", Severity.WARNING)
        return r

    @staticmethod
    def _pipewire_version(ctx: Context) -> str | None:
        res = ctx.run(["pipewire", "--version"], timeout=5)
        m = re.search(r"libpipewire ([\d.]+)", res.stdout) if res.ok else None
        return m.group(1) if m else None

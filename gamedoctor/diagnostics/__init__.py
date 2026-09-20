"""Diagnostic modules. Add a module here and it becomes part of the default run."""

from gamedoctor.diagnostics.audio import AudioDiagnostic
from gamedoctor.diagnostics.base import Diagnostic
from gamedoctor.diagnostics.controllers import ControllersDiagnostic
from gamedoctor.diagnostics.environment import EnvironmentDiagnostic
from gamedoctor.diagnostics.filesystem import FilesystemDiagnostic
from gamedoctor.diagnostics.gpu import GpuDiagnostic
from gamedoctor.diagnostics.proton import ProtonDiagnostic
from gamedoctor.diagnostics.steam import SteamDiagnostic
from gamedoctor.diagnostics.system import SystemDiagnostic
from gamedoctor.diagnostics.tools import ToolsDiagnostic
from gamedoctor.diagnostics.vulkan import VulkanDiagnostic

# Presentation order of the report. Execution order is derived from ``requires``.
ALL_DIAGNOSTICS: list[Diagnostic] = [
    SystemDiagnostic(),
    GpuDiagnostic(),
    VulkanDiagnostic(),
    SteamDiagnostic(),
    ProtonDiagnostic(),
    ToolsDiagnostic(),
    AudioDiagnostic(),
    ControllersDiagnostic(),
    FilesystemDiagnostic(),
    EnvironmentDiagnostic(),
]

__all__ = ["ALL_DIAGNOSTICS", "Diagnostic"]

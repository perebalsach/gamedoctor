"""Redaction of personal data from reports (on by default, off with --debug)."""

from __future__ import annotations

import os
import re
from pathlib import Path


class Redactor:
    def __init__(self, home: Path, uid: int, user: str | None = None):
        self.home = str(home).rstrip("/")
        self.uid = uid
        self.user = user or os.environ.get("USER") or Path(self.home).name
        patterns = [(re.escape(self.home), "$HOME")]
        real = str(Path(self.home).resolve()).rstrip("/")
        if real != self.home:
            patterns.append((re.escape(real), "$HOME"))
        patterns.append((rf"/run/user/{self.uid}\b", "$XDG_RUNTIME_DIR"))
        if self.user and len(self.user) > 1:
            patterns.append((rf"/home/{re.escape(self.user)}\b", "$HOME"))
        self._patterns = [(re.compile(p), r) for p, r in patterns]

    def redact(self, text: str) -> str:
        for pattern, replacement in self._patterns:
            text = pattern.sub(replacement, text)
        return text

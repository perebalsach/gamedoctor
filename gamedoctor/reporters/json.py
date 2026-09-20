from __future__ import annotations

import json as _json

from gamedoctor.core.report import Report


def render_json(report: Report, *, indent: int | None = 2) -> str:
    return _json.dumps(report.to_dict(), indent=indent, ensure_ascii=False) + "\n"

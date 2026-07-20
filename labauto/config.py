from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_hardware_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def configured(value: object) -> bool:
    return isinstance(value, (int, float)) or bool(value and not str(value).startswith("TODO"))


def parse_number(value: object) -> float:
    return float(str(value).strip().replace(",", "."))


def require_config(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        value = value[key]
    if not configured(value):
        raise ValueError("missing config: " + ".".join(keys))
    return value

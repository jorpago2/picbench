from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def build_real_config(example: dict[str, Any], discovered: dict[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(example)
    notes: list[str] = []

    laser = unique_resource(discovered.get("visa", []), "laser")
    if laser:
        config["laser"]["visa_resource"] = laser["resource"]
    else:
        notes.append("laser.visa_resource not inferred")

    power_meter = unique_resource(discovered.get("visa", []), "power_meter")
    if power_meter:
        config["power_meter"]["visa_resource"] = power_meter["resource"]
    else:
        notes.append("power_meter.visa_resource not inferred")

    camera = unique_ok(discovered.get("cameras", []), "index")
    if camera:
        config["camera"]["opencv_index"] = camera["index"]
    else:
        notes.append("camera.opencv_index not inferred")

    stages = [row for row in discovered.get("thorlabs_kinesis", []) if row.get("status") == "ok" and row.get("serial")]
    if stages:
        config["motion"]["serial_number"] = stages[0]["serial"]
        config.setdefault("manual_stages", {}).setdefault("a", {})["serial_number"] = stages[0]["serial"]
    else:
        notes.append("Stage A serial number not inferred")
    if len(stages) >= 2:
        config.setdefault("manual_stages", {}).setdefault("b", {})["serial_number"] = stages[1]["serial"]
    else:
        notes.append("Stage B serial number not inferred")

    config["_build_notes"] = notes
    return config


def unique_resource(records: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    matches = [record for record in records if record.get("role") == role and record.get("resource")]
    return matches[0] if len(matches) == 1 else None


def unique_ok(records: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    matches = [record for record in records if record.get("status") == "ok" and key in record]
    return matches[0] if len(matches) == 1 else None


def build_real_config_files(example_path: Path, discovered_path: Path, out_path: Path) -> dict[str, Any]:
    config = build_real_config(
        json.loads(example_path.read_text(encoding="utf-8")),
        json.loads(discovered_path.read_text(encoding="utf-8")),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return config

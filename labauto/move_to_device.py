from __future__ import annotations

import json
import shutil
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from labauto.bsc_config import automatic_stage_configs, axis_channel, bsc_from_config, stage_position_mm
from labauto.config import require_config
from labauto.devices import Device
from labauto.thorlabs_bsc203 import BSC203


def plan_move(reference: dict[str, Any], target: Device) -> dict[str, Any]:
    ref_layout = reference["device_layout_um"]
    ref_stages = reference.get("stage_positions_mm")
    if not isinstance(ref_stages, dict) or not all(stage in ref_stages for stage in ("a", "b")):
        raise ValueError("reference does not contain both stages; register the reference again")
    offsets = {
        "a": {
            "x": target.input_gc_x - float(ref_layout["input_gc_x"]),
            "y": target.input_gc_y - float(ref_layout["input_gc_y"]),
        },
        "b": {
            "x": target.output_gc_x - float(ref_layout["output_gc_x"]),
            "y": target.output_gc_y - float(ref_layout["output_gc_y"]),
        },
    }
    targets = {
        stage: {
            "x": float(ref_stages[stage]["x"]) + offset["x"] / 1000.0,
            "y": float(ref_stages[stage]["y"]) + offset["y"] / 1000.0,
            "z": float(ref_stages[stage]["z"]),
        }
        for stage, offset in offsets.items()
    }
    return {
        "reference_device_id": reference["device_id"],
        "target_device_id": target.device_id,
        "offset_layout_um": offsets["a"],
        "offset_layout_by_stage_um": offsets,
        "target_stage_position_mm": targets["a"],
        "target_stage_positions_mm": targets,
        "target_layout_um": {
            "input_gc_x": target.input_gc_x,
            "input_gc_y": target.input_gc_y,
            "output_gc_x": target.output_gc_x,
            "output_gc_y": target.output_gc_y,
        },
    }


def move_to_device(
    config: dict[str, Any],
    target: Device,
    *,
    reference_path: Path,
    state_dir: Path | None = None,
    dry_run: bool = False,
) -> Path:
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    state_dir = state_dir or Path(config.get("startup", {}).get("state_dir", "workspace/state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(),
        "reference_path": str(reference_path),
        "dry_run": dry_run,
        "z_policy": "retract to motion.z_travel_mm before x/y move; leave z at travel height",
        "z_retract_mm": config.get("motion", {}).get("z_travel_mm"),
        **plan_move(reference, target),
    }

    if not dry_run:
        report["z_retract_mm"] = float(require_config(config, "motion", "z_travel_mm"))
        stage_configs = automatic_stage_configs(config)
        with ExitStack() as stack:
            controllers = {
                stage: stack.enter_context(bsc_from_config({"motion": stage_config}))
                for stage, stage_config in stage_configs.items()
            }
            report["positions_before_mm"] = stage_positions_mm(stage_configs, controllers)
            retract_stages_then_move_xy(
                stage_configs, controllers, report["target_stage_positions_mm"], report["z_retract_mm"]
            )
            report["positions_after_mm"] = stage_positions_mm(stage_configs, controllers)

    path = state_dir / f"move_{target.device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.copyfile(path, state_dir / "move_latest.json")
    return path


def retract_z_then_move_xy(
    config: dict[str, Any],
    controller: BSC203,
    target_stage_mm: dict[str, float],
    z_retract_mm: float,
) -> None:
    controller.move_to_mm(axis_channel(config, "z"), z_retract_mm)
    controller.move_to_mm(axis_channel(config, "x"), target_stage_mm["x"])
    controller.move_to_mm(axis_channel(config, "y"), target_stage_mm["y"])


def stage_positions_mm(stage_configs: dict[str, dict[str, Any]], controllers: dict[str, BSC203]) -> dict[str, dict[str, float]]:
    return {
        stage: stage_position_mm({"motion": stage_configs[stage]}, controller)
        for stage, controller in controllers.items()
    }


def retract_stages_then_move_xy(
    stage_configs: dict[str, dict[str, Any]],
    controllers: dict[str, BSC203],
    targets: dict[str, dict[str, float]],
    z_retract_mm: float,
) -> None:
    for stage, controller in controllers.items():
        controller.move_to_mm(axis_channel({"motion": stage_configs[stage]}, "z"), z_retract_mm)
    for stage, controller in controllers.items():
        stage_config = {"motion": stage_configs[stage]}
        controller.move_to_mm(axis_channel(stage_config, "x"), targets[stage]["x"])
        controller.move_to_mm(axis_channel(stage_config, "y"), targets[stage]["y"])

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from labauto.config import configured, require_config
from labauto.thorlabs_bsc203 import BSC203

MANUAL_STAGE_AXES = {
    "a": {"x": 1, "y": 2, "z": 3},
    "b": {"x": 2, "y": 1, "z": 3},
}
NANOMAX_DRV208_SETTINGS = {
    "x": "HS NanoMax 300 X Axis (DRV208)",
    "y": "HS NanoMax 300 Y Axis (DRV208)",
    "z": "HS NanoMax 300 Z Axis (DRV208)",
}


def manual_stage_config(config: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage not in MANUAL_STAGE_AXES:
        raise ValueError(f"unknown manual stage: {stage}")
    value = config.get("manual_stages", {}).get(stage)
    if not isinstance(value, dict):
        raise RuntimeError(f"Manual Stage {stage.upper()} is not configured")
    if value.get("axis_channels") != MANUAL_STAGE_AXES[stage]:
        raise RuntimeError(f"Manual Stage {stage.upper()} channel map is invalid")
    missing = [axis.upper() for axis in ("x", "y", "z") if axis not in value.get("limits_mm", {})]
    if missing:
        raise RuntimeError(f"Manual Stage {stage.upper()} safe limits are missing for " + ", ".join(missing))
    for axis in ("x", "y", "z"):
        values = value["limits_mm"][axis]
        if not isinstance(values, list) or len(values) != 2 or not all(isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) for item in values) or values[0] >= values[1]:
            raise RuntimeError(f"Manual Stage {stage.upper()} {axis.upper()} safe range is invalid")
    merged = dict(config.get("motion", {}))
    merged.update(value)
    return merged


def automatic_stage_configs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {stage: manual_stage_config(config, stage) for stage in ("a", "b")}


def bsc_from_config(config: dict[str, Any]) -> BSC203:
    motion = config["motion"]
    kinesis_dir = motion.get("kinesis_dir")
    limits = {}
    for axis, channel in motion.get("axis_channels", {}).items():
        values = motion.get("limits_mm", {}).get(axis)
        if isinstance(values, list) and len(values) == 2 and all(isinstance(value, (int, float)) for value in values):
            lower, upper = map(float, values)
            if lower < upper:
                limits[int(channel)] = (lower, upper)
    velocity = motion.get("max_velocity_mm_s")
    acceleration = motion.get("acceleration_mm_s2")
    profile = (float(velocity), float(acceleration)) if isinstance(velocity, (int, float)) and isinstance(acceleration, (int, float)) and velocity > 0 and acceleration > 0 else None
    axis_settings = motion.get("axis_stage_settings")
    if not isinstance(axis_settings, dict) and motion.get("stage_settings_name") == "MAX381/M":
        axis_settings = NANOMAX_DRV208_SETTINGS
    stage_name = (
        {int(channel): axis_settings[axis] for axis, channel in motion.get("axis_channels", {}).items() if axis in axis_settings}
        if isinstance(axis_settings, dict)
        else motion.get("stage_settings_name")
    )
    return BSC203(
        require_config(config, "motion", "serial_number"),
        kinesis_dir=Path(kinesis_dir) if configured(kinesis_dir) else None,
        stage_name=stage_name,
        limits_mm=limits,
        motion_profile=profile,
    )


def axis_channel(config: dict[str, Any], axis: str) -> int:
    return int(require_config(config, "motion", "axis_channels", axis))


def stage_position_mm(config: dict[str, Any], controller: BSC203) -> dict[str, float]:
    return {
        axis: controller.position_mm(axis_channel(config, axis))
        for axis in config["motion"]["axis_channels"]
    }

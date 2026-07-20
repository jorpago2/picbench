from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from labauto.bsc_config import manual_stage_config
from labauto.config import configured
from labauto.vision_calibration import load_profile


REQUIRED_COMMANDS = {
    "laser": (
        "set_wavelength_nm", "get_wavelength_nm", "set_power_unit_mw", "set_power_mw",
        "get_power_mw", "get_power_limit_mw", "output_on", "output_off", "get_output",
    ),
    "power_meter": ("set_wavelength_nm", "get_wavelength_nm", "read_power_w"),
}


def validate_hardware_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    require(errors, config, "motion", "serial_number")
    for stage in ("a", "b"):
        require(errors, config, "manual_stages", stage, "serial_number")
        try:
            manual_stage_config(config, stage)
        except RuntimeError as exc:
            errors.append(str(exc))
    require_axes(errors, config)
    require_limits(errors, config)
    require_motion_profile(errors, warnings, config)
    require_number(errors, config, "motion", "z_travel_mm")
    require(errors, config, "laser", "visa_resource")
    laser = config.get("laser", {})
    slot = laser.get("slot", 1)
    power_mw = laser.get("power_mw", 1.0)
    if not isinstance(slot, int) or isinstance(slot, bool) or slot not in range(1, 9):
        errors.append("laser.slot must be an integer from 1 to 8")
    if not numeric(power_mw) or power_mw <= 0:
        errors.append("laser.power_mw must be a positive number")
    for key in ("wavelength_min_nm", "wavelength_max_nm", "tuning_rate_nm_s", "tuning_margin_ms"):
        require_number(errors, config, "laser", key)
    low_nm = laser.get("wavelength_min_nm")
    high_nm = laser.get("wavelength_max_nm")
    if numeric(low_nm) and numeric(high_nm) and low_nm >= high_nm:
        errors.append("laser wavelength minimum must be below maximum")
    if numeric(laser.get("tuning_rate_nm_s")) and laser["tuning_rate_nm_s"] <= 0:
        errors.append("laser.tuning_rate_nm_s must be > 0")
    if numeric(laser.get("tuning_margin_ms")) and laser["tuning_margin_ms"] < 0:
        errors.append("laser.tuning_margin_ms must be >= 0")
    require(errors, config, "power_meter", "visa_resource")
    if config.get("power_meter", {}).get("channel", 1) not in (1, 2):
        errors.append("power_meter.channel must be 1 or 2")
    require_number(errors, config, "camera", "opencv_index")

    for section, commands in REQUIRED_COMMANDS.items():
        for command in commands:
            require(errors, config, section, "commands", command)

    if not configured(config.get("motion", {}).get("piezo_controller")):
        warnings.append("motion.piezo_controller is not configured")
    if config.get("z_approach", {}).get("enabled"):
        require_number(errors, config, "z_approach", "stop_mm")
        require_number(errors, config, "z_approach", "step_um")
        require_number(errors, config, "z_approach", "settle_ms")
        if configured(config.get("z_approach", {}).get("target_power_w")):
            require_number(errors, config, "z_approach", "target_power_w")
        if configured(config.get("z_approach", {}).get("visual_change_stop")):
            require_number(errors, config, "z_approach", "visual_change_stop")
        if configured(config.get("z_approach", {}).get("wavelength_nm")):
            require_number(errors, config, "z_approach", "wavelength_nm")
        if configured(config.get("z_approach", {}).get("fiber_angle_deg")):
            require_number(errors, config, "z_approach", "fiber_angle_deg")
        if configured(config.get("z_approach", {}).get("angle_sign")):
            require_number(errors, config, "z_approach", "angle_sign")
        if config.get("z_approach", {}).get("angle_axis", "x") not in ("x", "y"):
            errors.append("z_approach.angle_axis must be x or y")
        z = config["z_approach"]
        if not configured(z.get("visual_change_stop")) and not configured(z.get("vision_calibration_path")):
            errors.append("two-stage automatic Z approach requires visual change or a vision calibration")
        if configured(z.get("vision_calibration_path")):
            validate_vision_profile(errors, config, Path(z["vision_calibration_path"]))
        if numeric(z.get("step_um")) and z["step_um"] <= 0:
            errors.append("z_approach.step_um must be > 0")
        if numeric(z.get("settle_ms")) and z["settle_ms"] < 0:
            errors.append("z_approach.settle_ms must be >= 0")
        if numeric(z.get("target_power_w")) and z["target_power_w"] <= 0:
            errors.append("z_approach.target_power_w must be > 0")
        if numeric(z.get("visual_change_stop")) and not 0 <= z["visual_change_stop"] <= 1:
            errors.append("z_approach.visual_change_stop must be between 0 and 1")
        if numeric(z.get("fiber_angle_deg")) and abs(z["fiber_angle_deg"]) >= 90:
            errors.append("z_approach.fiber_angle_deg must be between -90 and 90")
        z_limits = config.get("motion", {}).get("limits_mm", {}).get("z")
        if isinstance(z_limits, list) and len(z_limits) == 2:
            for key in ("start_mm", "stop_mm"):
                if numeric(z.get(key)) and not z_limits[0] <= z[key] <= z_limits[1]:
                    errors.append(f"z_approach.{key} must be inside motion.limits_mm.z")
    z_limits = config.get("motion", {}).get("limits_mm", {}).get("z")
    z_travel = config.get("motion", {}).get("z_travel_mm")
    if isinstance(z_limits, list) and len(z_limits) == 2 and numeric(z_travel) and not z_limits[0] <= z_travel <= z_limits[1]:
        errors.append("motion.z_travel_mm must be inside motion.limits_mm.z")
    for stage in ("a", "b"):
        limits = config.get("manual_stages", {}).get(stage, {}).get("limits_mm", {}).get("z")
        if isinstance(limits, list) and len(limits) == 2:
            if numeric(z_travel) and not limits[0] <= z_travel <= limits[1]:
                errors.append(f"motion.z_travel_mm must be inside Manual Stage {stage.upper()} Z limits")
            if config.get("z_approach", {}).get("enabled"):
                for key in ("start_mm", "stop_mm"):
                    value = config["z_approach"].get(key)
                    if numeric(value) and not limits[0] <= value <= limits[1]:
                        errors.append(f"z_approach.{key} must be inside Manual Stage {stage.upper()} Z limits")
    if config.get("_build_notes"):
        warnings.extend(str(note) for note in config["_build_notes"])

    return errors, warnings


def validate_vision_profile(errors: list[str], config: dict[str, Any], path: Path) -> None:
    try:
        profile = load_profile(path)
    except Exception as exc:
        errors.append(f"invalid z_approach.vision_calibration_path: {exc}")
        return
    camera_index = config.get("camera", {}).get("opencv_index")
    if isinstance(camera_index, (int, float)) and int(profile["camera"]["index"]) != int(camera_index):
        errors.append("vision calibration camera does not match camera.opencv_index")
    for stage in ("a", "b"):
        entry = profile["stages"].get(stage)
        if not entry:
            errors.append(f"vision calibration is missing Stage {stage.upper()}")
            continue
        serial = str(config.get("manual_stages", {}).get(stage, {}).get("serial_number", ""))
        if str(entry.get("serial_number", "")) != serial:
            errors.append(f"vision calibration serial does not match Stage {stage.upper()}")


def require(errors: list[str], config: dict[str, Any], *keys: str) -> None:
    value: Any = config
    try:
        for key in keys:
            value = value[key]
    except KeyError:
        errors.append("missing " + ".".join(keys))
        return
    if not configured(value):
        errors.append("missing " + ".".join(keys))


def require_number(errors: list[str], config: dict[str, Any], *keys: str) -> None:
    value: Any = config
    try:
        for key in keys:
            value = value[key]
    except KeyError:
        errors.append("missing " + ".".join(keys))
        return
    if not numeric(value):
        errors.append("must be numeric " + ".".join(keys))


def require_axes(errors: list[str], config: dict[str, Any]) -> None:
    channels = config.get("motion", {}).get("axis_channels", {})
    for axis in ("x", "y", "z"):
        if axis not in channels:
            errors.append(f"missing motion.axis_channels.{axis}")
        elif not isinstance(channels[axis], int) or isinstance(channels[axis], bool) or channels[axis] not in (1, 2, 3):
            errors.append(f"must be integer motion.axis_channels.{axis}")
    if len({channels.get(axis) for axis in ("x", "y", "z")}) != 3:
        errors.append("motion.axis_channels must use channels 1, 2, 3 exactly once")


def require_limits(errors: list[str], config: dict[str, Any]) -> None:
    limits = config.get("motion", {}).get("limits_mm", {})
    for axis in ("x", "y", "z"):
        values = limits.get(axis) if isinstance(limits, dict) else None
        if not isinstance(values, list) or len(values) != 2 or not all(numeric(value) for value in values):
            errors.append(f"missing motion.limits_mm.{axis}")
        elif values[0] >= values[1]:
            errors.append(f"invalid motion.limits_mm.{axis}")


def require_motion_profile(errors: list[str], warnings: list[str], config: dict[str, Any]) -> None:
    motion = config.get("motion", {})
    velocity = motion.get("max_velocity_mm_s")
    acceleration = motion.get("acceleration_mm_s2")
    if not configured(velocity) and not configured(acceleration):
        warnings.append("motion speed is managed by Kinesis")
    elif not numeric(velocity) or not numeric(acceleration) or velocity <= 0 or acceleration <= 0:
        errors.append("motion.max_velocity_mm_s and motion.acceleration_mm_s2 must be positive numbers")


def numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

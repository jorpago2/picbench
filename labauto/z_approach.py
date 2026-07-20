from __future__ import annotations

import json
import math
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from labauto.bsc_config import axis_channel, bsc_from_config, stage_position_mm
from labauto.camera import OpenCVCamera
from labauto.config import configured, require_config
from labauto.thorlabs_bsc203 import BSC203
from labauto.visa_devices import VisaLaser, VisaPowerMeter
from labauto.vision_calibration import VisionGuard


def approach_z(config: dict[str, Any], *, state_dir: Path | None = None) -> Path:
    state_dir = state_dir or Path(config.get("startup", {}).get("state_dir", "workspace/state"))
    with (
        bsc_from_config(config) as controller,
        VisaLaser(config) as laser,
        VisaPowerMeter(config) as meter,
        OpenCVCamera(int(require_config(config, "camera", "opencv_index"))) as camera,
    ):
        report = None
        laser_auto_on = config.get("z_approach", {}).get("laser_output_on", True)
        try:
            prepare_z_laser(config, laser, meter)
            report = approach_z_with_sessions(config, controller, meter, camera)
        finally:
            if (
                laser_auto_on
                and (report is None or report["status"] != "ok")
                and config.get("z_approach", {}).get("laser_output_off_on_failure", True)
            ):
                laser.output(False)
    path = write_z_report(report, state_dir)
    if report["status"] != "ok":
        raise RuntimeError(f"z approach failed: {report['stop_reason']}; report saved at {path}")
    return path


def approach_z_with_sessions(
    config: dict[str, Any],
    controller: BSC203,
    meter: VisaPowerMeter,
    camera: OpenCVCamera,
) -> dict[str, Any]:
    settings = config.get("z_approach", {})
    start = stage_position_mm(config, controller)
    start_mm = float(settings["start_mm"]) if configured(settings.get("start_mm")) else start["z"]
    stop_mm = float(require_config(config, "z_approach", "stop_mm"))
    step_um = float(settings.get("step_um", 2.0))
    settle_ms = int(settings.get("settle_ms", 100))
    target_power_w = optional_float(settings, "target_power_w")
    visual_stop = optional_float(settings, "visual_change_stop")
    roi = settings.get("roi")
    vision_guard = VisionGuard.from_config(config)

    if step_um <= 0:
        raise ValueError("z_approach.step_um must be > 0")
    if target_power_w is None and visual_stop is None and vision_guard is None:
        raise ValueError("configure power, visual change or a vision calibration")

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "status": "failed",
        "stop_reason": "limit_reached",
        "start_position_mm": start,
        "start_mm": start_mm,
        "stop_mm": stop_mm,
        "step_um": step_um,
        "settle_ms": settle_ms,
        "target_power_w": target_power_w,
        "visual_change_stop": visual_stop,
        "fiber_angle_deg": optional_float(settings, "fiber_angle_deg"),
        "angle_axis": settings.get("angle_axis", "x"),
        "angle_sign": float(settings.get("angle_sign", 1.0)),
        "roi": roi,
        "vision_stage": vision_guard.stage if vision_guard else None,
        "vision_calibration_path": str(vision_guard.path) if vision_guard else None,
        "samples": [],
    }

    move_z_with_lateral_compensation(config, controller, start, start_mm)
    baseline_frame = camera.read()
    baseline_power = meter.read_power_w()
    report["baseline_position_mm"] = stage_position_mm(config, controller)
    report["baseline_power_w"] = baseline_power
    baseline_vision = vision_guard.evaluate(baseline_frame) if vision_guard else None
    report["baseline_vision"] = baseline_vision

    distance_mm = abs(stop_mm - start_mm)
    step_mm = step_um / 1000.0
    direction = 1 if stop_mm > start_mm else -1
    steps = int(math.ceil(distance_mm / step_mm))

    if baseline_vision is not None and not baseline_vision["ok"]:
        report["stop_reason"] = baseline_vision["reason"]

    for index in range(steps + 1) if report["stop_reason"] == "limit_reached" else ():
        z_mm = start_mm + direction * min(index * step_mm, distance_mm)
        compensation = move_z_with_lateral_compensation(config, controller, start, z_mm)
        time.sleep(settle_ms / 1000.0)
        frame = camera.read()
        power_w = meter.read_power_w()
        change = visual_change(frame, baseline_frame, roi)
        vision = vision_guard.evaluate(frame) if vision_guard else None
        sample = {
            "z_mm": z_mm,
            "power_w": power_w,
            "power_delta_w": power_w - baseline_power,
            "visual_change": change,
            "timestamp": datetime.now().isoformat(),
        }
        if vision is not None:
            sample["vision"] = vision
        if compensation is not None:
            axis, axis_mm = compensation
            sample[f"{axis}_compensated_mm"] = axis_mm
        report["samples"].append(sample)

        if vision is not None and not vision["ok"]:
            report["stop_reason"] = vision["reason"]
            break
        if vision is not None and vision["stop"]:
            report["status"] = "ok"
            report["stop_reason"] = "vision_clearance"
            break
        if target_power_w is not None and power_w >= target_power_w:
            report["status"] = "ok"
            report["stop_reason"] = "target_power"
            break
        if index and visual_stop is not None and change >= visual_stop:
            report["status"] = "ok"
            report["stop_reason"] = "visual_change"
            break

    if report["status"] != "ok" and settings.get("retract_on_failure", True):
        controller.move_to_mm(axis_channel(config, "z"), start["z"])
        compensation = lateral_compensation(config, start, stop_mm)
        if compensation is not None:
            axis, _axis_mm = compensation
            controller.move_to_mm(axis_channel(config, axis), start[axis])
        report["retracted_to_mm"] = start["z"]

    report["final_position_mm"] = stage_position_mm(config, controller)
    return report


def move_z_with_lateral_compensation(
    config: dict[str, Any],
    controller: BSC203,
    start: dict[str, float],
    z_mm: float,
) -> tuple[str, float] | None:
    compensation = lateral_compensation(config, start, z_mm)
    if compensation is not None:
        axis, axis_mm = compensation
        controller.move_to_mm(axis_channel(config, axis), axis_mm)
    controller.move_to_mm(axis_channel(config, "z"), z_mm)
    return compensation


def lateral_compensation(config: dict[str, Any], start: dict[str, float], z_mm: float) -> tuple[str, float] | None:
    settings = config.get("z_approach", {})
    angle_deg = optional_float(settings, "fiber_angle_deg")
    if angle_deg is None:
        return None
    axis = settings.get("angle_axis", "x")
    if axis not in ("x", "y"):
        raise ValueError("z_approach.angle_axis must be x or y")
    sign = float(settings.get("angle_sign", 1.0))
    axis_mm = start[axis] + sign * (z_mm - start["z"]) * math.tan(math.radians(angle_deg))
    return axis, axis_mm


def prepare_z_laser(
    config: dict[str, Any],
    laser: VisaLaser,
    meter: VisaPowerMeter,
    wavelength_nm: float | None = None,
) -> dict[str, Any]:
    settings = config.get("z_approach", {})
    wavelength_nm = wavelength_nm if wavelength_nm is not None else optional_float(settings, "wavelength_nm")
    if wavelength_nm is not None:
        meter.set_wavelength_nm(wavelength_nm)
        laser.set_wavelength_nm(wavelength_nm)
    output = "unchanged"
    if settings.get("laser_output_on", True):
        laser.output(True)
        output = "on"
    return {"wavelength_nm": wavelength_nm, "output": output}


def visual_change(frame, baseline, roi: list[float] | None = None) -> float:
    cv2 = OpenCVCamera._cv2()
    current = crop_roi(to_gray(frame), roi)
    reference = crop_roi(to_gray(baseline), roi)
    return float(cv2.absdiff(current, reference).mean() / 255.0)


def to_gray(frame):
    cv2 = OpenCVCamera._cv2()
    if len(frame.shape) == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


def crop_roi(frame, roi: list[float] | None):
    if not roi:
        return frame
    if len(roi) != 4:
        raise ValueError("z_approach.roi must be [x, y, width, height]")
    height, width = frame.shape[:2]
    x, y, w, h = [float(value) for value in roi]
    x0 = max(0, min(width - 1, int(width * x)))
    y0 = max(0, min(height - 1, int(height * y)))
    x1 = max(x0 + 1, min(width, int(width * (x + w))))
    y1 = max(y0 + 1, min(height, int(height * (y + h))))
    return frame[y0:y1, x0:x1]


def optional_float(settings: dict[str, Any], key: str) -> float | None:
    value = settings.get(key)
    return float(value) if configured(value) else None


def write_z_report(report: dict[str, Any], state_dir: Path, suffix: str = "") -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    tag = f"_{suffix}" if suffix else ""
    path = state_dir / f"z_approach{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.copyfile(path, state_dir / f"z_approach{tag}_latest.json")
    return path

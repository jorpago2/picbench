from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from labauto.bsc_config import axis_channel, bsc_from_config, stage_position_mm
from labauto.thorlabs_bsc203 import BSC203
from labauto.visa_devices import VisaPowerMeter


def grid_offsets_um(span_um: float, step_um: float) -> list[float]:
    if span_um < 0:
        raise ValueError("span_um must be >= 0")
    if step_um <= 0:
        raise ValueError("step_um must be > 0")
    span = Decimal(str(span_um))
    step = Decimal(str(step_um))
    value = -span
    offsets = []
    while value <= span:
        offsets.append(float(value))
        value += step
    if offsets[-1] != float(span):
        offsets.append(float(span))
    return offsets


def align_xy(
    config: dict[str, Any],
    *,
    device_id: str,
    span_um: float,
    step_um: float,
    settle_ms: int = 100,
    state_dir: Path | None = None,
) -> Path:
    state_dir = state_dir or Path(config.get("startup", {}).get("state_dir", "workspace/state"))
    with bsc_from_config(config) as controller, VisaPowerMeter(config) as meter:
        try:
            report = align_xy_with_sessions(
                config,
                controller,
                meter,
                device_id=device_id,
                span_um=span_um,
                step_um=step_um,
                settle_ms=settle_ms,
            )
        except Exception:
            controller.emergency_stop([axis_channel(config, axis) for axis in ("x", "y", "z")])
            raise
    return write_alignment_report(report, state_dir)


def align_xy_with_sessions(
    config: dict[str, Any],
    controller: BSC203,
    meter: VisaPowerMeter,
    *,
    device_id: str,
    span_um: float,
    step_um: float,
    settle_ms: int = 100,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "device_id": device_id,
        "coarse_span_um": span_um,
        "coarse_step_um": step_um,
        "fine_span_um": min(span_um, step_um),
        "fine_step_um": step_um / 4.0,
        "settle_ms": settle_ms,
        "z_policy": "z is not moved during xy alignment",
        "passes": [],
        "samples": [],
    }

    start = stage_position_mm(config, controller)
    report["start_position_mm"] = start
    best: dict[str, Any] | None = None

    def scan(name: str, center: dict[str, float], scan_span_um: float, scan_step_um: float) -> None:
        nonlocal best
        offsets = grid_offsets_um(scan_span_um, scan_step_um)
        report["passes"].append(
            {
                "name": name,
                "center_x_mm": center["x"],
                "center_y_mm": center["y"],
                "span_um": scan_span_um,
                "step_um": scan_step_um,
                "points": len(offsets) * len(offsets),
            }
        )
        for dx_um in offsets:
            for dy_um in offsets:
                x_mm = center["x"] + dx_um / 1000.0
                y_mm = center["y"] + dy_um / 1000.0
                controller.move_to_mm(axis_channel(config, "x"), x_mm)
                controller.move_to_mm(axis_channel(config, "y"), y_mm)
                time.sleep(settle_ms / 1000.0)
                power_w = meter.read_power_w()
                sample = {
                    "pass": name,
                    "dx_um": dx_um,
                    "dy_um": dy_um,
                    "x_mm": x_mm,
                    "y_mm": y_mm,
                    "z_mm": start["z"],
                    "power_w": power_w,
                }
                report["samples"].append(sample)
                if best is None or power_w > best["power_w"]:
                    best = sample

    scan("coarse", start, span_um, step_um)

    if best is None:
        raise RuntimeError("alignment produced no samples")

    scan(
        "fine",
        {"x": best["x_mm"], "y": best["y_mm"], "z": start["z"]},
        report["fine_span_um"],
        report["fine_step_um"],
    )

    controller.move_to_mm(axis_channel(config, "x"), best["x_mm"])
    controller.move_to_mm(axis_channel(config, "y"), best["y_mm"])
    report["best"] = best
    report["final_position_mm"] = stage_position_mm(config, controller)
    return report


def write_alignment_report(report: dict[str, Any], state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"alignment_{report['device_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.copyfile(path, state_dir / "alignment_latest.json")
    return path

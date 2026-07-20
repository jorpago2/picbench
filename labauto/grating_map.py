from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


VERSION = 1


def save_grating_map(
    path: Path,
    *,
    camera_index: int,
    resolution: tuple[int, int],
    devices_path: Path,
    pairs: dict[str, dict[str, list[float]]],
) -> dict[str, Any]:
    width, height = resolution
    if width <= 0 or height <= 0 or not pairs:
        raise ValueError("record at least one grating pair before saving")
    for device_id, pair in pairs.items():
        if set(pair) != {"input_norm", "output_norm"}:
            raise ValueError(f"{device_id} does not have an input/output pair")
        for point in pair.values():
            if len(point) != 2 or not all(0 <= float(value) <= 1 for value in point):
                raise ValueError(f"{device_id} contains an invalid image point")
    profile = {
        "version": VERSION,
        "camera": {"index": int(camera_index), "resolution": [width, height]},
        "devices_csv": str(devices_path),
        "devices": pairs,
        "updated_at": datetime.now().isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return profile


def load_grating_map(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    camera = profile.get("camera", {})
    if (
        profile.get("version") != VERSION
        or not isinstance(profile.get("devices"), dict)
        or not isinstance(camera.get("index"), int)
        or not isinstance(camera.get("resolution"), list)
        or len(camera["resolution"]) != 2
    ):
        raise ValueError("unsupported grating map")
    return profile


def is_compatible(profile: dict[str, Any], camera_index: int, resolution: tuple[int, int]) -> bool:
    return profile["camera"] == {"index": int(camera_index), "resolution": list(resolution)}


def plan_xy_move(
    pair: dict[str, list[float]],
    resolution: tuple[int, int],
    stages: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Convert the two image targets into absolute logical stage positions."""
    width, height = resolution
    plan = {}
    for stage, point_name in (("a", "input_norm"), ("b", "output_norm")):
        data = stages[stage]
        point = pair[point_name]
        tip = data["tip_px"]
        matrix = data["pixel_to_stage_um"]
        delta_px = [point[0] * width - tip[0], point[1] * height - tip[1]]
        delta_um = [
            matrix[0][0] * delta_px[0] + matrix[0][1] * delta_px[1],
            matrix[1][0] * delta_px[0] + matrix[1][1] * delta_px[1],
        ]
        current = data["position_mm"]
        target = {"x": current["x"] + delta_um[0] / 1000.0, "y": current["y"] + delta_um[1] / 1000.0}
        values = [*delta_px, *delta_um, *target.values()]
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError(f"Stage {stage.upper()} grating move is not finite")
        plan[stage] = {
            "point": "input" if stage == "a" else "output",
            "tip_px": list(map(float, tip)),
            "target_px": [point[0] * width, point[1] * height],
            "delta_px": delta_px,
            "delta_um": delta_um,
            "current_mm": {axis: float(current[axis]) for axis in ("x", "y", "z")},
            "target_mm": target,
        }
    return plan


def assess_xy_correction(
    plan: dict[str, dict[str, Any]],
    *,
    tolerance_um: float,
    max_correction_um: float,
    corrections: int,
    max_corrections: int,
    previous_errors: dict[str, float] | None = None,
) -> tuple[dict[str, float], bool]:
    """Return residual magnitudes and whether another bounded correction is allowed."""
    errors = {stage: math.hypot(*map(float, move["delta_um"])) for stage, move in plan.items()}
    if all(error <= tolerance_um for error in errors.values()):
        return errors, False
    if corrections >= max_corrections:
        raise RuntimeError(f"fiber positioning did not converge after {corrections} correction(s)")
    for stage, error in errors.items():
        if error <= tolerance_um:
            continue
        if error > max_correction_um:
            raise RuntimeError(
                f"Stage {stage.upper()} residual {error:.1f} um exceeds the {max_correction_um:.1f} um correction limit"
            )
        previous = (previous_errors or {}).get(stage)
        if previous is not None and error > previous * 1.25:
            raise RuntimeError(
                f"Stage {stage.upper()} residual increased from {previous:.1f} to {error:.1f} um"
            )
    return errors, True


def _self_check() -> None:
    profile = {"camera": {"index": 0, "resolution": [1920, 1080]}}
    assert is_compatible(profile, 0, (1920, 1080))
    assert not is_compatible(profile, 1, (1920, 1080))
    move = plan_xy_move(
        {"input_norm": [0.5, 0.5], "output_norm": [0.75, 0.25]},
        (100, 100),
        {
            "a": {"tip_px": [40, 40], "pixel_to_stage_um": [[2, 0], [0, 3]], "position_mm": {"x": 1, "y": 2, "z": 3}},
            "b": {"tip_px": [80, 20], "pixel_to_stage_um": [[1, 0], [0, 1]], "position_mm": {"x": 2, "y": 1, "z": 3}},
        },
    )
    assert move["a"]["target_mm"] == {"x": 1.02, "y": 2.03}
    assert move["b"]["delta_um"] == [-5.0, 5.0]
    errors, correct = assess_xy_correction(
        move, tolerance_um=4, max_correction_um=50, corrections=0, max_corrections=3
    )
    assert correct and round(errors["a"], 3) == round(math.hypot(20, 30), 3)
    settled = {stage: {**data, "delta_um": [1.0, 2.0]} for stage, data in move.items()}
    assert assess_xy_correction(
        settled, tolerance_um=4, max_correction_um=50, corrections=1, max_corrections=3
    )[1] is False
    try:
        assess_xy_correction(
            move,
            tolerance_um=4,
            max_correction_um=50,
            corrections=1,
            max_corrections=3,
            previous_errors={"a": 20, "b": 8},
        )
    except RuntimeError as exc:
        assert "increased" in str(exc)
    else:
        raise AssertionError("diverging correction was not rejected")


if __name__ == "__main__":
    _self_check()

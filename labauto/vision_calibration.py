from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any


PROFILE_VERSION = 1
SAMPLE_NAMES = ("far", "near", "minimum_safe")


def save_stage_calibration(
    path: Path,
    *,
    stage: str,
    camera_index: int,
    serial_number: str,
    roi_px: tuple[int, int, int, int],
    chip_line_px: tuple[tuple[int, int], tuple[int, int]],
    samples: dict[str, dict[str, Any]],
    xy_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save one guided fiber calibration and its image templates."""
    if stage not in ("a", "b"):
        raise ValueError("stage must be a or b")
    if not serial_number or str(serial_number).startswith("TODO"):
        raise ValueError(f"select the Stage {stage.upper()} controller before calibrating")
    if set(samples) != set(SAMPLE_NAMES):
        raise ValueError("record Far, Near and Minimum safe before saving")

    first = samples["far"]["frame"]
    height, width = first.shape[:2]
    if any(sample["frame"].shape[:2] != (height, width) for sample in samples.values()):
        raise ValueError("camera resolution changed during calibration")
    x, y, roi_w, roi_h = roi_px
    if roi_w < 20 or roi_h < 20 or x < 0 or y < 0 or x + roi_w > width or y + roi_h > height:
        raise ValueError("the calibration ROI is invalid or too small")

    clearances = {
        name: point_line_distance(sample["tip_px"], chip_line_px[0], chip_line_px[1])
        for name, sample in samples.items()
    }
    direction = 1 if clearances["minimum_safe"] > clearances["far"] else -1
    span = abs(clearances["minimum_safe"] - clearances["far"])
    progress = direction * (clearances["near"] - clearances["far"])
    if span < 8:
        raise ValueError("Far and Minimum safe must differ by at least 8 pixels")
    if not 0 < progress < span:
        raise ValueError("Near clearance must lie between Far and Minimum safe")

    path.parent.mkdir(parents=True, exist_ok=True)
    asset_dir = path.parent / f"{path.stem}_assets" / f"stage_{stage}"
    asset_dir.mkdir(parents=True, exist_ok=True)
    cv2 = _cv2()
    saved_samples = {}
    for name in SAMPLE_NAMES:
        sample = samples[name]
        frame = sample["frame"]
        tip_x, tip_y = map(int, sample["tip_px"])
        template, tip_offset = extract_template(frame, (tip_x, tip_y))
        frame_path = asset_dir / f"{name}.png"
        template_path = asset_dir / f"{name}_template.png"
        if not cv2.imwrite(str(frame_path), frame) or not cv2.imwrite(str(template_path), template):
            raise RuntimeError("could not save calibration images")
        saved_samples[name] = {
            "position_mm": sample["position_mm"],
            "tip_norm": [tip_x / width, tip_y / height],
            "clearance_px": clearances[name],
            "frame": str(frame_path.relative_to(path.parent)),
            "template": str(template_path.relative_to(path.parent)),
            "tip_in_template_px": tip_offset,
        }

    margin = max(3.0, span * 0.1)
    stage_profile = {
        "serial_number": str(serial_number),
        "roi": [x / width, y / height, roi_w / width, roi_h / height],
        "chip_line_norm": [[px / width, py / height] for px, py in chip_line_px],
        "samples": saved_samples,
        "approach_direction": direction,
        "stop_clearance_px": clearances["minimum_safe"] - direction * margin,
        "confidence_min": 0.55,
        "corridor_px": max(20.0, math.dist(samples["far"]["tip_px"], samples["minimum_safe"]["tip_px"]) * 0.25),
        "calibrated_at": datetime.now().isoformat(),
    }
    if xy_mapping is not None:
        stage_profile["xy_mapping"] = xy_mapping
    profile = load_profile(path) if path.exists() else {"version": PROFILE_VERSION, "stages": {}}
    camera = profile.get("camera")
    if camera and (camera.get("index"), camera.get("resolution")) != (camera_index, [width, height]):
        raise ValueError("the existing profile belongs to another camera or resolution")
    profile.update({"version": PROFILE_VERSION, "camera": {"index": camera_index, "resolution": [width, height]}})
    profile.setdefault("stages", {})[stage] = stage_profile
    path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    return stage_profile


class VisionGuard:
    def __init__(self, path: Path, profile: dict[str, Any], stage: str) -> None:
        self.path = path
        self.camera = profile["camera"]
        self.stage = stage
        self.data = profile["stages"][stage]
        cv2 = _cv2()
        self.templates = []
        for sample in self.data["samples"].values():
            image = cv2.imread(str(path.parent / sample["template"]), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise RuntimeError(f"missing vision template: {sample['template']}")
            self.templates.append((image, sample["tip_in_template_px"]))

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> VisionGuard | None:
        settings = config.get("z_approach", {})
        value = settings.get("vision_calibration_path")
        if not value:
            return None
        path = Path(value)
        profile = load_profile(path)
        stage = settings.get("vision_stage")
        if stage not in ("a", "b"):
            serial = str(config.get("motion", {}).get("serial_number", ""))
            matches = [name for name, data in profile.get("stages", {}).items() if data.get("serial_number") == serial]
            if len(matches) != 1:
                raise ValueError("set z_approach.vision_stage to a or b")
            stage = matches[0]
        if stage not in profile.get("stages", {}):
            raise ValueError(f"Stage {stage.upper()} has no vision calibration")
        expected_serial = str(profile["stages"][stage].get("serial_number", ""))
        actual_serial = str(config.get("motion", {}).get("serial_number", ""))
        if expected_serial and expected_serial != actual_serial:
            raise ValueError(f"vision calibration serial mismatch for Stage {stage.upper()}")
        expected_camera = profile["camera"].get("index")
        if int(config.get("camera", {}).get("opencv_index")) != int(expected_camera):
            raise ValueError("vision calibration camera does not match the selected camera")
        return cls(path, profile, stage)

    def evaluate(self, frame) -> dict[str, Any]:
        located = self.locate_tip(frame)
        if not located["ok"]:
            return located
        height, width = frame.shape[:2]
        confidence, tip = located["confidence"], located["tip_px"]
        far_tip = denormalize_point(self.data["samples"]["far"]["tip_norm"], width, height)
        safe_tip = denormalize_point(self.data["samples"]["minimum_safe"]["tip_norm"], width, height)
        corridor_error = point_segment_distance(tip, far_tip, safe_tip)
        if confidence < float(self.data["confidence_min"]) or corridor_error > float(self.data["corridor_px"]):
            return {
                "ok": False,
                "reason": "fiber_tracking_lost",
                "confidence": confidence,
                "tip_px": list(map(float, tip)),
                "corridor_error_px": corridor_error,
            }

        line = [denormalize_point(point, width, height) for point in self.data["chip_line_norm"]]
        clearance = point_line_distance(tip, line[0], line[1])
        direction = int(self.data["approach_direction"])
        threshold = float(self.data["stop_clearance_px"])
        reached = clearance >= threshold if direction > 0 else clearance <= threshold
        return {
            "ok": True,
            "reason": "minimum_safe_clearance" if reached else "clear",
            "stop": reached,
            "confidence": confidence,
            "tip_px": list(map(float, tip)),
            "clearance_px": clearance,
            "stop_clearance_px": threshold,
            **self._tip_offset(tip, far_tip),
        }

    def locate_tip(self, frame, *, full_frame: bool = False) -> dict[str, Any]:
        """Locate the enrolled fiber without applying the Z-approach corridor."""
        cv2 = _cv2()
        height, width = frame.shape[:2]
        if [width, height] != self.camera["resolution"]:
            return {"ok": False, "reason": "camera_resolution_changed"}
        if full_frame:
            x, y, roi_w, roi_h = 0, 0, width, height
        else:
            x, y, roi_w, roi_h = normalized_roi_to_pixels(self.data["roi"], width, height)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        search = gray[y:y + roi_h, x:x + roi_w]
        best = None
        for template, tip_offset in self.templates:
            if template.shape[0] > search.shape[0] or template.shape[1] > search.shape[1]:
                continue
            _minimum, score, _minimum_location, location = cv2.minMaxLoc(
                cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            )
            if math.isfinite(score) and (best is None or score > best[0]):
                best = (float(score), (x + location[0] + tip_offset[0], y + location[1] + tip_offset[1]))
        if best is None:
            return {"ok": False, "reason": "fiber_not_found"}
        return {"ok": True, "confidence": best[0], "tip_px": list(map(float, best[1]))}

    def _tip_offset(self, tip, far_tip) -> dict[str, list[float]]:
        mapping = self.data.get("xy_mapping")
        if not mapping:
            return {}
        matrix = mapping["pixel_to_stage_um"]
        dx, dy = tip[0] - far_tip[0], tip[1] - far_tip[1]
        return {"tip_stage_offset_um": [matrix[0][0] * dx + matrix[0][1] * dy, matrix[1][0] * dx + matrix[1][1] * dy]}


def calculate_xy_mapping(
    reference_frame,
    reference_tip_px: tuple[int, int],
    roi_px: tuple[int, int, int, int],
    moves: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Calculate the camera/stage affine basis from one pure X and one pure Y move."""
    if set(moves) != {"x", "y"}:
        raise ValueError("XY mapping requires one X move and one Y move")
    columns = {}
    details = {}
    for axis in ("x", "y"):
        delta_um = float(moves[axis]["delta_mm"]) * 1000.0
        if abs(delta_um) < 1:
            raise ValueError(f"measured {axis.upper()} stage displacement is too small")
        tracked = locate_tip(reference_frame, reference_tip_px, moves[axis]["frame"], roi_px)
        if tracked["confidence"] < 0.55:
            raise ValueError(f"could not track the fiber after the {axis.upper()} move")
        dx = tracked["tip_px"][0] - reference_tip_px[0]
        dy = tracked["tip_px"][1] - reference_tip_px[1]
        if math.hypot(dx, dy) < 3:
            raise ValueError(f"{axis.upper()} move produced less than 3 pixels; increase the calibration step")
        columns[axis] = (dx / delta_um, dy / delta_um)
        details[axis] = {
            "stage_delta_um": delta_um,
            "pixel_delta": [dx, dy],
            "confidence": tracked["confidence"],
        }

    stage_to_pixel = [
        [columns["x"][0], columns["y"][0]],
        [columns["x"][1], columns["y"][1]],
    ]
    determinant = stage_to_pixel[0][0] * stage_to_pixel[1][1] - stage_to_pixel[0][1] * stage_to_pixel[1][0]
    if abs(determinant) < 1e-6:
        raise ValueError("camera mapping is singular; check the axis channels and repeat with a larger step")
    pixel_to_stage = [
        [stage_to_pixel[1][1] / determinant, -stage_to_pixel[0][1] / determinant],
        [-stage_to_pixel[1][0] / determinant, stage_to_pixel[0][0] / determinant],
    ]
    return {
        "stage_um_to_pixel": stage_to_pixel,
        "pixel_to_stage_um": pixel_to_stage,
        "moves": details,
        "calibrated_at": datetime.now().isoformat(),
    }


def locate_tip(reference_frame, reference_tip_px, frame, roi_px) -> dict[str, Any]:
    cv2 = _cv2()
    template, tip_offset = extract_template(reference_frame, reference_tip_px)
    x, y, width, height = roi_px
    search = frame[y:y + height, x:x + width]
    gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY) if len(search.shape) == 3 else search
    if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
        raise ValueError("fiber template is larger than the ROI")
    _minimum, confidence, _minimum_location, location = cv2.minMaxLoc(
        cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    )
    if not math.isfinite(confidence):
        raise ValueError("fiber tracking returned an invalid confidence")
    return {
        "tip_px": [x + location[0] + tip_offset[0], y + location[1] + tip_offset[1]],
        "confidence": float(confidence),
    }


def extract_template(frame, tip_px):
    cv2 = _cv2()
    height, width = frame.shape[:2]
    tip_x, tip_y = map(int, tip_px)
    radius = max(12, min(width, height) // 45)
    left, top = max(0, tip_x - radius), max(0, tip_y - radius)
    right, bottom = min(width, tip_x + radius + 1), min(height, tip_y + radius + 1)
    template = frame[top:bottom, left:right]
    gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) if len(template.shape) == 3 else template
    if template.size == 0 or float(gray.std()) < 2:
        raise ValueError("fiber template has insufficient contrast")
    return gray, [tip_x - left, tip_y - top]


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    camera = profile.get("camera")
    if (
        profile.get("version") != PROFILE_VERSION
        or not isinstance(profile.get("stages"), dict)
        or not isinstance(camera, dict)
        or not isinstance(camera.get("resolution"), list)
        or len(camera["resolution"]) != 2
    ):
        raise ValueError("unsupported vision calibration profile")
    return profile


def normalized_roi_to_pixels(roi: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, roi_w, roi_h = roi
    left = max(0, min(width - 1, round(x * width)))
    top = max(0, min(height - 1, round(y * height)))
    return left, top, max(1, min(width - left, round(roi_w * width))), max(1, min(height - top, round(roi_h * height)))


def denormalize_point(point: list[float], width: int, height: int) -> tuple[float, float]:
    return point[0] * width, point[1] * height


def point_line_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1:
        raise ValueError("chip line points are too close")
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length


def point_segment_distance(point, start, end) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if not length_squared:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    return math.dist(point, (start[0] + t * dx, start[1] + t * dy))


def _cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python is not installed") from exc
    return cv2


def _self_check() -> None:
    assert point_line_distance((5, 3), (0, 0), (10, 0)) == 3
    assert point_segment_distance((5, 2), (0, 0), (10, 0)) == 2
    assert normalized_roi_to_pixels([0.1, 0.2, 0.5, 0.5], 100, 80) == (10, 16, 50, 40)


if __name__ == "__main__":
    _self_check()

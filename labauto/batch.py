from __future__ import annotations

import json
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from labauto.alignment import align_xy_with_sessions, write_alignment_report
from labauto.bsc_config import automatic_stage_configs, axis_channel, bsc_from_config
from labauto.camera import OpenCVCamera
from labauto.config import require_config
from labauto.devices import Device, load_devices
from labauto.move_to_device import plan_move, retract_stages_then_move_xy, stage_positions_mm
from labauto.spectrum import (
    measure_spectrum_with_sessions,
    prepare_measurement_laser,
    validate_device_wavelengths,
    write_spectrum_metadata,
)
from labauto.visa_devices import VisaLaser, VisaPowerMeter
from labauto.z_approach import approach_z_with_sessions, prepare_z_laser, write_z_report


def select_batch_devices(devices: list[Device], reference_device_id: str, start_after_reference: bool) -> list[Device]:
    if not start_after_reference:
        return devices
    for index, device in enumerate(devices):
        if device.device_id == reference_device_id:
            return devices[index + 1 :]
    raise ValueError(f"reference device_id {reference_device_id!r} not found in devices CSV")


def run_batch(
    config: dict[str, Any],
    *,
    devices_csv: Path,
    reference_path: Path,
    out_root: Path,
    span_um: float,
    step_um: float,
    align_settle_ms: int,
    spectrum_settle_ms: int,
    start_after_reference: bool,
    resume: Path | None,
    pause: Callable[[str], None],
) -> Path:
    state_dir = Path(config.get("startup", {}).get("state_dir", "workspace/state"))
    z_retract_mm = float(require_config(config, "motion", "z_travel_mm"))
    auto_z = bool(config.get("z_approach", {}).get("enabled", False))

    if resume:
        batch_dir = resume
        report = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
        reference = json.loads(Path(report["reference_path"]).read_text(encoding="utf-8"))
    else:
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        devices = select_batch_devices(load_devices(devices_csv), reference["device_id"], start_after_reference)
        batch_dir = out_root / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        report = {
            "timestamp": datetime.now().isoformat(),
            "devices_csv": str(devices_csv),
            "reference_path": str(reference_path),
            "reference_device_id": reference["device_id"],
            "start_after_reference": start_after_reference,
            "z_retract_mm": z_retract_mm,
            "devices": [{"device_id": device.device_id, "status": "pending"} for device in devices],
            "connections": "persistent BSC203, laser, and PM320 for whole batch",
        }
        batch_dir.mkdir(parents=True, exist_ok=True)
        save_report(batch_dir, report)

    device_by_id = {device.device_id: device for device in load_devices(Path(report["devices_csv"]))}
    for device in device_by_id.values():
        validate_device_wavelengths(config, device)

    camera_session = (
        OpenCVCamera(int(require_config(config, "camera", "opencv_index"))) if auto_z else nullcontext(None)
    )
    stage_configs = automatic_stage_configs(config)
    with ExitStack() as stack:
        controllers = {
            stage: stack.enter_context(bsc_from_config({"motion": stage_config}))
            for stage, stage_config in stage_configs.items()
        }
        laser = stack.enter_context(VisaLaser(config))
        meter = stack.enter_context(VisaPowerMeter(config))
        camera = stack.enter_context(camera_session)
        batch_dir.mkdir(parents=True, exist_ok=True)
        for item in report["devices"]:
            if item.get("status") == "measured":
                continue
            device = device_by_id[item["device_id"]]
            try:
                item["status"] = "moving"
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)

                move = plan_move(reference, device)
                item["move"] = move
                item["positions_before_move_mm"] = stage_positions_mm(stage_configs, controllers)
                retract_stages_then_move_xy(stage_configs, controllers, move["target_stage_positions_mm"], z_retract_mm)
                item["positions_after_move_mm"] = stage_positions_mm(stage_configs, controllers)
                item["status"] = "moved"
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)

                if auto_z:
                    item["status"] = "approaching_z"
                    item["updated_at"] = datetime.now().isoformat()
                    save_report(batch_dir, report)
                    laser_auto_on = config.get("z_approach", {}).get("laser_output_on", True)
                    item["laser"] = prepare_z_laser(config, laser, meter, device.lambda_start_nm)
                    item["z_approach_paths"] = {}
                    item["z_approach_stop_reasons"] = {}
                    for stage, controller in controllers.items():
                        stage_run_config = deepcopy(config)
                        stage_run_config["motion"] = stage_configs[stage]
                        stage_run_config["z_approach"]["vision_stage"] = stage
                        if stage == "a":
                            stage_run_config["z_approach"]["target_power_w"] = None
                        roi_by_stage = config.get("z_approach", {}).get("roi_by_stage", {})
                        if stage in roi_by_stage:
                            stage_run_config["z_approach"]["roi"] = roi_by_stage[stage]
                        z_report = None
                        try:
                            z_report = approach_z_with_sessions(stage_run_config, controller, meter, camera)
                        finally:
                            if (
                                laser_auto_on
                                and (z_report is None or z_report["status"] != "ok")
                                and config.get("z_approach", {}).get("laser_output_off_on_failure", True)
                            ):
                                laser.output(False)
                        item["z_approach_paths"][stage] = str(write_z_report(z_report, state_dir, stage))
                        item["z_approach_stop_reasons"][stage] = z_report["stop_reason"]
                        if z_report["status"] != "ok":
                            raise RuntimeError(f"stage {stage.upper()} z approach failed: {z_report['stop_reason']}")
                else:
                    pause(f"{device.device_id}: bajar z manualmente a zona de trabajo y pulsar Enter")

                prepare_measurement_laser(laser, meter, device.lambda_start_nm)
                item["laser"] = "on_for_alignment_and_measurement"

                item["status"] = "aligning"
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)
                item["alignment_paths"] = {}
                item["alignment_best"] = {}
                for stage, controller in controllers.items():
                    alignment = align_xy_with_sessions(
                        {"motion": stage_configs[stage]},
                        controller,
                        meter,
                        device_id=f"{device.device_id}_stage_{stage}",
                        span_um=span_um,
                        step_um=step_um,
                        settle_ms=align_settle_ms,
                    )
                    item["alignment_paths"][stage] = str(write_alignment_report(alignment, state_dir))
                    item["alignment_best"][stage] = alignment["best"]
                item["status"] = "aligned"
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)

                pause(f"{device.device_id}: revisar alineamiento y pulsar Enter para medir espectro")

                item["status"] = "measuring"
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)
                spectrum_dir = batch_dir / f"spectrum_{device.device_id}"
                rows = measure_spectrum_with_sessions(
                    config,
                    device,
                    controller=controllers["a"],
                    laser=laser,
                    meter=meter,
                    csv_path=spectrum_dir / "spectrum.csv",
                    settle_ms=spectrum_settle_ms,
                    output_controller=controllers["b"],
                    output_config={"motion": stage_configs["b"]},
                )
                write_spectrum_metadata(spectrum_dir, device, spectrum_settle_ms, len(rows))
                item["spectrum_dir"] = str(spectrum_dir)
                item["spectrum_points"] = len(rows)
                item["status"] = "measured"
                item["updated_at"] = datetime.now().isoformat()
                laser.output(False)
                item["laser"] = "off_command_sent_after_measurement"
                save_report(batch_dir, report)
            except Exception as exc:
                item["emergency_stop"] = {
                    stage: controller.emergency_stop(
                        [axis_channel({"motion": stage_configs[stage]}, axis) for axis in ("x", "y", "z")]
                    )
                    for stage, controller in controllers.items()
                }
                try:
                    laser.output(False)
                    item["laser"] = "off_command_sent_after_failure"
                except Exception as laser_exc:
                    item["laser_stop_error"] = str(laser_exc)
                item["status"] = "failed"
                item["error"] = str(exc)
                item["updated_at"] = datetime.now().isoformat()
                save_report(batch_dir, report)
                raise

    save_report(batch_dir, report)
    return batch_dir


def save_report(batch_dir: Path, report: dict[str, Any]) -> None:
    (batch_dir / "batch.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

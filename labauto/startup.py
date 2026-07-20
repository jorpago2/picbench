from __future__ import annotations

import json
import shutil
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from labauto.bsc_config import automatic_stage_configs, axis_channel, bsc_from_config
from labauto.visa_devices import VisaLaser, VisaPowerMeter


def initialize_setup(config: dict[str, Any]) -> Path:
    startup = config.get("startup", {})
    state_dir = Path(startup.get("state_dir", "workspace/state"))
    state_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "laser": {},
        "power_meter": {},
        "motion": {
            "home_order": startup.get("home_order", ["z", "x", "y"]),
            "positions_before_mm": {},
            "positions_after_mm": {},
            "status_before": {},
            "status_after": {},
        },
    }

    try:
        with VisaLaser(config) as laser:
            report["laser"]["idn"] = laser.identify()
            if startup.get("laser_output_off_on_start", True):
                laser.output(False)
                report["laser"]["output"] = "off_command_sent"
    except Exception as exc:
        report["laser"]["error"] = str(exc)
        if startup.get("laser_output_off_on_start", True):
            raise RuntimeError(f"could not switch laser output off: {exc}") from exc

    try:
        with VisaPowerMeter(config) as meter:
            report["power_meter"]["idn"] = meter.identify()
    except Exception as exc:
        report["power_meter"]["idn_error"] = str(exc)

    home_timeout_ms = int(startup.get("home_timeout_ms", 60000))
    stage_configs = automatic_stage_configs(config)
    report["motion"]["stages"] = {}
    with ExitStack() as stack:
        controllers = {
            stage: stack.enter_context(bsc_from_config({"motion": stage_config}))
            for stage, stage_config in stage_configs.items()
        }
        try:
            for stage, controller in controllers.items():
                stage_config = {"motion": stage_configs[stage]}
                stage_report = {"idn": controller.identify(1), "positions_before_mm": {}, "positions_after_mm": {}, "status_before": {}, "status_after": {}}
                report["motion"]["stages"][stage] = stage_report
                for axis in stage_configs[stage]["axis_channels"]:
                    channel = axis_channel(stage_config, axis)
                    stage_report["positions_before_mm"][axis] = controller.position_mm(channel)
                    stage_report["status_before"][axis] = controller.status(channel)
                for axis in report["motion"]["home_order"]:
                    channel = axis_channel(stage_config, axis)
                    controller.home(channel, timeout_ms=home_timeout_ms)
                    stage_report["positions_after_mm"][axis] = controller.position_mm(channel)
                    stage_report["status_after"][axis] = controller.status(channel)
        except Exception:
            for stage, controller in controllers.items():
                controller.emergency_stop(list(stage_configs[stage]["axis_channels"].values()))
            raise

    path = state_dir / f"startup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.copyfile(path, state_dir / "startup_latest.json")
    return path

from __future__ import annotations

import argparse
import json
from pathlib import Path

from labauto.bsc_config import axis_channel, bsc_from_config, manual_stage_config
from labauto.config import load_hardware_config
from labauto.visa_devices import VisaLaser


def main() -> None:
    parser = argparse.ArgumentParser(description="Immediately stop BSC203 axes and disable laser output.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    config = load_hardware_config(parser.parse_args().config)
    report: dict[str, object] = {"motion": {}, "laser": "not configured"}
    report["motion"] = {}
    for stage in ("a", "b"):
        try:
            stage_config = {"motion": manual_stage_config(config, stage)}
            with bsc_from_config(stage_config) as controller:
                report["motion"][stage] = controller.emergency_stop(
                    [axis_channel(stage_config, axis) for axis in ("x", "y", "z")]
                )
        except Exception as exc:
            report["motion"][stage] = {"error": str(exc)}
    try:
        with VisaLaser(config) as laser:
            laser.output(False)
        report["laser"] = "off_command_sent"
    except Exception as exc:
        report["laser"] = str(exc)
    print(json.dumps(report, ensure_ascii=False))
    motion_ok = all(
        "error" not in result and all(value == "stopped" for value in result.values())
        for result in report["motion"].values()
    )
    if report["laser"] != "off_command_sent" or not motion_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

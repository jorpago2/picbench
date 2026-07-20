from __future__ import annotations

import argparse
from pathlib import Path

from labauto.bsc_config import axis_channel, bsc_from_config
from labauto.camera import OpenCVCamera
from labauto.config import load_hardware_config, require_config
from labauto.visa_devices import VisaLaser, VisaPowerMeter


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe hardware checks for the PIC setup.")
    parser.add_argument("--config", type=Path, default=Path("examples/hardware.example.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("identify")
    sub.add_parser("read-power")

    laser_wl = sub.add_parser("laser-wavelength")
    laser_wl.add_argument("--nm", type=float, required=True)
    laser_wl.add_argument("--yes", action="store_true")

    laser_out = sub.add_parser("laser-output")
    laser_out.add_argument("--on", action="store_true")
    laser_out.add_argument("--off", action="store_true")
    laser_out.add_argument("--yes", action="store_true")

    pm_wl = sub.add_parser("pm-wavelength")
    pm_wl.add_argument("--nm", type=float, required=True)

    capture = sub.add_parser("capture")
    capture.add_argument("--out", type=Path, default=Path("workspace/captures/frame.png"))

    pos = sub.add_parser("bsc-position")
    pos.add_argument("--axis", choices=("x", "y", "z"), required=True)

    home = sub.add_parser("bsc-home")
    home.add_argument("--axis", choices=("x", "y", "z"), required=True)
    home.add_argument("--yes", action="store_true")

    move = sub.add_parser("bsc-move")
    move.add_argument("--axis", choices=("x", "y", "z"), required=True)
    move.add_argument("--to-mm", type=float, required=True)
    move.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    config = load_hardware_config(args.config)

    if args.command == "identify":
        identify(config)
    elif args.command == "read-power":
        print(VisaPowerMeter(config).read_power_w())
    elif args.command == "laser-wavelength":
        require_yes(args.yes)
        VisaLaser(config).set_wavelength_nm(args.nm)
    elif args.command == "laser-output":
        require_yes(args.yes)
        if args.on == args.off:
            raise SystemExit("choose exactly one: --on or --off")
        VisaLaser(config).output(args.on)
    elif args.command == "pm-wavelength":
        VisaPowerMeter(config).set_wavelength_nm(args.nm)
    elif args.command == "capture":
        index = int(require_config(config, "camera", "opencv_index"))
        print(OpenCVCamera(index).capture(args.out))
    elif args.command == "bsc-position":
        with bsc_from_config(config) as controller:
            print(controller.position_mm(axis_channel(config, args.axis)))
    elif args.command == "bsc-home":
        require_yes(args.yes)
        with bsc_from_config(config) as controller:
            controller.home(axis_channel(config, args.axis))
    elif args.command == "bsc-move":
        require_yes(args.yes)
        with bsc_from_config(config) as controller:
            controller.move_to_mm(axis_channel(config, args.axis), args.to_mm)


def identify(config: dict) -> None:
    for label, factory in (("laser", VisaLaser), ("power_meter", VisaPowerMeter)):
        try:
            print(f"{label}: {factory(config).identify()}")
        except Exception as exc:
            print(f"{label}: {exc}")

    try:
        with bsc_from_config(config) as controller:
            print(f"bsc203: {controller.identify(1)}")
    except Exception as exc:
        print(f"bsc203: {exc}")

    try:
        index = int(require_config(config, "camera", "opencv_index"))
        print(f"camera: OpenCV index {index}")
    except Exception as exc:
        print(f"camera: {exc}")


def require_yes(yes: bool) -> None:
    if not yes:
        raise SystemExit("command refused; rerun with --yes")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

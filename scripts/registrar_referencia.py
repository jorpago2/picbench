from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.devices import find_device
from labauto.manual_align import keyboard_align_reference


def main() -> None:
    parser = argparse.ArgumentParser(description="Jog fibers with keyboard and save the aligned device reference.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--devices", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--enable-z", action="store_true")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("keyboard jogging refused; rerun with --yes")

    config = load_hardware_config(args.config)
    device = find_device(args.devices, args.device_id)
    keyboard_align_reference(config, device, enable_z=args.enable_z, state_dir=args.state_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

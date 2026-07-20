from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.devices import find_device
from labauto.move_to_device import move_to_device


def main() -> None:
    parser = argparse.ArgumentParser(description="Move from saved reference to another CSV device by relative offsets.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--devices", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--reference", type=Path, default=Path("workspace/state/reference_latest.json"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        raise SystemExit("move refused; rerun with --yes or use --dry-run")

    path = move_to_device(
        load_hardware_config(args.config),
        find_device(args.devices, args.device_id),
        reference_path=args.reference,
        state_dir=args.state_dir,
        dry_run=args.dry_run,
    )
    print(path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

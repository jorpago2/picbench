from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.z_approach import approach_z


def main() -> None:
    parser = argparse.ArgumentParser(description="Automatic safe z approach using PM320 and camera.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("z approach refused; rerun with --yes")

    print(approach_z(load_hardware_config(args.config), state_dir=args.state_dir))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

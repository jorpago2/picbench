from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.startup import initialize_setup


def main() -> None:
    parser = argparse.ArgumentParser(description="Safe startup with automatic BSC203 homing.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("startup refused; rerun with --yes")

    path = initialize_setup(load_hardware_config(args.config))
    print(path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

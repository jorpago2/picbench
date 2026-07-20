from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.config_validator import validate_hardware_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate hardware.real.json before running lab hardware.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    args = parser.parse_args()

    errors, warnings = validate_hardware_config(load_hardware_config(args.config))
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        raise SystemExit(1)
    print("config ok")


if __name__ == "__main__":
    main()

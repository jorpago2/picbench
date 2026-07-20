from __future__ import annotations

import argparse
from pathlib import Path

from labauto.alignment import align_xy
from labauto.config import load_hardware_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Local x/y optical alignment using the power meter.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--span-um", type=float, default=10.0)
    parser.add_argument("--step-um", type=float, default=2.0)
    parser.add_argument("--settle-ms", type=int, default=100)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("alignment refused; rerun with --yes")

    path = align_xy(
        load_hardware_config(args.config),
        device_id=args.device_id,
        span_um=args.span_um,
        step_um=args.step_um,
        settle_ms=args.settle_ms,
        state_dir=args.state_dir,
    )
    print(path)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

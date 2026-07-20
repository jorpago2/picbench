from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config import load_hardware_config
from labauto.devices import find_device
from labauto.spectrum import measure_spectrum


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure one device spectrum with persistent instrument connections.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--devices", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--out", type=Path, default=Path("workspace/results"))
    parser.add_argument("--settle-ms", type=int, default=100)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("spectrum measurement refused; rerun with --yes")

    run_dir = measure_spectrum(
        load_hardware_config(args.config),
        find_device(args.devices, args.device_id),
        out_root=args.out,
        settle_ms=args.settle_ms,
    )
    print(run_dir)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

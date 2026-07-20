from __future__ import annotations

import argparse
from pathlib import Path

from labauto.batch import run_batch
from labauto.config import load_hardware_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Semi-automatic batch measurement from a saved reference.")
    parser.add_argument("--config", type=Path, default=Path("config/hardware.real.json"))
    parser.add_argument("--devices", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("workspace/state/reference_latest.json"))
    parser.add_argument("--out", type=Path, default=Path("workspace/results"))
    parser.add_argument("--span-um", type=float, default=10.0)
    parser.add_argument("--step-um", type=float, default=2.0)
    parser.add_argument("--align-settle-ms", type=int, default=100)
    parser.add_argument("--spectrum-settle-ms", type=int, default=100)
    parser.add_argument("--start-after-reference", action="store_true")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--no-pauses", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if not args.yes:
        raise SystemExit("batch measurement refused; rerun with --yes")

    batch_dir = run_batch(
        load_hardware_config(args.config),
        devices_csv=args.devices,
        reference_path=args.reference,
        out_root=args.out,
        span_um=args.span_um,
        step_um=args.step_um,
        align_settle_ms=args.align_settle_ms,
        spectrum_settle_ms=args.spectrum_settle_ms,
        start_after_reference=args.start_after_reference,
        resume=args.resume,
        pause=(lambda _message: None) if args.no_pauses else pause,
    )
    print(batch_dir)


def pause(message: str) -> None:
    input(message + "...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

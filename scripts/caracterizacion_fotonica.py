from __future__ import annotations

import argparse
from pathlib import Path

from labauto.devices import load_devices
from labauto.runner import run, self_test


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal PIC characterization runner.")
    parser.add_argument("--devices", type=Path, default=Path("examples/devices.example.csv"))
    parser.add_argument("--out", type=Path, default=Path("workspace/results"))
    parser.add_argument("--simulate", action="store_true", help="run with fake motion and fake power data")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-devices", type=Path, help="validate a devices CSV and exit")
    args = parser.parse_args()

    if args.validate_devices:
        devices = load_devices(args.validate_devices)
        print(f"devices CSV ok: {len(devices)} devices")
        return

    if args.self_test:
        self_test()
        print("self-test ok")
        return

    if not args.simulate:
        parser.error("real hardware drivers are not configured yet; use --simulate for the current prototype")

    run_dir = run(args.devices, args.out)
    print(run_dir)


if __name__ == "__main__":
    main()

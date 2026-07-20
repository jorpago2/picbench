from __future__ import annotations

import argparse
from pathlib import Path

from labauto.config_builder import build_real_config_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Create hardware.real.json from hardware.discovered.json.")
    parser.add_argument("--example", type=Path, default=Path("examples/hardware.example.json"))
    parser.add_argument("--discovered", type=Path, default=Path("config/hardware.discovered.json"))
    parser.add_argument("--out", type=Path, default=Path("config/hardware.real.json"))
    args = parser.parse_args()

    config = build_real_config_files(args.example, args.discovered, args.out)
    print(args.out)
    for note in config.get("_build_notes", []):
        print(f"TODO: {note}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(str(exc))

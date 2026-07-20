from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from labauto.bsc_config import automatic_stage_configs, axis_channel, bsc_from_config, stage_position_mm
from labauto.devices import Device
from labauto.thorlabs_bsc203 import BSC203


STEP_MM = (0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5)


def keyboard_align_reference(
    config: dict[str, Any],
    device: Device,
    *,
    enable_z: bool = False,
    state_dir: Path | None = None,
) -> Path | None:
    import msvcrt

    state_dir = state_dir or Path(config.get("startup", {}).get("state_dir", "workspace/state"))
    step_index = 1

    with bsc_from_config(config) as controller:
        print_help(enable_z)
        print_position(config, controller)
        while True:
            key = read_key(msvcrt)
            if key in ("q", "esc"):
                print("cancelled")
                return None
            if key == "enter":
                return save_reference(config, device, controller, state_dir)
            if key in ("1", "2", "3", "4"):
                step_index = int(key) - 1
                print(f"step = {STEP_MM[step_index] * 1000:g} um")
                continue
            move = key_move(key, STEP_MM[step_index], enable_z)
            if move is None:
                continue
            axis, delta_mm = move
            controller.move_by_mm(axis_channel(config, axis), delta_mm)
            print_position(config, controller)


def read_key(msvcrt) -> str:
    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return {
            "K": "left",
            "M": "right",
            "H": "up",
            "P": "down",
            "I": "page_up",
            "Q": "page_down",
        }.get(code, "")
    if key == "\r":
        return "enter"
    if key == "\x1b":
        return "esc"
    return key.lower()


def key_move(key: str, step_mm: float, enable_z: bool) -> tuple[str, float] | None:
    moves = {
        "left": ("x", -step_mm),
        "right": ("x", step_mm),
        "up": ("y", step_mm),
        "down": ("y", -step_mm),
        "a": ("x", -step_mm),
        "d": ("x", step_mm),
        "w": ("y", step_mm),
        "s": ("y", -step_mm),
    }
    if enable_z:
        moves.update(
            {
                "page_up": ("z", step_mm),
                "page_down": ("z", -step_mm),
                "r": ("z", step_mm),
                "f": ("z", -step_mm),
            }
        )
    return moves.get(key)


def save_reference(
    config: dict[str, Any],
    device: Device,
    controller: BSC203 | dict[str, BSC203],
    state_dir: Path,
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(controller, dict):
        stage_configs = automatic_stage_configs(config)
        stage_positions = {
            stage: stage_position_mm({"motion": stage_configs[stage]}, stage_controller)
            for stage, stage_controller in controller.items()
        }
        primary_position = stage_positions["a"]
    else:
        stage_positions = None
        primary_position = stage_position_mm(config, controller)
    data = {
        "timestamp": datetime.now().isoformat(),
        "device_id": device.device_id,
        "stage_position_mm": primary_position,
        "device_layout_um": {
            "input_gc_x": device.input_gc_x,
            "input_gc_y": device.input_gc_y,
            "output_gc_x": device.output_gc_x,
            "output_gc_y": device.output_gc_y,
        },
        "polarization": device.polarization,
        "wavelength_nm": {
            "start": device.lambda_start_nm,
            "stop": device.lambda_stop_nm,
            "step": device.lambda_step_nm,
        },
    }
    if stage_positions is not None:
        data["stage_positions_mm"] = stage_positions
    path = state_dir / f"reference_{device.device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    shutil.copyfile(path, state_dir / "reference_latest.json")
    print(f"saved {path}")
    return path


def print_help(enable_z: bool) -> None:
    print("Keyboard alignment")
    print("arrows or WASD: move x/y")
    if enable_z:
        print("PageUp/PageDown or R/F: move z")
    else:
        print("z disabled; rerun with --enable-z to allow z jogging")
    print("1/2/3/4/5/6/7/8: step 0.5/1/5/10/50/100/250/500 um")
    print("Enter: save reference")
    print("q or Esc: cancel")


def print_position(config: dict[str, Any], controller: BSC203) -> None:
    pos = stage_position_mm(config, controller)
    print("position mm: " + ", ".join(f"{axis}={value:.6f}" for axis, value in pos.items()))

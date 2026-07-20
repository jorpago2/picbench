from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from labauto.bsc_config import bsc_from_config, stage_position_mm
from labauto.devices import Device, wavelengths_nm
from labauto.thorlabs_bsc203 import BSC203
from labauto.visa_devices import VisaLaser, VisaPowerMeter


SPECTRUM_COLUMNS = [
    "device_id",
    "wavelength_nm",
    "power_w",
    "x_mm",
    "y_mm",
    "z_mm",
    "output_x_mm",
    "output_y_mm",
    "output_z_mm",
    "timestamp",
]


def measure_spectrum(
    config: dict[str, Any],
    device: Device,
    *,
    out_root: Path,
    settle_ms: int = 100,
) -> Path:
    validate_device_wavelengths(config, device)
    run_dir = out_root / f"spectrum_{device.device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    csv_path = run_dir / "spectrum.csv"
    rows = []

    with (
        bsc_from_config(config) as controller,
        VisaLaser(config) as laser,
        VisaPowerMeter(config) as meter,
    ):
        try:
            prepare_measurement_laser(laser, meter, device.lambda_start_nm)
            rows = measure_spectrum_with_sessions(
                config,
                device,
                controller=controller,
                laser=laser,
                meter=meter,
                csv_path=csv_path,
                settle_ms=settle_ms,
            )
        finally:
            laser.output(False)

    write_spectrum_metadata(run_dir, device, settle_ms, len(rows))
    return run_dir


def measure_spectrum_with_sessions(
    config: dict[str, Any],
    device: Device,
    *,
    controller: BSC203,
    laser: VisaLaser,
    meter: VisaPowerMeter,
    csv_path: Path,
    settle_ms: int = 100,
    output_controller: BSC203 | None = None,
    output_config: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SPECTRUM_COLUMNS)
        writer.writeheader()
        for wavelength in wavelengths_nm(device.lambda_start_nm, device.lambda_stop_nm, device.lambda_step_nm):
            meter.set_wavelength_nm(wavelength)
            laser.set_wavelength_nm(wavelength)
            time.sleep(settle_ms / 1000.0)
            position = stage_position_mm(config, controller)
            output_position = stage_position_mm(output_config, output_controller) if output_controller and output_config else None
            row = {
                "device_id": device.device_id,
                "wavelength_nm": f"{wavelength:.6f}",
                "power_w": f"{meter.read_power_w():.12g}",
                "x_mm": f"{position['x']:.6f}",
                "y_mm": f"{position['y']:.6f}",
                "z_mm": f"{position['z']:.6f}",
                "output_x_mm": f"{output_position['x']:.6f}" if output_position else "",
                "output_y_mm": f"{output_position['y']:.6f}" if output_position else "",
                "output_z_mm": f"{output_position['z']:.6f}" if output_position else "",
                "timestamp": datetime.now().isoformat(),
            }
            writer.writerow(row)
            rows.append(row)
    return rows


def prepare_measurement_laser(laser: VisaLaser, meter: VisaPowerMeter, wavelength_nm: float) -> None:
    meter.set_wavelength_nm(wavelength_nm)
    laser.set_wavelength_nm(wavelength_nm)
    laser.output(True)


def validate_device_wavelengths(config: dict[str, Any], device: Device) -> None:
    laser = config.get("laser", {})
    low = float(laser.get("wavelength_min_nm", 1490.0))
    high = float(laser.get("wavelength_max_nm", 1610.0))
    if device.lambda_start_nm < low or device.lambda_stop_nm > high:
        raise ValueError(
            f"{device.device_id} wavelength range [{device.lambda_start_nm:g}, {device.lambda_stop_nm:g}] nm "
            f"outside configured laser range [{low:g}, {high:g}] nm"
        )


def write_spectrum_metadata(run_dir: Path, device: Device, settle_ms: int, points: int) -> None:
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "device_id": device.device_id,
                "polarization": device.polarization,
                "lambda_start_nm": device.lambda_start_nm,
                "lambda_stop_nm": device.lambda_stop_nm,
                "lambda_step_nm": device.lambda_step_nm,
                "settle_ms": settle_ms,
                "points": points,
                "connections": "persistent laser, power meter, and BSC203 during sweep",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

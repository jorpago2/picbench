from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


REQUIRED_COLUMNS = (
    "device_id",
    "input_gc_x",
    "input_gc_y",
    "output_gc_x",
    "output_gc_y",
    "polarization",
    "lambda_start_nm",
    "lambda_stop_nm",
    "lambda_step_nm",
)


@dataclass(frozen=True)
class Device:
    device_id: str
    input_gc_x: float
    input_gc_y: float
    output_gc_x: float
    output_gc_y: float
    polarization: str
    lambda_start_nm: float
    lambda_stop_nm: float
    lambda_step_nm: float


def load_devices(path: Path) -> list[Device]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing columns: {', '.join(sorted(missing))}")
        devices = [parse_device(row, i + 2) for i, row in enumerate(reader)]
    if not devices:
        raise ValueError(f"{path} has no devices")
    seen = set()
    for device in devices:
        if not device.device_id:
            raise ValueError(f"{path} has an empty device_id")
        if device.device_id in seen:
            raise ValueError(f"{path} has duplicated device_id: {device.device_id}")
        seen.add(device.device_id)
    return devices


def find_device(path: Path, device_id: str) -> Device:
    for device in load_devices(path):
        if device.device_id == device_id:
            return device
    raise ValueError(f"{path} has no device_id {device_id!r}")


def parse_device(row: dict[str, str], line: int) -> Device:
    try:
        device = Device(
            device_id=row["device_id"].strip(),
            input_gc_x=float(row["input_gc_x"]),
            input_gc_y=float(row["input_gc_y"]),
            output_gc_x=float(row["output_gc_x"]),
            output_gc_y=float(row["output_gc_y"]),
            polarization=row["polarization"].strip(),
            lambda_start_nm=float(row["lambda_start_nm"]),
            lambda_stop_nm=float(row["lambda_stop_nm"]),
            lambda_step_nm=float(row["lambda_step_nm"]),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid device CSV row at line {line}: {exc}") from exc
    if device.lambda_stop_nm < device.lambda_start_nm:
        raise ValueError(f"invalid device CSV row at line {line}: lambda_stop_nm < lambda_start_nm")
    if device.lambda_step_nm <= 0:
        raise ValueError(f"invalid device CSV row at line {line}: lambda_step_nm must be > 0")
    return device


def wavelengths_nm(start_nm: float, stop_nm: float, step_nm: float):
    start = Decimal(str(start_nm))
    stop = Decimal(str(stop_nm))
    step = Decimal(str(step_nm))
    if step <= 0 or stop < start:
        raise ValueError("wavelength range must have stop >= start and step > 0")
    value = start
    while value <= stop:
        yield float(value)
        value += step

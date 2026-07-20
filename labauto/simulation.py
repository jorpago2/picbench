from __future__ import annotations

import math

from labauto.devices import Device


class SimulatedPowerMeter:
    def read_dbm(self, device: Device, x_um: float, y_um: float, wavelength_nm: float) -> float:
        target_x, target_y = simulated_best_xy(device)
        dx = x_um - target_x
        dy = y_um - target_y
        spatial_loss_db = 4.0 * ((dx / 2.0) ** 2 + (dy / 2.0) ** 2)
        spectral_db = 1.3 * math.sin((wavelength_nm - device.lambda_start_nm) / 4.0)
        return round(-18.0 + spectral_db - spatial_loss_db, 4)


def simulated_best_xy(device: Device) -> tuple[float, float]:
    seed = sum(ord(ch) for ch in device.device_id)
    return device.input_gc_x + (seed % 7 - 3) * 0.35, device.input_gc_y + (seed % 5 - 2) * 0.35

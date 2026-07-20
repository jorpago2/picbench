from __future__ import annotations

import math
from datetime import datetime, timezone


class SafeMotion:
    def __init__(
        self,
        *,
        z_travel_um: float = 200.0,
        z_chip_um: float = 0.0,
        z_margin_um: float = 30.0,
        max_lateral_near_chip_um: float = 40.0,
    ) -> None:
        if z_travel_um < z_chip_um + z_margin_um:
            raise ValueError("z_travel_um must be above the safe z limit")
        self.x_um = 0.0
        self.y_um = 0.0
        self.z_um = z_travel_um
        self.z_travel_um = z_travel_um
        self.z_chip_um = z_chip_um
        self.z_margin_um = z_margin_um
        self.max_lateral_near_chip_um = max_lateral_near_chip_um
        self.events: list[dict[str, str | float]] = []

    def z_min_um(self) -> float:
        return self.z_chip_um + self.z_margin_um

    def move_z(self, z_um: float) -> None:
        if z_um < self.z_min_um():
            raise RuntimeError(f"blocked unsafe z move: {z_um:.3f} < {self.z_min_um():.3f} um")
        self.z_um = z_um
        self._log("move_z")

    def move_xy(self, x_um: float, y_um: float) -> None:
        distance = math.hypot(x_um - self.x_um, y_um - self.y_um)
        if distance > self.max_lateral_near_chip_um and self.z_um < self.z_travel_um:
            self.move_z(self.z_travel_um)
        self.x_um = x_um
        self.y_um = y_um
        self._log("move_xy")

    def _log(self, action: str) -> None:
        self.events.append(
            {
                "timestamp": now_utc(),
                "action": action,
                "x_um": self.x_um,
                "y_um": self.y_um,
                "z_um": self.z_um,
            }
        )


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

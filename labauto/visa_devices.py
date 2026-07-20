from __future__ import annotations

import math
import re
import time
from typing import Any

from labauto.config import configured, require_config


class VisaInstrument:
    def __init__(self, resource: str, *, timeout_ms: int = 5000) -> None:
        self.resource = resource
        self.timeout_ms = timeout_ms
        self._inst = None

    def __enter__(self):
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("pyvisa is not installed") from exc
        rm = pyvisa.ResourceManager()
        self._inst = rm.open_resource(self.resource)
        self._inst.timeout = self.timeout_ms
        self._inst.read_termination = "\n"
        self._inst.write_termination = "\n"
        return self

    def __exit__(self, *_exc) -> None:
        if self._inst is not None:
            self._inst.close()
            self._inst = None

    def query(self, command: str) -> str:
        return self._inst.query(command).strip()

    def write(self, command: str) -> None:
        self._inst.write(command)

    def identify(self) -> str:
        return self.query("*IDN?")


class VisaDevice:
    config_section = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.resource = require_config(config, self.config_section, "visa_resource")
        self.commands = config.get(self.config_section, {}).get("commands", {})
        self._inst: VisaInstrument | None = None

    def __enter__(self):
        self._inst = VisaInstrument(self.resource)
        self._inst.__enter__()
        return self

    def __exit__(self, *_exc) -> None:
        if self._inst is not None:
            self._inst.__exit__(*_exc)
            self._inst = None

    def identify(self) -> str:
        return self.query(self.commands.get("identify", "*IDN?"))

    def query(self, command: str) -> str:
        if self._inst is not None:
            return self._inst.query(command)
        with VisaInstrument(self.resource) as inst:
            return inst.query(command)

    def write(self, command: str) -> None:
        if self._inst is not None:
            self._inst.write(command)
            return
        with VisaInstrument(self.resource) as inst:
            inst.write(command)


class VisaLaser(VisaDevice):
    config_section = "laser"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        settings = config.get(self.config_section, {})
        self.slot = int(settings.get("slot", 1))
        self.power_mw = float(settings.get("power_mw", 1.0))
        self.wavelength_min_nm = float(settings.get("wavelength_min_nm", 1490.0))
        self.wavelength_max_nm = float(settings.get("wavelength_max_nm", 1610.0))
        self.tuning_rate_nm_s = float(settings.get("tuning_rate_nm_s", 10.0))
        self.tuning_margin_ms = int(settings.get("tuning_margin_ms", 50))
        if self.slot not in range(1, 9):
            raise ValueError("laser.slot must be between 1 and 8")
        if not math.isfinite(self.power_mw) or self.power_mw <= 0:
            raise ValueError("laser.power_mw must be a positive number")
        if self.wavelength_min_nm >= self.wavelength_max_nm or self.tuning_rate_nm_s <= 0 or self.tuning_margin_ms < 0:
            raise ValueError("invalid laser wavelength range or tuning timing")

    def set_wavelength_nm(self, wavelength_nm: float) -> None:
        wavelength_nm = float(wavelength_nm)
        if not self.wavelength_min_nm <= wavelength_nm <= self.wavelength_max_nm:
            raise ValueError(
                f"laser wavelength {wavelength_nm:g} nm outside "
                f"[{self.wavelength_min_nm:g}, {self.wavelength_max_nm:g}] nm"
            )
        previous = response_number(self.query(command_template(self.commands, "get_wavelength_nm", slot=self.slot)))
        command = command_template(self.commands, "set_wavelength_nm", slot=self.slot, wavelength_nm=wavelength_nm)
        self.write(command)
        actual = response_number(self.query(command_template(self.commands, "get_wavelength_nm", slot=self.slot)))
        if not math.isclose(actual, wavelength_nm, abs_tol=0.02):
            raise RuntimeError(f"laser rejected wavelength {wavelength_nm:g} nm; reports {actual:g} nm")
        time.sleep(abs(wavelength_nm - previous) / self.tuning_rate_nm_s + self.tuning_margin_ms / 1000.0)

    def set_power_mw(self, power_mw: float | None = None) -> None:
        value = self.power_mw if power_mw is None else float(power_mw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("laser power must be a positive number in mW")
        self.write(command_template(self.commands, "set_power_unit_mw", slot=self.slot))
        limit = response_number(self.query(command_template(self.commands, "get_power_limit_mw", slot=self.slot)))
        if value > limit:
            raise ValueError(f"laser power {value:g} mW exceeds CH{self.slot} limit {limit:g} mW")
        self.write(command_template(self.commands, "set_power_mw", slot=self.slot, power_mw=value))
        actual = response_number(self.query(command_template(self.commands, "get_power_mw", slot=self.slot)))
        if not math.isclose(actual, value, rel_tol=0.02, abs_tol=0.01):
            raise RuntimeError(f"laser rejected power {value:g} mW; reports {actual:g} mW")
        self.power_mw = value

    def output(self, enabled: bool) -> None:
        if enabled:
            self.set_power_mw()
        command = command_template(self.commands, "output_on" if enabled else "output_off", slot=self.slot)
        self.write(command)
        response = self.query(command_template(self.commands, "get_output", slot=self.slot)).upper()
        actual = not any(marker in response for marker in ("DISABLE", "OFF", "FALSE", "=0"))
        if actual != enabled:
            raise RuntimeError(f"laser CH{self.slot} output state verification failed: {response}")


class VisaPowerMeter(VisaDevice):
    config_section = "power_meter"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.channel = int(config.get(self.config_section, {}).get("channel", 1))
        if self.channel not in (1, 2):
            raise ValueError("power_meter.channel must be 1 or 2")

    def set_wavelength_nm(self, wavelength_nm: float) -> None:
        command = command_template(self.commands, "set_wavelength_nm", channel=self.channel, wavelength_nm=wavelength_nm)
        self.write(command)
        actual = response_number(self.query(command_template(self.commands, "get_wavelength_nm", channel=self.channel)))
        if not math.isclose(actual, float(wavelength_nm), abs_tol=0.01):
            raise RuntimeError(f"power meter CH{self.channel} wavelength verification failed: {actual:g} nm")

    def read_power_w(self) -> float:
        command = command_template(self.commands, "read_power_w", channel=self.channel)
        value = float(self.query(command))
        if not math.isfinite(value):
            raise RuntimeError(f"power meter CH{self.channel} returned a non-finite reading")
        return value


def response_number(response: str) -> float:
    values = re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?", response.replace(",", "."))
    if not values:
        raise RuntimeError(f"instrument returned no numeric value: {response!r}")
    return float(values[-1])


def command_template(commands: dict[str, str], name: str, **values: Any) -> str:
    command = commands.get(name)
    if not configured(command):
        raise ValueError(f"missing VISA command template: {name}")
    return command.format(**values)

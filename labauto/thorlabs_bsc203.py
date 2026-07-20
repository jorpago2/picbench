from __future__ import annotations

import sys
import time
import math
from pathlib import Path


def decimal_text(value: float) -> str:
    if not math.isfinite(float(value)):
        raise ValueError("motion value must be finite")
    return f"{float(value):.12f}".rstrip("0").rstrip(".") or "0"


def dotnet_float(value) -> float:
    return float(str(value).replace(",", "."))


def safe_limits(limits: tuple[float, float] | None, channel_number: int) -> tuple[float, float]:
    if limits is None:
        raise RuntimeError(f"motion limits missing for BSC203 channel {channel_number}")
    lower, upper = limits
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise RuntimeError(f"invalid motion limits for BSC203 channel {channel_number}")
    return lower, upper


class BSC203:
    def __init__(
        self,
        serial_number: str,
        *,
        kinesis_dir: Path | None = None,
        stage_name: str | dict[int, str] | None = None,
        limits_mm: dict[int, tuple[float, float]] | None = None,
        motion_profile: tuple[float, float] | None = None,
        poll_ms: int = 250,
    ) -> None:
        self.serial_number = str(serial_number)
        self.kinesis_dir = kinesis_dir
        self.stage_name = stage_name
        self.limits_mm = limits_mm or {}
        self.motion_profile = motion_profile
        self.poll_ms = poll_ms
        self.device = None
        self.channels = {}
        self.Decimal = None
        self.culture = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def connect(self) -> None:
        try:
            DeviceManagerCLI, BenchtopStepperMotor, Decimal, culture = load_kinesis(self.kinesis_dir)
            self.Decimal = Decimal
            self.culture = culture
            DeviceManagerCLI.BuildDeviceList()
            self.device = BenchtopStepperMotor.CreateBenchtopStepperMotor(self.serial_number)
            self.device.Connect(self.serial_number)
            time.sleep(0.25)
        except Exception:
            self.close()
            raise

    def channel(self, channel_number: int):
        if self.device is None:
            raise RuntimeError("BSC203 is not connected")
        if channel_number in self.channels:
            return self.channels[channel_number]

        channel = self.device.GetChannel(int(channel_number))
        if not channel.IsSettingsInitialized():
            channel.WaitForSettingsInitialized(10000)
        if not channel.IsSettingsInitialized():
            raise RuntimeError(f"BSC203 channel {channel_number} settings did not initialize")

        try:
            channel.StartPolling(self.poll_ms)
            time.sleep(0.25)
            channel.EnableDevice()
            time.sleep(0.25)

            stage_name = self.stage_name.get(channel_number) if isinstance(self.stage_name, dict) else self.stage_name
            if stage_name:
                config = channel.LoadMotorConfiguration(channel.DeviceID)
                settings = channel.MotorDeviceSettings
                channel.GetSettings(settings)
                config.DeviceSettingsName = stage_name
                config.UpdateCurrentConfiguration()
                channel.SetSettings(settings, True, False)

            if self.motion_profile:
                velocity, acceleration = self.motion_profile
                params = channel.GetVelocityParams()
                params.MaxVelocity = self.decimal(velocity)
                params.Acceleration = self.decimal(acceleration)
                channel.SetVelocityParams(params)
        except Exception:
            try:
                channel.StopPolling()
            except Exception:
                pass
            raise

        self.channels[channel_number] = channel
        return channel

    def identify(self, channel_number: int = 1) -> str:
        return str(self.channel(channel_number).GetDeviceInfo().Description)

    def settings_name(self, channel_number: int) -> str:
        channel = self.channel(channel_number)
        return str(channel.LoadMotorConfiguration(channel.DeviceID).DeviceSettingsName)

    def position_mm(self, channel_number: int) -> float:
        return dotnet_float(self.channel(channel_number).DevicePosition)

    def decimal(self, value: float):
        if self.Decimal is None or self.culture is None:
            raise RuntimeError("BSC203 is not connected")
        return self.Decimal.Parse(decimal_text(value), self.culture)

    def home(self, channel_number: int, *, timeout_ms: int = 60000) -> dict[str, bool]:
        self.channel(channel_number).Home(timeout_ms)
        status = self.status(channel_number)
        if status.get("homed") is False:
            raise RuntimeError(f"BSC203 channel {channel_number} did not report homed after homing")
        return status

    def move_to_mm(self, channel_number: int, position_mm: float, *, timeout_ms: int = 60000) -> dict[str, bool]:
        if not math.isfinite(position_mm):
            raise ValueError("target position must be finite")
        lower, upper = safe_limits(self.limits_mm.get(channel_number), channel_number)
        if not lower <= position_mm <= upper:
            raise RuntimeError(f"blocked move on channel {channel_number}: {position_mm:.6f} mm outside [{lower:.6f}, {upper:.6f}] mm")
        before = self.status(channel_number)
        if before.get("enabled") is False or before.get("homed") is False:
            raise RuntimeError(f"BSC203 channel {channel_number} is not enabled and homed")
        if any(before.get(key) for key in ("cw_hardware_limit", "ccw_hardware_limit", "cw_software_limit", "ccw_software_limit")):
            raise RuntimeError(f"BSC203 channel {channel_number} has an active limit switch")
        self.channel(channel_number).MoveTo(self.decimal(position_mm), timeout_ms)
        status = self.status(channel_number)
        if any(status.get(key) for key in ("cw_hardware_limit", "ccw_hardware_limit", "cw_software_limit", "ccw_software_limit")):
            raise RuntimeError(f"BSC203 channel {channel_number} reached a limit switch")
        return status

    def move_by_mm(self, channel_number: int, delta_mm: float, *, timeout_ms: int = 60000) -> None:
        self.move_to_mm(channel_number, self.position_mm(channel_number) + delta_mm, timeout_ms=timeout_ms)

    def stop(self, channel_number: int, *, timeout_ms: int = 60000) -> None:
        channel = self.channel(channel_number)
        if hasattr(channel, "StopImmediate"):
            channel.StopImmediate()
        else:
            channel.Stop(timeout_ms)

    def emergency_stop(self, channels: list[int]) -> dict[int, str]:
        result = {}
        for channel_number in channels:
            try:
                self.stop(channel_number)
                result[channel_number] = "stopped"
            except Exception as exc:
                result[channel_number] = str(exc)
        return result

    def status(self, channel_number: int) -> dict[str, bool]:
        channel = self.channel(channel_number)
        status = getattr(channel, "Status", None)
        result = {
            name[2:].lower(): bool(getattr(status, name))
            for name in ("IsEnabled", "IsHomed", "IsHoming", "IsMoving")
            if status is not None and hasattr(status, name)
        }
        raw = getattr(channel, "StatusBits", None)
        if raw is None:
            raw = getattr(channel, "GetStatusBits", None)
        raw = raw() if callable(raw) else raw
        if raw is not None:
            bits = int(raw)
            result.update({
                "cw_hardware_limit": bool(bits & 0x00000001),
                "ccw_hardware_limit": bool(bits & 0x00000002),
                "cw_software_limit": bool(bits & 0x00000004),
                "ccw_software_limit": bool(bits & 0x00000008),
                "homing": bool(bits & 0x00000200),
                "homed": bool(bits & 0x00000400),
                "enabled": bool(bits & 0x80000000),
            })
        return result

    def close(self) -> None:
        for channel in self.channels.values():
            try:
                channel.StopPolling()
            except Exception:
                pass
        self.channels.clear()
        if self.device is not None:
            self.device.Disconnect()
            self.device = None


def load_kinesis(kinesis_dir: Path | None):
    try:
        import clr
    except ImportError as exc:
        raise RuntimeError("pythonnet is not installed") from exc

    root = find_kinesis_dir(kinesis_dir)
    sys.path.append(str(root))
    for dll in (
        "Thorlabs.MotionControl.DeviceManagerCLI.dll",
        "Thorlabs.MotionControl.GenericMotorCLI.dll",
        "ThorLabs.MotionControl.Benchtop.StepperMotorCLI.dll",
        "Thorlabs.MotionControl.Benchtop.StepperMotorCLI.dll",
    ):
        path = root / dll
        if path.exists():
            clr.AddReference(str(path))

    from System import Decimal
    from System.Globalization import CultureInfo
    from Thorlabs.MotionControl.Benchtop.StepperMotorCLI import BenchtopStepperMotor
    from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI

    return DeviceManagerCLI, BenchtopStepperMotor, Decimal, CultureInfo.InvariantCulture


def find_kinesis_dir(kinesis_dir: Path | None) -> Path:
    roots = [kinesis_dir] if kinesis_dir else [
        Path(r"C:\Program Files\Thorlabs\Kinesis"),
        Path(r"C:\Program Files (x86)\Thorlabs\Kinesis"),
    ]
    for root in roots:
        if root and (root / "Thorlabs.MotionControl.DeviceManagerCLI.dll").exists():
            return root
    raise RuntimeError("Kinesis DLL folder not found")

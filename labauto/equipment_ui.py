from __future__ import annotations

import json
import math
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from labauto.bsc_config import bsc_from_config
from labauto.config import parse_number
from labauto.visa_devices import VisaLaser, VisaPowerMeter


class DeviceWorker:
    """One serial worker per instrument; different instruments run concurrently."""

    def __init__(self, owner: tk.Misc) -> None:
        self.owner = owner
        self.jobs: queue.Queue[tuple] = queue.Queue()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def submit(self, action, done, failed) -> None:
        self.jobs.put((action, done, failed))

    def _loop(self) -> None:
        while True:
            action, done, failed = self.jobs.get()
            if action is None:
                return
            try:
                result = action()
            except Exception as exc:
                if failed is not None:
                    self.owner.after(0, failed, exc)
            else:
                if done is not None:
                    self.owner.after(0, done, result)

    def close(self, action=None) -> None:
        if action is not None:
            self.jobs.put((action, None, None))
        self.jobs.put((None, None, None))
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=5)


class EquipmentDashboard(tk.Frame):
    def __init__(self, parent, app) -> None:
        super().__init__(parent, bg="#f5f7fb")
        self.app = app
        self.lower = tk.Frame(self, bg="#f5f7fb")
        self.panels = [
            StagePanel(self, app, "a"),
            StagePanel(self, app, "b"),
            LaserPanel(self.lower, app),
            PowerMeterPanel(self.lower, app),
            CameraPanel(self.lower, app),
        ]
        self.motion_label = _section_label(self, "Motion systems")
        self.optical_label = _section_label(self, "Optical instrumentation")
        self._compact = None
        self.bind("<Configure>", self._reflow)
        self.after_idle(lambda: self._layout(compact_equipment_layout(self.winfo_width())))

    def _reflow(self, event) -> None:
        self._layout(compact_equipment_layout(event.width))

    def _layout(self, compact: bool) -> None:
        if self._compact is compact:
            return
        self._compact = compact
        for widget in (self.motion_label, self.optical_label, self.lower, *self.panels):
            widget.grid_forget()
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0 if compact else 1)
        self.motion_label.grid(row=0, column=0, columnspan=1 if compact else 2, sticky="w", pady=(0, 7))
        if compact:
            self.panels[0].grid(row=1, column=0, sticky="ew", pady=(0, 10))
            self.panels[1].grid(row=2, column=0, sticky="ew", pady=(0, 16))
            self.optical_label.grid(row=3, column=0, sticky="w", pady=(0, 7))
            self.lower.grid(row=4, column=0, sticky="ew")
            for column in range(3):
                self.lower.columnconfigure(column, weight=1 if column == 0 else 0)
            for row, panel in enumerate(self.panels[2:]):
                panel.grid(row=row, column=0, sticky="ew", pady=(0, 10) if row < 2 else 0)
        else:
            self.panels[0].grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 16))
            self.panels[1].grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(0, 16))
            self.optical_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 7))
            self.lower.grid(row=3, column=0, columnspan=2, sticky="ew")
            for column in range(3):
                self.lower.columnconfigure(column, weight=1)
            for column, panel in enumerate(self.panels[2:]):
                panel.grid(
                    row=0,
                    column=column,
                    sticky="nsew",
                    padx=(0, 7) if column == 0 else ((7, 0) if column == 2 else 7),
                )

    def connected_devices(self) -> list[str]:
        return [panel.device_name for panel in self.panels if getattr(panel, "connected", False)]

    def close(self) -> None:
        for panel in self.panels:
            panel.close()

    def emergency_stop(self) -> None:
        for panel in self.panels:
            stop = getattr(panel, "emergency_stop_now", None)
            if stop is not None:
                stop()


def compact_equipment_layout(width: int) -> bool:
    return width < 1450


class AsyncPanel(tk.Frame):
    device_name = "device"

    def __init__(self, parent, app) -> None:
        super().__init__(
            parent, bg="#ffffff", padx=16, pady=14, bd=0,
            highlightbackground="#d9e2ec", highlightthickness=1,
        )
        self.app = app
        self.worker = DeviceWorker(self)
        self.busy = False
        self.connected = False
        self.status = tk.StringVar(value="Disconnected")

    def accent(self, color: str) -> None:
        tk.Frame(self, bg=color, height=4).place(x=0, y=0, relwidth=1)

    def run(self, label: str, action, done=None, on_error=None) -> None:
        if self.busy:
            self.status.set(f"Busy: {label}")
            return
        self.busy = True
        self.status.set(f"{label}...")

        def complete(result) -> None:
            self.busy = False
            self.status.set(done(result) if done else f"{label} complete")

        def failed(exc: Exception) -> None:
            self.busy = False
            self.status.set(f"Error: {exc}")
            self.app._activity(f"{self.device_name}: {exc}\n")
            if on_error is not None:
                on_error(exc)

        self.worker.submit(action, complete, failed)

    def close(self) -> None:
        self.worker.close()


class StagePanel(AsyncPanel):
    def __init__(self, parent, app, stage: str) -> None:
        self.stage = stage
        self.device_name = f"Stage {stage.upper()}"
        self.controller = None
        self.stop_requested = threading.Event()
        super().__init__(parent, app)
        self.serial = app.stage_a_serial if stage == "a" else app.stage_b_serial
        self.axis_channels = {"x": 1, "y": 2, "z": 3} if stage == "a" else {"x": 2, "y": 1, "z": 3}
        self.step_um = tk.StringVar(value="10")
        self.allow_z = tk.BooleanVar(value=False)
        self.position = tk.StringVar(value="Connect to read positions")
        self.last_positions = None
        self.accent("#2f80ed" if stage == "a" else "#7b61ff")
        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        tk.Label(self, text=self.device_name, bg="#ffffff", fg="#182230", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(self, textvariable=self.status, bg="#f2f4f7", fg="#475467", padx=8, pady=4).grid(row=0, column=2, sticky="e")
        self.app.parameter_label(self, "Controller").grid(row=1, column=0, sticky="w", pady=(14, 0))
        combo = ttk.Combobox(self, textvariable=self.serial, state="readonly")
        combo.grid(row=1, column=1, sticky="ew", padx=10, pady=(14, 0))
        if self.stage == "a":
            self.app.stage_a_combo = combo
            self.app.stage_combo = combo
        else:
            self.app.stage_b_combo = combo
        controls = tk.Frame(self, bg="#ffffff")
        controls.grid(row=1, column=2, sticky="e", pady=(14, 0))
        _button(controls, "Connect", self.connect, primary=True).pack(side="left", padx=(0, 6))
        _button(controls, "Disconnect", self.disconnect).pack(side="left")

        tk.Label(self, textvariable=self.position, bg="#ffffff", fg="#475467", justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(14, 8)
        )
        body = tk.Frame(self, bg="#ffffff")
        body.grid(row=3, column=0, columnspan=3, sticky="ew")
        body.columnconfigure(2, weight=1)
        left = tk.Frame(body, bg="#ffffff")
        left.grid(row=0, column=0, sticky="nw", padx=(0, 8))
        motion = tk.Frame(left, bg="#ffffff")
        motion.grid(row=0, column=0, sticky="w")
        self.app.parameter_label(motion, "Step", help_key="Stage step").grid(row=0, column=0, padx=(0, 6))
        ttk.Combobox(motion, textvariable=self.step_um, state="readonly", width=6,
                     values=("0.5", "1", "5", "10", "50", "100", "250", "500")).grid(row=0, column=1)
        allow_z = tk.Checkbutton(motion, text="Z  \u24d8", variable=self.allow_z, bg="#ffffff", activebackground="#ffffff")
        self.app.helped(allow_z, "Allow Z").grid(row=0, column=2, padx=8)
        _button(motion, "Home", self.home).grid(row=0, column=3, padx=(0, 6))
        _button(motion, "Read", self.refresh_position).grid(row=0, column=4)

        jog = tk.Frame(left, bg="#ffffff")
        jog.grid(row=1, column=0, sticky="w", pady=(8, 0))
        for column, axis in enumerate(("x", "y", "z")):
            tk.Label(jog, text=axis.upper(), bg="#ffffff", fg="#667085").grid(row=0, column=column * 3, padx=(0 if column == 0 else 10, 3))
            _button(jog, "-", lambda ax=axis: self.move(ax, -1)).grid(row=0, column=column * 3 + 1, padx=2)
            _button(jog, "+", lambda ax=axis: self.move(ax, 1)).grid(row=0, column=column * 3 + 2, padx=2)
        _button(jog, "Stop", self.stop, danger=True).grid(row=0, column=9, padx=(12, 0))

        tk.Frame(body, bg="#eaecf0", width=1).grid(row=0, column=1, sticky="ns", padx=(0, 8))
        limits = tk.Frame(body, bg="#ffffff")
        limits.grid(row=0, column=2, sticky="nsew")
        for column in range(7):
            limits.columnconfigure(column, weight=1 if column in (2, 4) else 0)
        tk.Label(limits, text="Safe limits (mm)", bg="#ffffff", fg="#182230", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=7, sticky="w")
        for row, axis in enumerate(("x", "y", "z"), 1):
            tk.Label(limits, text=axis.upper(), bg="#ffffff", fg="#667085").grid(row=row, column=0, sticky="w", pady=(7, 0))
            self.app.parameter_label(limits, "min", help_key="Safe minimum").grid(row=row, column=1, pady=(7, 0))
            _entry(limits, self.app.manual_limits[self.stage][axis][0]).grid(row=row, column=2, sticky="ew", padx=(5, 12), pady=(7, 0))
            self.app.parameter_label(limits, "max", help_key="Safe maximum").grid(row=row, column=3, pady=(7, 0))
            _entry(limits, self.app.manual_limits[self.stage][axis][1]).grid(row=row, column=4, sticky="ew", padx=(5, 12), pady=(7, 0))
        _button(limits, "Save", self.app.save_manual_stage_safety).grid(row=1, column=6, rowspan=3, sticky="ns")

    def _config(self) -> dict:
        config = json.loads(Path(self.app.resolve_config_path()).read_text(encoding="utf-8"))
        entry = dict(config.get("manual_stages", {}).get(self.stage, {}))
        entry["serial_number"] = self.serial.get()
        entry["axis_channels"] = {"x": 1, "y": 2, "z": 3} if self.stage == "a" else {"x": 2, "y": 1, "z": 3}
        entry["limits_mm"] = {
            axis: [parse_number(value.get()) for value in self.app.manual_limits[self.stage][axis]]
            for axis in ("x", "y", "z")
        }
        motion = config.get("motion", {})
        for key in ("kinesis_dir", "axis_stage_settings", "max_velocity_mm_s", "acceleration_mm_s2"):
            if key in motion:
                entry.setdefault(key, motion[key])
        return entry

    def connect(self) -> None:
        config = self._config()

        def action():
            if self.controller is not None:
                self.controller.close()
            self.controller = bsc_from_config({"motion": config})
            self.controller.connect()
            self.axis_channels = config["axis_channels"]
            return self._positions()

        def done(positions):
            self.connected = True
            self.stop_requested.clear()
            self._show_positions(positions)
            return "Connected"

        self.run("Connecting", action, done)

    def disconnect(self) -> None:
        def action():
            if self.controller is not None:
                self.controller.close()
                self.controller = None

        def done(_result):
            self.connected = False
            self.position.set("Disconnected")
            return "Disconnected"

        self.run("Disconnecting", action, done)

    def home(self) -> None:
        if not self.connected or self.controller is None:
            self.status.set("Connect first")
            return
        if not messagebox.askyesno("Home", f"Home {self.device_name} in Z, X, Y order using Kinesis settings?"):
            return
        channels = dict(self._config()["axis_channels"])

        def action():
            for axis in ("z", "x", "y"):
                self.controller.home(int(channels[axis]))
            return self._positions()

        self.run("Homing", action, self._positions_done)

    def move(self, axis: str, sign: int) -> None:
        if axis == "z" and not self.allow_z.get():
            self.status.set("Enable Allow Z first")
            return
        if not self.connected or self.controller is None:
            self.status.set("Connect first")
            return
        channel = int(self._config()["axis_channels"][axis])
        delta = sign * parse_number(self.step_um.get()) / 1000.0

        def action():
            self.controller.move_by_mm(channel, delta)
            return self._positions()

        self.run(f"Moving {axis.upper()}", action, self._positions_done)

    def refresh_position(self) -> None:
        if self.connected and self.controller is not None:
            self.run("Reading position", self._positions, self._positions_done)

    def stop(self) -> None:
        if self.connected and self.controller is not None:
            self.emergency_stop_now()

    def emergency_stop_now(self) -> None:
        if self.controller is None:
            return
        self.stop_requested.set()
        channels = list(self.axis_channels.values())
        threading.Thread(target=self.controller.emergency_stop, args=(channels,), daemon=True).start()
        self.status.set("Emergency stop sent")

    def _positions(self) -> dict[str, tuple[float, dict]]:
        channels = self.axis_channels
        return {
            axis: (self.controller.position_mm(int(channel)), self.controller.status(int(channel)))
            for axis, channel in channels.items()
        }

    def _show_positions(self, positions) -> None:
        self.last_positions = positions
        self.position.set("   ".join(
            f"{axis.upper()} {position:.6f} mm" + ("  homed" if status.get("homed") else "  not homed")
            for axis, (position, status) in positions.items()
        ))

    def _positions_done(self, positions) -> str:
        self._show_positions(positions)
        return "Ready"

    def close(self) -> None:
        self.worker.close(lambda: self.controller.close() if self.controller is not None else None)


class VisaPanel(AsyncPanel):
    device_class = None

    def __init__(self, parent, app, resource_var: tk.StringVar) -> None:
        self.device = None
        self.resource = resource_var
        super().__init__(parent, app)

    def connect(self) -> None:
        path = self.app.resolve_config_path()
        resource = self.resource.get()
        laser_settings = None
        if self.device_class is VisaLaser:
            try:
                laser_settings = {
                    "slot": int(self.app.laser_slot.get()),
                    "power_mw": parse_number(self.app.laser_power_mw.get()),
                }
            except ValueError as exc:
                self.status.set(f"Invalid setting: {exc}")
                return

        def action():
            if self.device is not None:
                self.device.__exit__(None, None, None)
            config = json.loads(Path(path).read_text(encoding="utf-8"))
            config[self.device_class.config_section]["visa_resource"] = resource
            if laser_settings is not None:
                config["laser"].update(laser_settings)
            self.device = self.device_class(config)
            self.device.__enter__()
            return self.device.identify()

        def done(identity):
            self.connected = True
            return f"Connected: {identity}"

        self.run("Connecting", action, done)

    def disconnect(self) -> None:
        def action():
            if self.device is not None:
                self.device.__exit__(None, None, None)
                self.device = None

        def done(_result):
            self.connected = False
            return "Disconnected"

        self.run("Disconnecting", action, done)

    def close(self) -> None:
        self.worker.close(lambda: self.device.__exit__(None, None, None) if self.device is not None else None)


class LaserPanel(VisaPanel):
    device_name = "Laser"
    device_class = VisaLaser

    def __init__(self, parent, app) -> None:
        self.wavelength = tk.StringVar(value="1550")
        super().__init__(parent, app, app.laser_resource)
        self.accent("#f79009")
        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        _header(self, "Yenista / EXFO T100", self.status)
        self.app.parameter_label(self, "VISA resource").grid(row=1, column=0, sticky="w", pady=(14, 0))
        self.app.laser_combo = ttk.Combobox(self, textvariable=self.resource, state="readonly")
        self.app.laser_combo.grid(row=1, column=1, sticky="ew", padx=10, pady=(14, 0))
        row = tk.Frame(self, bg="#ffffff")
        row.grid(row=1, column=2, pady=(14, 0))
        _button(row, "Connect", self.connect, primary=True).pack(side="left", padx=(0, 6))
        _button(row, "Disconnect", self.disconnect).pack(side="left")
        settings = tk.Frame(self, bg="#ffffff")
        settings.grid(row=2, column=0, columnspan=3, sticky="w", pady=(16, 0))
        self.app.parameter_label(settings, "Wavelength (nm)").pack(side="left")
        _entry(settings, self.wavelength, width=8).pack(side="left", padx=(8, 14))
        self.app.parameter_label(settings, "Slot").pack(side="left")
        ttk.Combobox(settings, textvariable=self.app.laser_slot, values=tuple(range(1, 9)), state="readonly", width=3).pack(
            side="left", padx=(8, 14)
        )
        self.app.parameter_label(settings, "Power (mW)").pack(side="left")
        _entry(settings, self.app.laser_power_mw, width=7).pack(side="left", padx=(8, 0))
        controls = tk.Frame(self, bg="#ffffff")
        controls.grid(row=3, column=0, columnspan=3, sticky="w", pady=(14, 0))
        _button(controls, "Set wavelength", self.set_wavelength).pack(side="left", padx=(0, 6))
        _button(controls, "Set power", self.set_power).pack(side="left", padx=(0, 6))
        _button(controls, "Output on", lambda: self.set_output(True), primary=True).pack(side="left", padx=(0, 6))
        _button(controls, "Output off", lambda: self.set_output(False), danger=True).pack(side="left")

    def _apply_slot(self) -> int | None:
        if self.device is None:
            self.status.set("Connect first")
            return None
        try:
            slot = int(self.app.laser_slot.get())
            if slot not in range(1, 9):
                raise ValueError("slot must be 1-8")
        except ValueError as exc:
            self.status.set(f"Invalid setting: {exc}")
            return None
        self.device.slot = slot
        return slot

    def _apply_settings(self) -> tuple[int, float] | None:
        slot = self._apply_slot()
        if slot is None:
            return None
        try:
            power_mw = parse_number(self.app.laser_power_mw.get())
            if power_mw <= 0:
                raise ValueError("power must be positive")
        except ValueError as exc:
            self.status.set(f"Invalid setting: {exc}")
            return None
        self.device.power_mw = power_mw
        return slot, power_mw

    def set_wavelength(self) -> None:
        if self._apply_slot() is None:
            return
        value = parse_number(self.wavelength.get())
        self.run("Setting wavelength", lambda: self.device.set_wavelength_nm(value), lambda _r: f"Wavelength: {value:g} nm")

    def set_power(self) -> None:
        settings = self._apply_settings()
        if settings is None:
            return
        slot, power_mw = settings
        self.run("Setting power", lambda: self.device.set_power_mw(power_mw), lambda _r: f"CH{slot}: {power_mw:g} mW")

    def set_output(self, enabled: bool) -> None:
        if not enabled:
            if self._apply_slot() is not None:
                self.run("Changing output", lambda: self.device.output(False), lambda _r: "Output OFF")
            return
        settings = self._apply_settings()
        if settings is None:
            return
        slot, power_mw = settings
        if enabled and not messagebox.askyesno("Laser output", f"Enable CH{slot} at {power_mw:g} mW?"):
            return
        self.run("Changing output", lambda: self.device.output(enabled), lambda _r: "Output ON" if enabled else "Output OFF")

    def disconnect(self) -> None:
        def action():
            if self.device is not None:
                try:
                    self.device.output(False)
                finally:
                    self.device.__exit__(None, None, None)
                    self.device = None

        def done(_result):
            self.connected = False
            return "Disconnected; output OFF"

        self.run("Disconnecting", action, done)

    def emergency_stop_now(self) -> None:
        if self.device is not None:
            threading.Thread(target=self.device.output, args=(False,), daemon=True).start()
            self.status.set("Emergency output OFF sent")

    def close(self) -> None:
        def action():
            if self.device is not None:
                try:
                    self.device.output(False)
                finally:
                    self.device.__exit__(None, None, None)

        self.worker.close(action)


class PowerMeterPanel(VisaPanel):
    device_name = "Power meter"
    device_class = VisaPowerMeter

    def __init__(self, parent, app) -> None:
        self.wavelength = tk.StringVar(value="1550")
        self.reading = tk.StringVar(value="-")
        self.monitoring = False
        super().__init__(parent, app, app.power_meter_resource)
        self.accent("#12b76a")
        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        _header(self, "Thorlabs PM320E", self.status)
        self.app.parameter_label(self, "VISA resource").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.app.pm_combo = ttk.Combobox(self, textvariable=self.resource, state="readonly")
        self.app.pm_combo.grid(row=1, column=1, sticky="ew", padx=10, pady=(8, 0))
        row = tk.Frame(self, bg="#ffffff")
        row.grid(row=1, column=2, pady=(8, 0))
        _button(row, "Connect", self.connect, primary=True).pack(side="left", padx=(0, 6))
        _button(row, "Disconnect", self.disconnect).pack(side="left")
        details = tk.Frame(self, bg="#ffffff")
        details.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.app.parameter_label(details, "Wavelength (nm)").pack(side="left")
        _entry(details, self.wavelength).pack(side="left", padx=(8, 6))
        _button(details, "Set", self.set_wavelength).pack(side="left")
        self.app.parameter_label(details, "Channel").pack(side="left", padx=(14, 6))
        ttk.Combobox(details, textvariable=self.app.power_meter_channel, values=(1, 2), state="readonly", width=3).pack(side="left")
        tk.Label(details, textvariable=self.reading, bg="#ffffff", fg="#182230", font=("Segoe UI", 16, "bold")).pack(side="right")
        controls = tk.Frame(self, bg="#ffffff")
        controls.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        _button(controls, "Read", self.read_power, primary=True).pack(side="left", padx=(0, 6))
        self.monitor_button = _button(controls, "Monitor", self.toggle_monitor)
        self.monitor_button.pack(side="left")

    def set_wavelength(self) -> None:
        if self.device is None:
            self.status.set("Connect first")
            return
        self.device.channel = int(self.app.power_meter_channel.get())
        value = parse_number(self.wavelength.get())
        self.run("Setting wavelength", lambda: self.device.set_wavelength_nm(value), lambda _r: f"Wavelength: {value:g} nm")

    def read_power(self) -> None:
        if self.device is None:
            self.status.set("Connect first")
            return
        self.device.channel = int(self.app.power_meter_channel.get())

        def done(watts: float) -> str:
            dbm = 10 * math.log10(watts) + 30 if watts > 0 else float("-inf")
            self.reading.set(f"{watts:.6g} W   {dbm:.2f} dBm")
            return "Monitoring" if self.monitoring else "Ready"

        self.run("Reading", self.device.read_power_w, done)

    def toggle_monitor(self) -> None:
        self.monitoring = not self.monitoring
        self.monitor_button.configure(text="Stop monitor" if self.monitoring else "Monitor")
        if self.monitoring:
            self._monitor_tick()

    def disconnect(self) -> None:
        self.monitoring = False
        self.monitor_button.configure(text="Monitor")
        super().disconnect()

    def _monitor_tick(self) -> None:
        if not self.monitoring:
            return
        if not self.busy:
            self.read_power()
        self.after(300, self._monitor_tick)


class CameraPanel(tk.Frame):
    device_name = "Camera"
    connected = False

    def __init__(self, parent, app) -> None:
        super().__init__(
            parent, bg="#ffffff", padx=16, pady=14, bd=0,
            highlightbackground="#d9e2ec", highlightthickness=1,
        )
        self.app = app
        tk.Frame(self, bg="#0e7c7b", height=4).place(x=0, y=0, relwidth=1)
        self.columnconfigure(1, weight=1)
        status = tk.StringVar(value="")
        _header(self, "USB camera", status)
        self.app.parameter_label(self, "Camera").grid(row=1, column=0, sticky="w", pady=(14, 0))
        app.camera_combo = ttk.Combobox(self, textvariable=app.camera_index, state="readonly")
        app.camera_combo.grid(row=1, column=1, sticky="ew", padx=10, pady=(14, 0))
        controls = tk.Frame(self, bg="#ffffff")
        controls.grid(row=2, column=0, columnspan=3, sticky="w", pady=(16, 0))
        _button(controls, "Live", app.toggle_camera, primary=True).pack(side="left", padx=(0, 6))
        _button(controls, "Capture", app.capture_camera).pack(side="left", padx=(0, 6))
        _button(controls, "Save", app.save_hardware_selection).pack(side="left")

    def close(self) -> None:
        pass


def _header(parent, title: str, status: tk.StringVar) -> None:
    tk.Label(parent, text=title, bg="#ffffff", fg="#182230", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
    if status.get():
        tk.Label(parent, textvariable=status, bg="#f2f4f7", fg="#475467", padx=8, pady=4).grid(
            row=0, column=1, columnspan=2, sticky="e"
        )


def _section_label(parent, text: str) -> tk.Label:
    return tk.Label(
        parent, text=text.upper(), bg="#f5f7fb", fg="#667085",
        font=("Segoe UI", 9, "bold"),
    )


def _button(parent, text: str, command, *, primary: bool = False, danger: bool = False) -> tk.Button:
    return tk.Button(
        parent, text=text, command=command, bd=0, relief="flat", padx=8, pady=6,
        bg="#0e7c7b" if primary else "#eef2f6", fg="#ffffff" if primary else ("#d92d20" if danger else "#182230"),
        activebackground="#075e5d" if primary else "#e4e9f0", cursor="hand2", font=("Segoe UI", 9),
    )


def _entry(parent, var: tk.StringVar, width: int = 12) -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width, bd=0, highlightthickness=1, highlightbackground="#d9e2ec", bg="#fbfcfe", fg="#182230", font=("Segoe UI", 9))

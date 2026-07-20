from __future__ import annotations

import csv
import ctypes
import json
import math
import queue
import subprocess
import sys
import threading
import time
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from labauto.config import parse_number


SOURCE_ROOT = Path(__file__).resolve().parent.parent
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SOURCE_ROOT
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))

BG = "#f5f7fb"
CARD = "#ffffff"
TEXT = "#182230"
MUTED = "#667085"
LINE = "#d9e2ec"
ACCENT = "#0e7c7b"
ACCENT_DARK = "#075e5d"
BLUE = "#2f80ed"
PURPLE = "#7b61ff"
AMBER = "#f79009"
GREEN = "#12b76a"
RED = "#d92d20"

FIELD_HELP = {
    "Config": "Hardware JSON used by the current session. It stores resources, motion limits, safety settings and calibration paths.",
    "CSV": "Device table used for the chip map and measurements. Each row identifies one device and its coordinates and wavelength range.",
    "Reference": "Saved aligned position used as the coordinate origin for device-to-device movement.",
    "Device id": "Active device from the CSV. Selecting a structure in Operation area updates this value.",
    "Stage controller": "BSC203 serial used by legacy single-stage commands. Choose a controller discovered on this PC.",
    "Manual Stage A": "BSC203 assigned to the input fiber. Logical X/Y/Z use channels 1/2/3.",
    "Manual Stage B": "BSC203 assigned to the output fiber. Logical X/Y/Z use channels 2/1/3.",
    "Laser": "VISA resource for the Yenista/EXFO OSICS mainframe connected through GPIB-to-USB.",
    "Power meter": "VISA resource for the Thorlabs PM320E.",
    "Camera": "OpenCV camera index discovered on this PC. Recalibrate vision after changing camera or resolution.",
    "Power meter channel": "PM320E optical input channel. Allowed values: 1 or 2.",
    "XY span um": "Total local search span used by power-based XY alignment. Must be positive and remain inside stage limits.",
    "XY step um": "Sampling step used by power-based XY alignment. Smaller steps improve resolution but increase measurement time.",
    "Z step um": "Vertical increment used by automatic Z approach. Start conservatively and reduce only after collision checks.",
    "Z stop mm": "Hard software endpoint for automatic approach. It must stop before physical fiber-chip contact.",
    "Target power W": "Power threshold that completes automatic Z approach when reached.",
    "Approach wavelength nm": "Laser wavelength used by the standalone automatic Z-approach tool.",
    "Fiber angle deg": "Fiber angle from the chip normal used to estimate lateral compensation during Z movement. Typical grating setup: 10 degrees.",
    "Angle sign": "Direction of lateral compensation during Z movement. Use +1 or -1 according to the physical fiber orientation.",
    "Home timeout ms": "Maximum time allowed for one Kinesis homing operation before PICBench reports failure.",
    "X safe min mm": "Lowest allowed logical X coordinate for automatic motion.",
    "X safe max mm": "Highest allowed logical X coordinate for automatic motion.",
    "Y safe min mm": "Lowest allowed logical Y coordinate for automatic motion.",
    "Y safe max mm": "Highest allowed logical Y coordinate for automatic motion.",
    "Z safe min mm": "Lowest allowed logical Z coordinate. Set it above the collision position.",
    "Z safe max mm": "Highest allowed logical Z coordinate within verified mechanical travel.",
    "Max velocity mm/s": "Optional BSC203 velocity limit applied to all configured axes. Establish it experimentally away from the chip.",
    "Acceleration mm/s2": "Optional BSC203 acceleration applied to all configured axes. Establish it experimentally away from the chip.",
    "Z travel mm": "Collision-free Z position used before every automatic XY move. It must lie inside both stages' safe Z ranges.",
    "Laser tuning rate nm/s": "Expected wavelength tuning speed used to calculate settling time.",
    "Laser minimum nm": "Lowest wavelength PICBench may command to the Yenista T100.",
    "Laser maximum nm": "Highest wavelength PICBench may command to the Yenista T100.",
    "Laser tuning margin ms": "Extra wait added after the wavelength-dependent tuning time before reading power.",
    "Fiber XY tolerance um": "Maximum visual residual accepted for each fiber after closed-loop positioning. Must be positive.",
    "Fiber XY corrections": "Maximum closed-loop correction rounds after the initial move. Allowed range: 0 to 10.",
    "Max XY correction um": "Largest residual PICBench may correct automatically. It must be at least the XY tolerance.",
    "Z approach enabled": "Allows automatic Z descent during supported workflows. Leave off until power and vision safety thresholds are calibrated.",
    "Laser off on startup": "Requests laser output OFF before stage homing during initialization.",
    "Batch after reference": "Starts batch measurement after the reference row instead of measuring the reference again.",
    "Controller": "BSC203 serial assigned to this physical stage panel.",
    "Stage step": "Relative manual jog distance in micrometres. The resulting position must remain inside the configured safe range.",
    "Allow Z": "Unlocks manual Z jog for this panel. Keep disabled during ordinary XY alignment.",
    "Safe minimum": "Lowest software coordinate accepted for this logical axis.",
    "Safe maximum": "Highest software coordinate accepted for this logical axis.",
    "Stage safe range": "Minimum and maximum software coordinates accepted for this stage axis, in millimetres.",
    "VISA resource": "Exact VISA address of this instrument. Select the resource returned by Scan PC.",
    "Wavelength (nm)": "Optical wavelength applied to the connected laser or power-meter correction setting.",
    "Slot": "OSICS mainframe slot containing the Yenista T100 module. Allowed range: 1 to 8.",
    "Power (mW)": "Requested Yenista output power in milliwatts. PICBench verifies it before enabling output.",
    "Channel": "PM320E input channel used for wavelength correction and power readings. Allowed values: 1 or 2.",
    "Stage": "Physical stage selected for the current manual or calibration operation.",
    "Step um": "Relative manual movement per key press or button click, in micrometres.",
    "XY step (um)": "Known X and Y displacement used to calculate the camera pixel-to-stage transform.",
}

HELP_PAGE_FIELDS = {
    "Setup": (
        "Config", "CSV", "Reference", "Device id", "XY span um", "XY step um", "Z step um", "Z stop mm",
        "Target power W", "Approach wavelength nm", "Fiber angle deg", "Angle sign", "Home timeout ms",
        "X safe min mm", "X safe max mm", "Y safe min mm", "Y safe max mm", "Z safe min mm", "Z safe max mm",
        "Max velocity mm/s", "Acceleration mm/s2", "Z travel mm", "Laser tuning rate nm/s", "Laser minimum nm",
        "Laser maximum nm", "Laser tuning margin ms", "Fiber XY tolerance um", "Fiber XY corrections",
        "Max XY correction um", "Z approach enabled", "Laser off on startup", "Batch after reference",
    ),
    "Devices": (
        "Controller", "Stage step", "Allow Z", "Safe minimum", "Safe maximum", "VISA resource",
        "Wavelength (nm)", "Slot", "Power (mW)", "Channel", "Camera",
    ),
}
HELP_TEXT = """
# PICBench Help

## Purpose
PICBench coordinates a silicon photonics measurement setup: motorized stages, a tunable laser, a power meter, and a camera. It uses a devices CSV as the measurement map and keeps references, captures and measurement results under the workspace folder.

## Typical Workflow
1. Open Setup.
2. Select the config JSON, devices CSV, and reference file.
3. Click Scan PC to discover connected stage, VISA instruments, and cameras.
4. Pick the stage, laser, power meter, and camera from the detected devices.
5. Click Save selection and adjust Program settings if needed.
6. Click Initialize before moving hardware.
7. Register a reference device.
8. Use Live to monitor the setup and start measurements.
9. Use Results to inspect spectra and output files.

## Setup Tab
Configure session files, automatic measurement parameters, and maintenance tools before connecting equipment.

## Devices Tab
Discover, assign, connect, and control the stages, laser, power meter, and camera. Each panel runs independently. Disconnect equipment panels before starting an automatic measurement, which owns the hardware for the duration of the run.

The Yenista panel selects mainframe slot 1-8 and output power in mW. Output on applies and verifies the selected power before enabling that slot. The PM320E panel selects channel 1 or 2.

## Live Tab
### Status bar
Shows the current app state, active device, last measured power, latest known stage position, and number of result files.

### Operation area
Shows the devices from the CSV and the latest known fiber/stage position. The selected device_id is highlighted when it matches a row in the CSV. Devices with a saved spectrum are framed in green; click one to open its result in the Results tab.

### Camera
Shows the live camera feed or the latest capture.
- Live/Pause: start or stop live view.
- +/-: zoom the displayed image.
- Reset: return to normal scale.
- Map gratings: annotate input/output grating pairs in devices CSV order.
- Capture: save a frame.

### Grating map
Click the input grating and then the output grating for each device. The assistant advances through the devices CSV automatically. Freeze the image for precise annotation, use the mouse wheel to zoom, and middle-drag to pan. Save map supports partial work and reloads compatible existing annotations. Saved pairs appear over the Live camera; green marks input and magenta marks output.

Position fibers uses the selected device, the saved grating map, and both vision-calibration profiles. It previews the detected tips, XY deltas, absolute targets, and travel height. After confirmation it retracts both Z axes before either XY move. Both stage panels must be connected and idle.

After the first move, PICBench detects both fibers again and applies bounded XY corrections until both residuals are within the configured tolerance. It stops on low vision confidence, excessive or diverging corrections, active limits, stale camera frames, or the configured correction count. Z remains at the safe travel height throughout this process.

### Run control
- Position fibers: preview and move Stage A to the input grating and Stage B to the output grating at the configured safe travel height.
- Start batch: measure the batch from the current reference.
- Resume batch: continue an existing batch folder.
- Current spectrum: measure only the selected device_id.
- Continue: send Enter to a paused command.
- Stop: stop both stages, disable the laser, and lock motion until acknowledged.

## Results Tab
### Recent files
Lists files created under workspace/state, workspace/results and workspace/captures. Select one or more spectrum CSV files to overlay curves. If nothing is selected, the latest spectrum is shown by default.

### Spectra plot
- Mouse wheel: zoom.
- Middle-button drag: pan.
- +/- buttons: zoom.
- Reset: return to the default view.
- Cursor marker: show the nearest measured point.

### Activity
Shows operation messages. Enable technical details only when you need the exact command line and process output for debugging.

## Setup Details
### Session
- Config: usually config/hardware.real.json.
- CSV: the devices table.
- Reference: usually workspace/state/reference_latest.json.
- Device id: the active device row to move to or measure.

### Hardware selection
Scan PC fills the device menus. Save selection writes both stages, laser, PM320E channel, and camera into the config JSON.

### System preparation
Contains the ordered setup actions: Initialize, Register reference and Vision calibration. Maintenance contains configuration validation, diagnostics, self-test, manual motion and safety-lock acknowledgement.

### Manual motion
Manual motion works without a CSV, laser, meter, or camera. Select the discovered controller for each physical stage and enter separate safe ranges before connecting.
- Stage A: X channel 1, Y channel 2, Z channel 3.
- Stage B: X channel 2, Y channel 1, Z channel 3.
- Arrow keys or WASD jog logical X/Y. Enable Allow Z before using R/F for logical Z.

### Program settings
- XY span/step: search area for alignment.
- Z approach settings: automatic descent parameters and optical/vision stop conditions.
- Fiber angle/sign: lateral compensation while moving Z.
- Z travel: collision-safe height used before moving either stage in X/Y.
- Fiber XY tolerance/corrections: closed-loop acceptance tolerance, maximum correction rounds, and largest allowed corrective step.
- Laser range/rate: limits CSV wavelengths and provides enough tuning time before acquisition.
- Home timeout: maximum homing wait.
- Laser off on startup: safety option during initialization.
- Batch after reference: skip the reference row when measuring a batch.

### Vision calibration
Open Vision calibration from System preparation after connecting a stage and starting the camera. For each fiber, draw a region of interest, mark two points on the chip surface, and record the fiber tip at Far, Near, and Minimum safe heights. After Far, XY mapping moves X and Y by a small configurable step, measures the image displacement and returns to the starting position. Move Z only from the independent Devices controls.

Saving creates workspace/state/vision_calibration.json and camera templates. It does not enable automatic Z motion. Repeat the calibration whenever the camera, resolution, focus, illumination, stage assignment, or optical geometry changes.

## Files
- config/hardware.real.json: hardware resources and motion settings.
- workspace/devices.csv: devices to measure and their grating positions.
- workspace/state/reference_latest.json: last saved reference alignment.
- workspace/results: spectra, batch reports, and metadata.
- workspace/captures: camera snapshots.

## Safety Notes
Any action that can move axes or tune/enable the laser asks for confirmation. Initialize before real measurements. Check z_travel_mm and Z approach settings on the lab PC before automatic movement.

Stop sends an emergency stop to both controllers and disables the laser. Inspect the setup before acknowledging the safety lock.

## Reference Jog Dialog
Select Stage A for the input fiber or Stage B for the output fiber. Use arrow keys or WASD to jog X/Y and enable Allow Z before R/F. Enter saves both stage positions.
"""

HELP_PAGES = {
    "Overview": ("PICBench overview", HELP_TEXT),
    "Setup": (
        "Setup",
        """# Setup

## Purpose
Prepare the session, select its files, define motion and optical limits, and run calibration tools before connecting real equipment.

## Recommended workflow
1. Select `config/hardware.real.json`, the devices CSV and the reference file.
2. Run Scan PC and assign the discovered resources.
3. Save the hardware selection.
4. Review safe travel, motion limits and laser limits on the laboratory PC.
5. Initialize the setup, register a reference and complete vision calibration before automatic positioning.

## Session files
- Config: hardware resources, limits, calibration paths and automatic-control settings.
- CSV: one row per device, including its chip coordinates and spectral range.
- Reference: known aligned stage positions used by coordinate-based batch movement.
- Device id: the active structure selected in the operation area or entered manually.

## Program settings
- XY span / step: coarse and fine search dimensions used by power optimization.
- Z approach: enables automatic vertical approach only after its visual and power thresholds have been calibrated.
- Fiber angle / sign: compensates the lateral displacement caused by the 10-degree fiber angle during Z movement.
- Safe limits: software envelope applied before motion commands. Keep margin from the mechanical endpoints.
- Z travel: collision-free height used before any automatic XY movement.
- Fiber XY tolerance: residual visual alignment error accepted after positioning.
- Fiber XY corrections: maximum number of closed-loop camera corrections.
- Max XY correction: largest residual that PICBench may correct automatically.
- Laser range / rate / margin: validates wavelength commands and determines settling time.

## System preparation
- Initialize: identifies configured hardware, disables laser output and homes the stages.
- Register reference: manually align one known device and store both stage positions.
- Vision calibration: records fiber templates, safe Z states and the pixel-to-stage XY transform.
- Maintenance: configuration validation, diagnostics, hardware-config generation, self-test, manual motion and safety-lock acknowledgement.

## Safety
Saving settings does not validate the physical setup. Confirm directions, limits and `z_travel_mm` without a valuable sample before enabling automatic movement. Vision calibration must be repeated after changing camera position, focus, magnification, illumination, fiber geometry or stage assignment.
""",
    ),
    "Devices": (
        "Devices",
        """# Devices

## Purpose
Discover, assign, connect and control each instrument independently. Every panel has its own worker, so one device operation does not block the others.

## Scan and connection
1. Click Scan PC. Discovery is read-only and does not move stages or enable the laser.
2. Select the correct resource or serial number in each panel.
3. Click Save selection to write the choices to the active config.
4. Connect only the devices needed for the current task.

## Stage A and Stage B
- Stage A controls the input fiber: logical X=channel 1, Y=channel 2, Z=channel 3.
- Stage B controls the output fiber: logical X=channel 2, Y=channel 1, Z=channel 3.
- Home uses the active Kinesis profile. Read shows physical positions and homing state.
- Step selects jog distance in micrometres. Z jog remains locked until Z is explicitly enabled.
- Safe limits are checked before motion. Stop sends an immediate stop request to that controller.

## Yenista T100
- Resource selects the GPIB-to-USB VISA address.
- Slot selects the OSICS mainframe channel.
- Output power is entered in mW; the default is 1 mW.
- Output On applies and verifies the requested power before enabling emission.

## PM320E and camera
- Select PM320E VISA resource and input channel before connecting.
- The camera menu lists OpenCV-compatible cameras found by the PC.
- A smaller camera resolution or ROI improves live frame rate.

## Troubleshooting
- Found but not connected: verify vendor drivers, resource assignment and that another program is not using the device.
- Stage will not move: check enabled/homed state, active limits, Kinesis profile and configured logical channel mapping.
- Camera missing: close other camera applications, rescan and test another OpenCV index.
- Disconnect equipment panels before a batch command that needs exclusive ownership of the same hardware.
""",
    ),
    "Live": (
        "Live operation",
        """# Live operation

## Purpose
Monitor the chip and camera, select structures, position both fibers and control measurement execution.

## Status bar
- Status: current application or safety state.
- Device: selected device id.
- Last power: latest measured optical power.
- Stage: latest known position summary.
- Results: number of discovered output files.

## Operation area
The device CSV is drawn as a chip map. The selected device is highlighted. A green frame marks a device with a saved spectrum; click it to open that result.

## Camera
- Live / Pause: start or pause acquisition.
- Plus / minus: change display zoom without altering camera resolution.
- Reset: restore fit-to-view.
- Capture: save the current frame.
- Mouse wheel zooms and middle-button drag pans where supported.

## Map gratings
1. Select a clear live frame and open Map gratings.
2. Click input then output for each device.
3. Save partial progress when needed.
4. Repeat mapping after camera geometry or resolution changes.

## Position fibers
1. Connect and home both stages, start the live camera and select a mapped device.
2. PICBench detects both tips and previews absolute XY targets and vision confidence.
3. After confirmation, both Z axes move to `z_travel_mm` before either XY axis moves.
4. Fresh camera frames verify the result and apply bounded XY corrections.
5. The flow stops on low confidence, stale frames, limits, excessive residual, divergence or exhausted corrections.

Z remains at the safe travel height. Position fibers does not lower the fibers onto the chip.

## Run control
- Start batch: execute the configured device sequence.
- Resume batch: continue an interrupted batch folder.
- Current spectrum: measure only the selected device.
- Continue: release a command waiting for operator confirmation.
- Stop: stop stages, disable laser output and engage the safety lock.
""",
    ),
    "Results": (
        "Results",
        """# Results

## Purpose
Browse saved measurements, compare spectra and inspect operation messages without opening CSV files manually.

## Recent files
- Select one or more spectrum CSV files to overlay their curves.
- With no selection, the latest saved spectrum is displayed automatically.
- The list scrolls independently from the rest of the window.

## Spectra plot
- Mouse wheel: smooth zoom around the cursor.
- Middle-button drag: pan the current view.
- Plus / minus: controlled zoom steps.
- Reset: restore the full measured range.
- Hover a curve: show a marker and the nearest measured wavelength and power.
- Axis labels use wavelength in nm and power in dBm without scientific notation.

## Comparing measurements
Use Ctrl-click to select multiple files. The legend identifies each curve. Reset the plot after changing a large selection if the previous zoom no longer contains the new data.

## Activity
Activity contains operator-facing progress and failure messages. Technical details expose command lines and raw process output only for diagnostics.

## Output files
- Spectrum folders contain one spectrum CSV and metadata for each measurement.
- Batch folders also contain batch state and motion history so interrupted work can be resumed.
- State stores references, calibration profiles, grating maps and latest-operation reports.
""",
    ),
}


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class LabAutoUI(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()
        super().__init__()
        self._set_tk_scaling()
        self.title("PICBench")
        self.geometry("1420x860")
        self.minsize(1180, 760)
        self.configure(bg=BG)
        try:
            self.iconbitmap(str(RESOURCE_ROOT / "assets" / "picbench.ico"))
        except tk.TclError:
            pass
        self.after(0, self.maximize_window)

        self.log_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._tooltip_job: str | None = None
        self._tooltip_window: tk.Toplevel | None = None
        self.process: subprocess.Popen | None = None
        self.result_paths: dict[str, Path] = {}
        self.camera_cap = None
        self.camera_stop = threading.Event()
        self.camera_frames: queue.Queue[object] = queue.Queue(maxsize=1)
        self.camera_last_frame = None
        self.camera_frame_id = 0
        self.camera_frame_timestamp = 0.0
        self.camera_photo = None
        self.camera_live = False
        self.camera_zoom = 1.0
        self.spectrum_view = None
        self.spectrum_drag = None
        self.spectrum_plot = None
        self.spectrum_data_bounds = None
        self.spectrum_redraw_job = None
        self.spectrum_dirty = True
        self.current_spectra: list[tuple[str, list[tuple[float, float]]]] = []
        self.operation_hits: list[tuple[float, float, float, float, str]] = []
        self.measured_results: dict[str, tuple[str, Path]] = {}
        self.result_signature = ()
        self.pane_sizes: dict[str, tuple[int, int]] = {}
        self.hardware_report: dict[str, list[dict]] = {}
        self.motion_locked = False
        self.manual_dialog = None
        self.vision_dialog = None
        self.grating_dialog = None
        self.grating_map = None
        self.grating_move_pending = False
        self.manual_stage_connected = False

        self.config_path = tk.StringVar(value="config/hardware.real.json")
        self.devices_path = tk.StringVar(value="workspace/devices.csv")
        self.reference_path = tk.StringVar(value="workspace/state/reference_latest.json")
        self.device_id = tk.StringVar()
        self.span_um = tk.StringVar(value="10")
        self.step_um = tk.StringVar(value="2")
        self.z_enabled = tk.BooleanVar(value=False)
        self.z_step_um = tk.StringVar()
        self.z_stop_mm = tk.StringVar()
        self.z_target_power_w = tk.StringVar()
        self.z_wavelength_nm = tk.StringVar()
        self.fiber_angle_deg = tk.StringVar()
        self.angle_sign = tk.StringVar()
        self.home_timeout_ms = tk.StringVar()
        self.x_min_mm = tk.StringVar(value="0")
        self.x_max_mm = tk.StringVar(value="4")
        self.y_min_mm = tk.StringVar(value="0")
        self.y_max_mm = tk.StringVar(value="4")
        self.z_min_mm = tk.StringVar(value="0")
        self.z_max_mm = tk.StringVar(value="4")
        self.z_travel_mm = tk.StringVar()
        self.grating_tolerance_um = tk.StringVar(value="5")
        self.grating_max_corrections = tk.StringVar(value="3")
        self.grating_max_correction_um = tk.StringVar(value="50")
        self.max_velocity_mm_s = tk.StringVar()
        self.acceleration_mm_s2 = tk.StringVar()
        self.laser_off_on_start = tk.BooleanVar(value=True)
        self.stage_serial = tk.StringVar()
        self.stage_a_serial = tk.StringVar()
        self.stage_b_serial = tk.StringVar()
        self.laser_resource = tk.StringVar()
        self.laser_slot = tk.StringVar(value="1")
        self.laser_power_mw = tk.StringVar(value="1")
        self.laser_min_nm = tk.StringVar(value="1490")
        self.laser_max_nm = tk.StringVar(value="1610")
        self.laser_tuning_rate = tk.StringVar(value="10")
        self.laser_tuning_margin_ms = tk.StringVar(value="50")
        self.power_meter_resource = tk.StringVar()
        self.power_meter_channel = tk.StringVar(value="1")
        self.camera_index = tk.StringVar()
        self.manual_limits = {
            stage: {axis: [tk.StringVar(value="0"), tk.StringVar(value="4")] for axis in ("x", "y", "z")}
            for stage in ("a", "b")
        }
        self.hardware_status = tk.StringVar(value="Not scanned")
        self.start_after_reference = tk.BooleanVar(value=True)
        self.show_technical = tk.BooleanVar(value=False)

        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(100, self.maximize_window)
        self.bind("<F1>", self._show_current_help)
        self.load_config_fields()
        self.after(600, self.set_current_pane_defaults)
        self.after(100, self._drain_log)
        self.after(500, self.refresh_dashboard)
        self.after(2500, self.periodic_refresh)

    def _set_tk_scaling(self) -> None:
        try:
            self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        except tk.TclError:
            pass

    def maximize_window(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

    def _build(self) -> None:
        style = ttk.Style(self)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 8), font=("Segoe UI", 10, "bold"))

        scroll_host = tk.Frame(self, bg=BG)
        scroll_host.pack(fill="both", expand=True)
        scroll_host.columnconfigure(0, weight=1)
        scroll_host.rowconfigure(0, weight=1)

        self.page_canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0, bd=0)
        self.page_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = tk.Scrollbar(scroll_host, orient="vertical", command=self.page_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.page_scrollbar = scrollbar
        self.page_canvas.configure(yscrollcommand=scrollbar.set)

        shell = tk.Frame(self.page_canvas, bg=BG, padx=18, pady=16)
        self.page_shell = shell
        self.page_window = self.page_canvas.create_window((0, 0), window=shell, anchor="nw")
        shell.bind("<Configure>", self._update_scroll_region)
        self.page_canvas.bind("<Configure>", self._resize_scroll_window)
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        self._header(shell).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.tabs = ttk.Notebook(shell)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.tabs.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        setup = tk.Frame(self.tabs, bg=BG, padx=2, pady=8)
        devices = tk.Frame(self.tabs, bg=BG, padx=2, pady=8)
        live = tk.Frame(self.tabs, bg=BG, padx=2, pady=8)
        results = tk.Frame(self.tabs, bg=BG, padx=2, pady=8)
        self.tabs.add(setup, text="Setup")
        self.tabs.add(devices, text="Devices")
        self.tabs.add(live, text="Live")
        self.tabs.add(results, text="Results")
        self.results_tab = results
        self._build_configuration_tab(setup)
        self._build_devices_tab(devices)
        self._build_live_tab(live)
        self._build_results_tab(results)

    def _build_live_tab(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        self._metrics(parent).grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.live_split = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashwidth=6, bg=BG, bd=0)
        self.live_split.grid(row=1, column=0, sticky="nsew")
        self.live_split.bind("<Configure>", lambda _event: self.on_pane_resize("live", self.live_split))
        self.live_split.add(self._operation_card(self.live_split), minsize=360)
        self.live_split.add(self._camera_card(self.live_split), minsize=360)

        self._run_card(parent).grid(row=2, column=0, sticky="ew", pady=(12, 0))

    def _build_results_tab(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.results_split_y = tk.PanedWindow(parent, orient=tk.VERTICAL, sashwidth=6, bg=BG, bd=0)
        self.results_split_y.grid(row=0, column=0, sticky="nsew")
        self.results_split_y.bind("<Configure>", lambda _event: self.on_pane_resize("results_y", self.results_split_y))
        self.results_split_x = tk.PanedWindow(self.results_split_y, orient=tk.HORIZONTAL, sashwidth=6, bg=BG, bd=0)
        self.results_split_x.bind("<Configure>", lambda _event: self.on_pane_resize("results_x", self.results_split_x))
        self.results_split_x.add(self._results_card(self.results_split_x), minsize=280)
        self.results_split_x.add(self._spectrum_card(self.results_split_x), minsize=500)
        self.results_split_y.add(self.results_split_x, minsize=360)
        self.results_split_y.add(self._activity_card(self.results_split_y), minsize=120)

    def _build_configuration_tab(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self._session_card(parent).grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._tools_card(parent).grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._program_settings_card(parent).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def _build_devices_tab(self, parent: tk.Frame) -> None:
        from labauto.equipment_ui import EquipmentDashboard

        parent.columnconfigure(0, weight=1)
        self._equipment_toolbar(parent).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.equipment = EquipmentDashboard(parent, self)
        self.equipment.grid(row=1, column=0, sticky="nsew")

    def _equipment_toolbar(self, parent) -> tk.Frame:
        frame = card(parent)
        title_row(frame, "Equipment", "Independent control and configuration sessions").pack(side="left", fill="x", expand=True)
        button(frame, "Scan PC", self.discover_hardware, primary=True).pack(side="left", padx=(8, 6))
        button(frame, "Load config", self.load_config_fields).pack(side="left", padx=(0, 6))
        button(frame, "Save selection", self.save_hardware_selection).pack(side="left")
        tk.Label(frame, textvariable=self.hardware_status, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="right", padx=(12, 0))
        return frame

    def _update_scroll_region(self, _event=None) -> None:
        bounds = self.page_canvas.bbox("all")
        self.page_canvas.configure(scrollregion=bounds)
        needs_scroll = bool(bounds and bounds[3] - bounds[1] > self.page_canvas.winfo_height() + 1)
        if needs_scroll:
            self.page_scrollbar.grid()
        else:
            self.page_scrollbar.grid_remove()
            self.page_canvas.yview_moveto(0)

    def _resize_scroll_window(self, event) -> None:
        height = max(event.height, self.page_shell.winfo_reqheight())
        self.page_canvas.itemconfigure(self.page_window, width=event.width, height=height)
        self.after_idle(self._update_scroll_region)

    def _on_mousewheel(self, event) -> None:
        if isinstance(event.widget, (tk.Text, tk.Listbox)):
            return
        steps = int(-event.delta / 120) if event.delta else 0
        if steps == 0:
            steps = -1 if event.delta > 0 else 1
        self.page_canvas.yview_scroll(steps, "units")

    def on_tab_changed(self, _event=None) -> None:
        self.after_idle(self._update_scroll_region)
        self.after(80, self.set_current_pane_defaults)

    def on_pane_resize(self, key: str, pane: tk.PanedWindow) -> None:
        size = (pane.winfo_width(), pane.winfo_height())
        if self.pane_sizes.get(key) == size:
            return
        self.pane_sizes[key] = size
        self.after_idle(self.set_current_pane_defaults)

    def set_current_pane_defaults(self) -> None:
        tab = self.current_tab()
        self.update_idletasks()
        if tab == "Live":
            width = self.live_split.winfo_width()
            if width < 100:
                self.after(100, self.set_current_pane_defaults)
                return
            self.live_split.sash_place(0, width // 2, 0)
        elif tab == "Results":
            width = self.results_split_x.winfo_width()
            height = self.results_split_y.winfo_height()
            if width < 100 or height < 100:
                self.after(100, self.set_current_pane_defaults)
                return
            self.results_split_x.sash_place(0, width // 3, 0)
            self.results_split_y.sash_place(0, 0, int(height * 0.8))
        else:
            return

    def _header(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG)
        frame.columnconfigure(1, weight=1)
        tk.Label(frame, text="PICBench", bg=BG, fg=TEXT, font=("Segoe UI", 24, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            frame,
            text="Photonic characterization dashboard",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w")
        button(frame, "? Help", self.show_help, compact=True).grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.status_label = pill(frame, "Ready", BLUE, "#e8f3ff")
        self.status_label.grid(row=0, column=3, sticky="e", padx=(8, 0))
        return frame

    def _show_current_help(self, _event=None) -> str:
        self.show_help()
        return "break"

    def show_help(self, page: str | None = None) -> None:
        page = page if page in HELP_PAGES else self.current_tab()
        if page not in HELP_PAGES:
            page = "Overview"
        dialog = tk.Toplevel(self)
        dialog.title(f"PICBench Help - {HELP_PAGES[page][0]}")
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        width = min(980, screen_width - 60)
        height = min(760, screen_height - 80)
        dialog.geometry(
            f"{width}x{height}+{max(20, (screen_width - width) // 2)}"
            f"+{max(20, (screen_height - height) // 2)}"
        )
        dialog.minsize(min(720, width), min(520, height))
        dialog.configure(bg=BG)
        dialog.transient(self)

        frame = card(dialog)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        heading = tk.Frame(frame, bg=CARD)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        title_var = tk.StringVar()
        subtitle_var = tk.StringVar()
        tk.Label(heading, textvariable=title_var, bg=CARD, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(heading, textvariable=subtitle_var, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))

        content = tk.PanedWindow(frame, orient=tk.HORIZONTAL, sashwidth=5, bg=LINE, bd=0)
        content.grid(row=1, column=0, sticky="nsew")
        navigation = tk.Frame(content, bg="#f7f9fc", padx=10, pady=10)
        tk.Label(navigation, text="TOPICS", bg="#f7f9fc", fg=MUTED, font=("Segoe UI", 8, "bold")).pack(
            anchor="w", pady=(0, 7)
        )
        topics = tk.Listbox(
            navigation,
            exportselection=False,
            activestyle="none",
            bd=0,
            highlightthickness=0,
            bg="#f7f9fc",
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground="white",
            font=("Segoe UI", 10),
        )
        topics.pack(fill="both", expand=True)
        for key in HELP_PAGES:
            topics.insert("end", key)
        content.add(navigation, minsize=150, width=180)

        text_frame = tk.Frame(content, bg=CARD)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text = tk.Text(text_frame, wrap="word", bd=0, bg="#fbfcfe", fg=TEXT, font=("Segoe UI", 10), padx=12, pady=12)
        text.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(text_frame, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        content.add(text_frame, minsize=480)

        def display(selected: str) -> None:
            title, page_content = HELP_PAGES[selected]
            fields = HELP_PAGE_FIELDS.get(selected, ())
            if fields:
                page_content += "\n\n## Editable parameters\n" + "\n".join(
                    f"- {field}: {FIELD_HELP[field]}" for field in fields
                )
            dialog.title(f"PICBench Help - {title}")
            title_var.set(title)
            subtitle_var.set("Contextual guide and safety notes")
            page_content = page_content.lstrip()
            if page_content.startswith("# "):
                page_content = page_content.split("\n", 1)[1].lstrip()
            text.configure(state="normal")
            text.delete("1.0", "end")
            insert_help_text(text, page_content)
            text.configure(state="disabled")
            text.yview_moveto(0)

        def select_topic(_event=None) -> None:
            selection = topics.curselection()
            if selection:
                display(topics.get(selection[0]))

        topics.bind("<<ListboxSelect>>", select_topic)
        initial_index = list(HELP_PAGES).index(page)
        topics.selection_set(initial_index)
        topics.activate(initial_index)
        topics.see(initial_index)
        display(page)

        button(frame, "Close", dialog.destroy, primary=True).grid(row=2, column=0, sticky="e", pady=(10, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_set()

    def _hide_tooltip(self, _event=None) -> None:
        if self._tooltip_job is not None:
            self.after_cancel(self._tooltip_job)
            self._tooltip_job = None
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def _schedule_tooltip(self, widget: tk.Widget, text: str) -> None:
        self._hide_tooltip()

        def show() -> None:
            self._tooltip_job = None
            if not widget.winfo_exists():
                return
            window = tk.Toplevel(self)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            tk.Label(
                window,
                text=text,
                wraplength=420,
                justify="left",
                bg="#fffdf5",
                fg=TEXT,
                padx=10,
                pady=7,
                relief="solid",
                borderwidth=1,
                font=("Segoe UI", 9),
            ).pack()
            window.update_idletasks()
            x = min(widget.winfo_rootx() + 12, window.winfo_screenwidth() - window.winfo_reqwidth() - 8)
            y = widget.winfo_rooty() + widget.winfo_height() + 5
            if y + window.winfo_reqheight() > window.winfo_screenheight() - 8:
                y = widget.winfo_rooty() - window.winfo_reqheight() - 5
            window.geometry(f"+{max(8, x)}+{max(8, y)}")
            self._tooltip_window = window

        self._tooltip_job = self.after(450, show)

    def helped(self, widget: tk.Widget, help_key: str) -> tk.Widget:
        text = FIELD_HELP[help_key]
        widget.configure(cursor="question_arrow")
        widget.bind("<Enter>", lambda _event: self._schedule_tooltip(widget, text), add="+")
        widget.bind("<Leave>", self._hide_tooltip, add="+")
        widget.bind("<FocusIn>", lambda _event: self._schedule_tooltip(widget, text), add="+")
        widget.bind("<FocusOut>", self._hide_tooltip, add="+")
        return widget

    def parameter_label(
        self,
        parent,
        label: str,
        *,
        help_key: str | None = None,
        bg: str = CARD,
        fg: str = MUTED,
        font=("Segoe UI", 9),
    ) -> tk.Label:
        widget = tk.Label(parent, text=f"{label}  \u24d8", bg=bg, fg=fg, font=font)
        return self.helped(widget, help_key or label)  # type: ignore[return-value]

    def _metrics(self, parent) -> tk.Frame:
        frame = tk.Frame(parent, bg=BG)
        for col in range(5):
            frame.columnconfigure(col, weight=1)
        self.metric_status = metric(frame, "Status", "Ready", ACCENT)
        self.metric_device = metric(frame, "Device", "-", PURPLE)
        self.metric_power = metric(frame, "Last power", "-", GREEN)
        self.metric_position = metric(frame, "Stage", "-", BLUE)
        self.metric_files = metric(frame, "Results", "0 files", AMBER)
        self.metric_status.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.metric_device.grid(row=0, column=1, sticky="ew", padx=8)
        self.metric_power.grid(row=0, column=2, sticky="ew", padx=8)
        self.metric_position.grid(row=0, column=3, sticky="ew", padx=8)
        self.metric_files.grid(row=0, column=4, sticky="ew", padx=(8, 0))
        return frame

    def _spectrum_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = title_row(frame, "Spectra", "Latest spectrum by default; select CSV files for overlays")
        header.grid(row=0, column=0, sticky="ew")
        tools = tk.Frame(header, bg=CARD)
        tools.grid(row=0, column=1, rowspan=2, sticky="e")
        button(tools, "Latest", self.show_latest_spectrum, compact=True).pack(side="left", padx=(0, 6))
        button(tools, "-", lambda: self.zoom_spectra_at(1 / 1.08), compact=True).pack(side="left", padx=(0, 4))
        button(tools, "+", lambda: self.zoom_spectra_at(1.08), compact=True).pack(side="left", padx=(0, 6))
        button(tools, "Reset", self.reset_spectrum_view, compact=True).pack(side="left")
        self.spectrum = tk.Canvas(frame, bg=CARD, highlightthickness=0, height=300)
        self.spectrum.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.spectrum.bind("<Configure>", lambda _event: self.schedule_spectrum_redraw())
        self.spectrum.bind("<Enter>", self.enter_spectrum)
        self.spectrum.bind("<Leave>", self.leave_spectrum)
        self.spectrum.bind("<MouseWheel>", self._on_spectrum_mousewheel)
        self.spectrum.bind("<Button-4>", self._on_spectrum_mousewheel)
        self.spectrum.bind("<Button-5>", self._on_spectrum_mousewheel)
        self.spectrum.bind("<ButtonPress-2>", self.start_spectrum_pan)
        self.spectrum.bind("<B2-Motion>", self.pan_spectrum)
        self.spectrum.bind("<Motion>", self.update_spectrum_marker)
        return frame

    def _operation_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        title_row(frame, "Operation area", "Fibers, grating couplers and travel").grid(row=0, column=0, sticky="ew")
        self.operation = tk.Canvas(frame, bg=CARD, highlightthickness=0, height=280, cursor="hand2")
        self.operation.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.operation.bind("<Configure>", lambda _event: self.draw_operation())
        self.operation.bind("<Button-1>", self.on_operation_click)
        return frame

    def _camera_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = title_row(frame, "Camera", "Live feed")
        header.grid(row=0, column=0, sticky="ew")
        tools = tk.Frame(header, bg=CARD)
        tools.grid(row=0, column=1, sticky="e")
        self.camera_button = button(tools, "Live", self.toggle_camera)
        self.camera_button.pack(side="left", padx=(0, 6))
        button(tools, "-", lambda: self.zoom_camera(1 / 1.25), compact=True).pack(side="left", padx=(0, 4))
        button(tools, "+", lambda: self.zoom_camera(1.25), compact=True).pack(side="left", padx=(0, 4))
        button(tools, "Reset", self.reset_camera_zoom, compact=True).pack(side="left", padx=(0, 6))
        button(tools, "Map gratings", self.open_grating_map).pack(side="left", padx=(0, 6))
        button(tools, "Capture", self.capture_camera).pack(side="left")
        self.camera = tk.Canvas(frame, bg="#101828", highlightthickness=0, height=280)
        self.camera.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.camera.bind("<Configure>", lambda _event: self.show_latest_capture())
        self.camera.bind("<MouseWheel>", self._on_camera_mousewheel)
        return frame

    def _hardware_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        title_row(frame, "Hardware selection", "Scan this PC and assign the discovered controllers").grid(
            row=0, column=0, columnspan=4, sticky="ew"
        )
        self.stage_combo = self.combo_row(frame, 1, "Stage controller", self.stage_serial)
        self.stage_a_combo = self.combo_row(frame, 2, "Manual Stage A", self.stage_a_serial)
        self.stage_b_combo = self.combo_row(frame, 3, "Manual Stage B", self.stage_b_serial)
        self.laser_combo = self.combo_row(frame, 3, "Laser", self.laser_resource, label_col=2, combo_col=3)
        self.pm_combo = self.combo_row(frame, 1, "Power meter", self.power_meter_resource, label_col=2, combo_col=3)
        self.camera_combo = self.combo_row(frame, 2, "Camera", self.camera_index, label_col=2, combo_col=3)
        self.parameter_label(frame, "Power meter channel").grid(
            row=4, column=2, sticky="w", pady=(10, 0), padx=(18, 8)
        )
        ttk.Combobox(frame, textvariable=self.power_meter_channel, values=(1, 2), state="readonly", width=4).grid(
            row=4, column=3, sticky="w", pady=(10, 0)
        )
        controls = tk.Frame(frame, bg=CARD)
        controls.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        button(controls, "Scan PC", self.discover_hardware, primary=True).pack(side="left", padx=(0, 8))
        button(controls, "Load config", self.load_config_fields).pack(side="left", padx=(0, 8))
        button(controls, "Save selection", self.save_hardware_selection).pack(side="left")
        tk.Label(controls, textvariable=self.hardware_status, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="right")
        return frame

    def _manual_stage_safety_card(self, parent) -> tk.Frame:
        frame = card(parent)
        for column in range(4):
            frame.columnconfigure(column, weight=1)
        title_row(frame, "Manual stage safety", "Independent safe ranges for the two NanoMax stages").grid(
            row=0, column=0, columnspan=4, sticky="ew"
        )
        pairs = [(stage, axis) for stage in ("a", "b") for axis in ("x", "y", "z")]
        for row, (stage, axis) in enumerate(pairs, start=1):
            self.parameter_label(frame, f"Stage {stage.upper()} {axis.upper()} mm", help_key="Stage safe range").grid(
                row=row, column=0, sticky="w", pady=(8, 0)
            )
            entry(frame, self.manual_limits[stage][axis][0]).grid(row=row, column=1, sticky="ew", pady=(8, 0), padx=(8, 8))
            entry(frame, self.manual_limits[stage][axis][1]).grid(row=row, column=2, sticky="ew", pady=(8, 0), padx=(0, 8))
            tk.Label(frame, text="min / max", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=row, column=3, sticky="w", pady=(8, 0))
        button(frame, "Save manual safety", self.save_manual_stage_safety, primary=True).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )
        return frame

    def combo_row(self, parent, row: int, label: str, var: tk.StringVar, *, label_col: int = 0, combo_col: int = 1):
        self.parameter_label(parent, label).grid(
            row=row, column=label_col, sticky="w", pady=(10, 0), padx=(0 if label_col == 0 else 18, 8)
        )
        combo = ttk.Combobox(parent, textvariable=var, state="readonly", values=(), font=("Segoe UI", 9))
        combo.grid(row=row, column=combo_col, sticky="ew", pady=(10, 0))
        return combo

    def _program_settings_card(self, parent) -> tk.Frame:
        frame = card(parent)
        for col in (1, 3):
            frame.columnconfigure(col, weight=1)
        title_row(frame, "Program settings", "Common measurement, Z approach and startup parameters").grid(
            row=0, column=0, columnspan=4, sticky="ew"
        )
        self.setting_row(frame, 1, "XY span um", self.span_um)
        self.setting_row(frame, 1, "XY step um", self.step_um, label_col=2, entry_col=3)
        self.setting_row(frame, 2, "Z step um", self.z_step_um)
        self.setting_row(frame, 2, "Z stop mm", self.z_stop_mm, label_col=2, entry_col=3)
        self.setting_row(frame, 3, "Target power W", self.z_target_power_w)
        self.setting_row(frame, 3, "Approach wavelength nm", self.z_wavelength_nm, label_col=2, entry_col=3)
        self.setting_row(frame, 4, "Fiber angle deg", self.fiber_angle_deg)
        self.setting_row(frame, 4, "Angle sign", self.angle_sign, label_col=2, entry_col=3)
        self.setting_row(frame, 5, "Home timeout ms", self.home_timeout_ms)
        checks = tk.Frame(frame, bg=CARD)
        checks.grid(row=5, column=2, columnspan=2, sticky="ew", pady=(2, 0), padx=(18, 0))
        z_enabled = tk.Checkbutton(checks, text="Z approach enabled  \u24d8", variable=self.z_enabled, bg=CARD, activebackground=CARD, fg=TEXT, selectcolor=CARD)
        laser_off = tk.Checkbutton(checks, text="laser off on startup  \u24d8", variable=self.laser_off_on_start, bg=CARD, activebackground=CARD, fg=TEXT, selectcolor=CARD)
        after_reference = tk.Checkbutton(checks, text="batch after reference  \u24d8", variable=self.start_after_reference, bg=CARD, activebackground=CARD, fg=TEXT, selectcolor=CARD)
        self.helped(z_enabled, "Z approach enabled").pack(side="left", padx=(0, 16))
        self.helped(laser_off, "Laser off on startup").pack(side="left", padx=(0, 16))
        self.helped(after_reference, "Batch after reference").pack(side="left")
        self.setting_row(frame, 6, "X safe min mm", self.x_min_mm)
        self.setting_row(frame, 6, "X safe max mm", self.x_max_mm, label_col=2, entry_col=3)
        self.setting_row(frame, 7, "Y safe min mm", self.y_min_mm)
        self.setting_row(frame, 7, "Y safe max mm", self.y_max_mm, label_col=2, entry_col=3)
        self.setting_row(frame, 8, "Z safe min mm", self.z_min_mm)
        self.setting_row(frame, 8, "Z safe max mm", self.z_max_mm, label_col=2, entry_col=3)
        self.setting_row(frame, 9, "Max velocity mm/s", self.max_velocity_mm_s)
        self.setting_row(frame, 9, "Acceleration mm/s2", self.acceleration_mm_s2, label_col=2, entry_col=3)
        self.setting_row(frame, 10, "Z travel mm", self.z_travel_mm)
        self.setting_row(frame, 10, "Laser tuning rate nm/s", self.laser_tuning_rate, label_col=2, entry_col=3)
        self.setting_row(frame, 11, "Laser minimum nm", self.laser_min_nm)
        self.setting_row(frame, 11, "Laser maximum nm", self.laser_max_nm, label_col=2, entry_col=3)
        self.setting_row(frame, 12, "Laser tuning margin ms", self.laser_tuning_margin_ms)
        self.setting_row(frame, 12, "Fiber XY tolerance um", self.grating_tolerance_um, label_col=2, entry_col=3)
        self.setting_row(frame, 13, "Fiber XY corrections", self.grating_max_corrections)
        self.setting_row(frame, 13, "Max XY correction um", self.grating_max_correction_um, label_col=2, entry_col=3)
        controls = tk.Frame(frame, bg=CARD)
        controls.grid(row=14, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        button(controls, "Save settings", self.save_program_settings, primary=True).pack(side="left", padx=(0, 8))
        button(controls, "Reload", self.load_config_fields).pack(side="left")
        return frame

    def setting_row(self, parent, row: int, label: str, var: tk.StringVar, *, label_col: int = 0, entry_col: int = 1) -> None:
        self.parameter_label(parent, label).grid(
            row=row, column=label_col, sticky="w", pady=(2, 0), padx=(0 if label_col == 0 else 18, 8)
        )
        entry(parent, var).grid(row=row, column=entry_col, sticky="ew", pady=(2, 0))

    def _session_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(1, weight=1)
        title_row(frame, "Session", "Files and active device").grid(row=0, column=0, columnspan=3, sticky="ew")
        self.path_row(frame, 1, "Config", self.config_path, [("JSON", "*.json"), ("All", "*.*")])
        self.path_row(frame, 2, "CSV", self.devices_path, [("CSV", "*.csv"), ("All", "*.*")])
        self.path_row(frame, 3, "Reference", self.reference_path, [("JSON", "*.json"), ("All", "*.*")])
        self.parameter_label(frame, "Device id").grid(row=4, column=0, sticky="w", pady=(10, 0))
        entry(frame, self.device_id).grid(row=4, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))
        return frame

    def _run_card(self, parent) -> tk.Frame:
        frame = card(parent)
        title_row(frame, "Run control", "Start, continue paused steps, and stop safely").grid(row=0, column=0, sticky="ew")
        row = tk.Frame(frame, bg=CARD)
        row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        button(row, "Position fibers", self.position_fibers).pack(side="left", padx=(0, 8))
        button(row, "Start batch", self.measure_batch, primary=True).pack(side="left", padx=(0, 8))
        button(row, "Resume batch", self.resume_batch).pack(side="left", padx=(0, 8))
        button(row, "Current spectrum", self.measure_spectrum).pack(side="left", padx=(0, 8))
        button(row, "Continue", self.send_enter).pack(side="left", padx=(0, 8))
        button(row, "Stop", self.stop_process, danger=True).pack(side="left")
        button(row, "Emergency stop", self.emergency_stop, danger=True).pack(side="left", padx=(8, 0))
        return frame

    def _tools_card(self, parent) -> tk.Frame:
        frame = card(parent)
        title_row(frame, "System preparation", "Initialize hardware, define the reference, then calibrate vision").grid(
            row=0, column=0, sticky="ew"
        )
        row = tk.Frame(frame, bg=CARD)
        row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        button(row, "Initialize", self.initialize_setup, primary=True).pack(side="left", padx=(0, 8))
        button(row, "Register reference", self.register_reference).pack(side="left", padx=(0, 8))
        button(row, "Vision calibration", self.open_vision_calibration).pack(side="left", padx=(0, 8))
        maintenance = tk.Menubutton(
            row,
            text="Maintenance \u25be",
            bg="#eef2f6",
            fg=TEXT,
            activebackground="#e4e9ef",
            activeforeground=TEXT,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 9),
        )
        menu = tk.Menu(maintenance, tearoff=False, font=("Segoe UI", 9))
        menu.add_command(label="Validate configuration", command=self.validate_config)
        menu.add_command(label="Run diagnostics", command=self.diagnostics)
        menu.add_command(label="Build hardware config", command=self.build_real_config)
        menu.add_command(label="Run self-test", command=self.self_test)
        menu.add_separator()
        menu.add_command(label="Manual motion", command=self.open_manual_motion)
        menu.add_command(label="Acknowledge safety lock", command=self.acknowledge_safety_lock)
        maintenance.configure(menu=menu)
        maintenance.pack(side="left")
        return frame

    def _activity_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        title_row(frame, "Activity", "Operation messages").grid(row=0, column=0, sticky="ew")
        self.activity = tk.Text(
            frame,
            height=5,
            wrap="word",
            bd=0,
            bg="#f8fafc",
            fg=TEXT,
            font=("Consolas", 9),
            padx=8,
            pady=8,
        )
        self.activity.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        controls = tk.Frame(frame, bg=CARD)
        controls.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        button(controls, "Send Enter", self.send_enter).pack(side="left", padx=(0, 8))
        button(controls, "Stop", self.stop_process, danger=True).pack(side="left")
        tk.Checkbutton(
            controls,
            text="technical details",
            variable=self.show_technical,
            command=lambda: self.toggle_widget(self.technical, self.show_technical, 3),
            bg=CARD,
            activebackground=CARD,
            fg=MUTED,
            selectcolor=CARD,
        ).pack(side="right")
        self.technical = tk.Text(frame, height=4, wrap="word", bd=0, bg="#f8fafc", fg=MUTED, font=("Consolas", 8))
        return frame

    def _results_card(self, parent) -> tk.Frame:
        frame = card(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        header = title_row(frame, "Results", "Recent files")
        header.grid(row=0, column=0, sticky="ew")
        button(header, "Refresh", self.refresh_dashboard).grid(row=0, column=1, sticky="e")
        list_frame = tk.Frame(frame, bg=CARD)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.files = tk.Listbox(
            list_frame,
            height=7,
            selectmode="extended",
            bd=0,
            highlightthickness=1,
            highlightbackground=LINE,
            bg="#fbfcfe",
            fg=TEXT,
            selectbackground="#d9f0ef",
            selectforeground="#ffffff",
            exportselection=False,
            activestyle="none",
            font=("Segoe UI", 9),
        )
        try:
            self.files.configure(inactiveselectbackground=ACCENT)
        except tk.TclError:
            pass
        self.files.configure(selectbackground=ACCENT)
        self.files.grid(row=0, column=0, sticky="nsew")
        yscroll = tk.Scrollbar(list_frame, orient="vertical", command=self.files.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll = tk.Scrollbar(list_frame, orient="horizontal", command=self.files.xview)
        xscroll.grid(row=1, column=0, sticky="ew")
        self.files.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.files.bind("<<ListboxSelect>>", lambda _event: self.on_result_selection())
        return frame

    def path_row(self, parent, row: int, label: str, var: tk.StringVar, filetypes) -> None:
        self.parameter_label(parent, label).grid(row=row, column=0, sticky="w", pady=4)
        entry(parent, var).grid(row=row, column=1, sticky="ew", padx=8, pady=2)
        button(parent, "...", lambda: self.browse(var, filetypes), compact=True).grid(row=row, column=2, pady=2)

    def browse(self, var: tk.StringVar, filetypes) -> None:
        path = filedialog.askopenfilename(initialdir=ROOT, filetypes=filetypes)
        if path:
            path = Path(path)
            try:
                var.set(str(path.relative_to(ROOT)))
            except ValueError:
                var.set(str(path))
            self.load_config_fields()
            self.refresh_dashboard()

    def load_config_fields(self) -> None:
        try:
            config = read_config(resolve_user_path(self.config_path.get()))
        except Exception:
            self.hardware_status.set("Config not loaded")
            return
        self.stage_serial.set(str(config.get("motion", {}).get("serial_number", "")))
        manual_stages = config.get("manual_stages", {})
        self.stage_a_serial.set(str(manual_stages.get("a", {}).get("serial_number", config.get("motion", {}).get("serial_number", ""))))
        self.stage_b_serial.set(str(manual_stages.get("b", {}).get("serial_number", "")))
        for stage in ("a", "b"):
            limits = manual_stages.get(stage, {}).get("limits_mm", {})
            for axis in ("x", "y", "z"):
                values = limits.get(axis, [])
                for index, var in enumerate(self.manual_limits[stage][axis]):
                    var.set(config_display(values[index]) if isinstance(values, list) and len(values) == 2 else ("0" if index == 0 else "4"))
        laser = config.get("laser", {})
        self.laser_resource.set(str(laser.get("visa_resource", "")))
        self.laser_slot.set(config_display(laser.get("slot", 1)))
        self.laser_power_mw.set(config_display(laser.get("power_mw", 1)))
        self.laser_min_nm.set(config_display(laser.get("wavelength_min_nm", 1490)))
        self.laser_max_nm.set(config_display(laser.get("wavelength_max_nm", 1610)))
        self.laser_tuning_rate.set(config_display(laser.get("tuning_rate_nm_s", 10)))
        self.laser_tuning_margin_ms.set(config_display(laser.get("tuning_margin_ms", 50)))
        power_meter = config.get("power_meter", {})
        self.power_meter_resource.set(str(power_meter.get("visa_resource", "")))
        self.power_meter_channel.set(config_display(power_meter.get("channel", 1)))
        self.camera_index.set(str(config.get("camera", {}).get("opencv_index", "")))
        z = config.get("z_approach", {})
        startup = config.get("startup", {})
        self.z_enabled.set(bool(z.get("enabled", False)))
        self.z_step_um.set(config_display(z.get("step_um", "")))
        self.z_stop_mm.set(config_display(z.get("stop_mm", "")))
        self.z_target_power_w.set(config_display(z.get("target_power_w", "")))
        self.z_wavelength_nm.set(config_display(z.get("wavelength_nm", "")))
        self.fiber_angle_deg.set(config_display(z.get("fiber_angle_deg", "")))
        self.angle_sign.set(config_display(z.get("angle_sign", "")))
        self.home_timeout_ms.set(config_display(startup.get("home_timeout_ms", "")))
        limits = config.get("motion", {}).get("limits_mm", {})
        motion = config.get("motion", {})
        self.max_velocity_mm_s.set(config_display(motion.get("max_velocity_mm_s", "")))
        self.acceleration_mm_s2.set(config_display(motion.get("acceleration_mm_s2", "")))
        self.z_travel_mm.set(config_display(motion.get("z_travel_mm", "")))
        positioning = config.get("grating_positioning", {})
        self.grating_tolerance_um.set(config_display(positioning.get("tolerance_um", 5)))
        self.grating_max_corrections.set(config_display(positioning.get("max_corrections", 3)))
        self.grating_max_correction_um.set(config_display(positioning.get("max_correction_um", 50)))
        for var, axis, index in (
            (self.x_min_mm, "x", 0), (self.x_max_mm, "x", 1),
            (self.y_min_mm, "y", 0), (self.y_max_mm, "y", 1),
            (self.z_min_mm, "z", 0), (self.z_max_mm, "z", 1),
        ):
            values = limits.get(axis, [])
            var.set(config_display(values[index]) if isinstance(values, list) and len(values) == 2 else ("0" if index == 0 else "4"))
        self.laser_off_on_start.set(bool(startup.get("laser_output_off_on_start", True)))
        self.hardware_status.set("Loaded from config")
        self.load_grating_overlay()

    def discover_hardware(self) -> None:
        self.hardware_status.set("Scanning...")
        threading.Thread(target=self._discover_hardware_worker, args=(self.config_path.get(),), daemon=True).start()

    def _discover_hardware_worker(self, config_value: str) -> None:
        try:
            from concurrent.futures import ThreadPoolExecutor

            from labauto.diagnostics import discover_cameras, discover_thorlabs, discover_visa, discover_windows_pnp

            try:
                config = read_config(resolve_user_path(config_value))
                raw_kinesis_dir = config.get("motion", {}).get("kinesis_dir")
                kinesis_dir = Path(raw_kinesis_dir) if raw_kinesis_dir else None
            except Exception:
                kinesis_dir = None
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs = {
                    "visa": pool.submit(discover_visa, 1000),
                    "cameras": pool.submit(discover_cameras, 5),
                    "thorlabs_kinesis": pool.submit(discover_thorlabs, kinesis_dir),
                }
                report = {name: job.result() for name, job in jobs.items()}
            if not any(row.get("resource") or row.get("index") is not None or row.get("serial") for rows in report.values() for row in rows):
                report["windows_pnp"] = discover_windows_pnp()
            self.log_queue.put(("hardware", report))
        except Exception as exc:
            self.log_queue.put(("hardware_error", str(exc)))

    def apply_hardware_report(self, report: dict[str, list[dict]]) -> None:
        self.hardware_report = report
        visa = [row for row in report.get("visa", []) if row.get("resource")]
        lasers = [row["resource"] for row in visa if row.get("role") == "laser"] or [row["resource"] for row in visa]
        meters = [row["resource"] for row in visa if row.get("role") == "power_meter"] or [row["resource"] for row in visa]
        stages = [row["serial"] for row in report.get("thorlabs_kinesis", []) if row.get("serial")]
        cameras = [camera_choice_label(row) for row in report.get("cameras", []) if "index" in row]
        self.stage_combo.configure(values=stages)
        self.stage_a_combo.configure(values=stages)
        self.stage_b_combo.configure(values=stages)
        self.laser_combo.configure(values=lasers)
        self.pm_combo.configure(values=meters)
        self.camera_combo.configure(values=cameras)
        for var, values in (
            (self.stage_serial, stages),
            (self.stage_a_serial, stages),
            (self.stage_b_serial, stages),
            (self.laser_resource, lasers),
            (self.power_meter_resource, meters),
            (self.camera_index, cameras),
        ):
            if values and var.get() not in values:
                var.set(values[0])
        summary = f"Detected: {len(stages)} stage(s), {len(visa)} VISA, {len(cameras)} camera(s)"
        failures = [
            f"{name}: {row['status']}"
            for name, rows in (("VISA", report.get("visa", [])), ("Camera", report.get("cameras", [])), ("Thorlabs", report.get("thorlabs_kinesis", [])))
            for row in rows
            if row.get("status") and row.get("status") != "ok"
        ]
        if failures:
            summary += ". " + failures[0]
        self.hardware_status.set(summary)
        self._activity(f"Hardware scan: {summary}\n")
        if not stages and not visa and not cameras:
            pnp = [str(row["FriendlyName"]) for row in report.get("windows_pnp", []) if row.get("FriendlyName")]
            details = "\n".join(failures or ["No compatible drivers responded."])
            if pnp:
                details += "\n\nWindows sees: " + ", ".join(pnp[:3])
            messagebox.showwarning("Hardware scan", f"No controllable equipment was detected.\n\n{details}")

    def save_hardware_selection(self) -> None:
        path = resolve_user_path(self.config_path.get())
        config = read_config(path)
        config.setdefault("motion", {})["serial_number"] = self.stage_a_serial.get() or self.stage_serial.get()
        motion = config.setdefault("motion", {})
        manual = config.setdefault("manual_stages", {})
        for stage, serial, axes in (
            ("a", self.stage_a_serial.get(), {"x": 1, "y": 2, "z": 3}),
            ("b", self.stage_b_serial.get(), {"x": 2, "y": 1, "z": 3}),
        ):
            entry = manual.setdefault(stage, {})
            entry.update({"serial_number": serial, "axis_channels": axes})
            entry.setdefault("limits_mm", {axis: [0.0, 4.0] for axis in axes})
            for key in ("kinesis_dir", "axis_stage_settings", "max_velocity_mm_s", "acceleration_mm_s2"):
                if key in motion:
                    entry.setdefault(key, motion[key])
        laser = config.setdefault("laser", {})
        laser["visa_resource"] = self.laser_resource.get()
        try:
            slot = int(self.laser_slot.get())
            power_mw = parse_number(self.laser_power_mw.get())
            if slot not in range(1, 9) or power_mw <= 0:
                raise ValueError("slot must be 1-8 and power must be positive")
        except ValueError as exc:
            messagebox.showerror("Laser settings", f"Invalid Yenista setting: {exc}")
            return
        laser.update({"slot": slot, "power_mw": power_mw})
        power_meter = config.setdefault("power_meter", {})
        power_meter["visa_resource"] = self.power_meter_resource.get()
        power_meter["channel"] = int(self.power_meter_channel.get())
        camera = self.camera_index.get()
        try:
            config.setdefault("camera", {})["opencv_index"] = parse_camera_index(camera)
        except (IndexError, ValueError):
            config.setdefault("camera", {})["opencv_index"] = camera
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        self.hardware_status.set(f"Saved {path.name}")
        self._activity(f"Hardware selection saved: {path}\n")

    def save_manual_stage_safety(self) -> None:
        path = resolve_user_path(self.config_path.get())
        config = read_config(path)
        motion = config.get("motion", {})
        manual = config.setdefault("manual_stages", {})
        try:
            for stage, axes in (("a", {"x": 1, "y": 2, "z": 3}), ("b", {"x": 2, "y": 1, "z": 3})):
                limits = {axis: [parse_number(var.get()) for var in self.manual_limits[stage][axis]] for axis in axes}
                if any(low >= high for low, high in limits.values()):
                    raise ValueError(f"Stage {stage.upper()} each minimum must be below its maximum")
                manual.setdefault(stage, {}).update({
                    "axis_channels": axes,
                    "limits_mm": limits,
                    "kinesis_dir": motion.get("kinesis_dir"),
                    "axis_stage_settings": motion.get("axis_stage_settings"),
                    "max_velocity_mm_s": motion.get("max_velocity_mm_s"),
                    "acceleration_mm_s2": motion.get("acceleration_mm_s2"),
                })
        except ValueError as exc:
            messagebox.showerror("Manual stage safety", f"Invalid safe range: {exc}")
            return
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        self.hardware_status.set(f"Saved {path.name}")
        self._activity(f"Manual stage safety saved: {path}\n")

    def save_program_settings(self) -> None:
        path = resolve_user_path(self.config_path.get())
        config = read_config(path)
        z = config.setdefault("z_approach", {})
        startup = config.setdefault("startup", {})
        motion = config.setdefault("motion", {})
        laser = config.setdefault("laser", {})
        positioning = config.setdefault("grating_positioning", {})
        z["enabled"] = self.z_enabled.get()
        try:
            set_float(z, "step_um", self.z_step_um.get())
            set_float(z, "stop_mm", self.z_stop_mm.get())
            set_float(z, "target_power_w", self.z_target_power_w.get())
            set_float(z, "wavelength_nm", self.z_wavelength_nm.get())
            set_float(z, "fiber_angle_deg", self.fiber_angle_deg.get())
            set_float(z, "angle_sign", self.angle_sign.get())
            set_int(startup, "home_timeout_ms", self.home_timeout_ms.get())
            motion["limits_mm"] = {
                "x": [parse_number(self.x_min_mm.get()), parse_number(self.x_max_mm.get())],
                "y": [parse_number(self.y_min_mm.get()), parse_number(self.y_max_mm.get())],
                "z": [parse_number(self.z_min_mm.get()), parse_number(self.z_max_mm.get())],
            }
            if any(values[0] >= values[1] for values in motion["limits_mm"].values()):
                raise ValueError("each safe minimum must be below its maximum")
            set_float(motion, "max_velocity_mm_s", self.max_velocity_mm_s.get())
            set_float(motion, "acceleration_mm_s2", self.acceleration_mm_s2.get())
            set_float(motion, "z_travel_mm", self.z_travel_mm.get())
            set_float(laser, "wavelength_min_nm", self.laser_min_nm.get())
            set_float(laser, "wavelength_max_nm", self.laser_max_nm.get())
            set_float(laser, "tuning_rate_nm_s", self.laser_tuning_rate.get())
            set_int(laser, "tuning_margin_ms", self.laser_tuning_margin_ms.get())
            tolerance_um = parse_number(self.grating_tolerance_um.get())
            max_corrections = int(self.grating_max_corrections.get())
            max_correction_um = parse_number(self.grating_max_correction_um.get())
            if tolerance_um <= 0:
                raise ValueError("fiber XY tolerance must be positive")
            if not 0 <= max_corrections <= 10:
                raise ValueError("fiber XY corrections must be between 0 and 10")
            if max_correction_um < tolerance_um:
                raise ValueError("maximum XY correction must be at least the XY tolerance")
            positioning.update(
                tolerance_um=tolerance_um,
                max_corrections=max_corrections,
                max_correction_um=max_correction_um,
            )
        except ValueError as exc:
            messagebox.showerror("Program settings", f"Invalid numeric value: {exc}")
            return
        startup["laser_output_off_on_start"] = self.laser_off_on_start.get()
        path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        self.hardware_status.set(f"Saved {path.name}")
        self._activity(f"Program settings saved: {path}\n")

    def toggle_widget(self, widget: tk.Widget, var: tk.BooleanVar, row: int) -> None:
        if var.get():
            widget.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        else:
            widget.grid_forget()

    def refresh_dashboard(self) -> None:
        self.refresh_results()
        if self.current_tab() == "Results":
            self.draw_spectra()
        self.draw_operation()
        if self.current_tab() == "Live":
            self.show_latest_capture()
        self.update_metrics(include_power=True)

    def periodic_refresh(self) -> None:
        if self.process is not None:
            self.refresh_results()
        if self.current_tab() == "Results" and self.spectrum_dirty:
            self.draw_spectra()
        if self.current_tab() == "Live":
            self.draw_operation()
        self.update_metrics(include_power=self.process is not None or self.current_tab() == "Results")
        self.after(2500, self.periodic_refresh)

    def current_tab(self) -> str:
        try:
            return self.tabs.tab(self.tabs.select(), "text")
        except tk.TclError:
            return ""

    def update_metrics(self, *, include_power: bool = False) -> None:
        set_metric(self.metric_status, "Status", self.status_label["text"])
        set_metric(self.metric_device, "Device", self.device_id.get().strip() or "-")
        if include_power:
            set_metric(self.metric_power, "Last power", latest_power_label(collect_spectra(limit=1)))
        set_metric(self.metric_position, "Stage", stage_label())
        set_metric(self.metric_files, "Results", f"{len(self.result_paths)} files")

    def selected_spectra(self) -> list[tuple[str, list[tuple[float, float]]]]:
        spectra = []
        for index in self.files.curselection():
            label = self.files.get(index)
            path = self.result_paths.get(label)
            if path:
                points = cached_spectrum_points(path)
                if points:
                    spectra.append((label, points))
        if spectra:
            return spectra
        latest = collect_spectra(limit=1)
        return latest[-1:] if latest else []

    def show_latest_spectrum(self) -> None:
        self.files.selection_clear(0, "end")
        self.current_spectra = []
        self.spectrum_data_bounds = None
        self.reset_spectrum_view()

    def zoom_spectra_at(self, factor: float, x: float | None = None, y: float | None = None) -> None:
        spectra = self.current_spectra or self.selected_spectra()
        if not spectra:
            return
        bounds = self.spectrum_data_bounds or padded_bounds(spectra)
        self.spectrum_data_bounds = bounds
        view = self.spectrum_view or bounds
        xmin, xmax, ymin, ymax = view
        cx = (xmin + xmax) / 2
        cy = (ymin + ymax) / 2
        if x is not None and y is not None and self.spectrum_plot:
            left, top, right, bottom = self.spectrum_plot
            if right > left and bottom > top:
                cx = xmin + (x - left) / (right - left) * (xmax - xmin)
                cy = ymax - (y - top) / (bottom - top) * (ymax - ymin)
        span_x = (xmax - xmin) / factor
        span_y = (ymax - ymin) / factor
        self.spectrum_view = clamp_view((cx - span_x / 2, cx + span_x / 2, cy - span_y / 2, cy + span_y / 2), bounds)
        self.schedule_spectrum_redraw()

    def reset_spectrum_view(self) -> None:
        self.spectrum_view = None
        self.draw_spectra()

    def schedule_spectrum_redraw(self) -> None:
        self.spectrum_dirty = True
        if self.spectrum_redraw_job is None:
            self.spectrum_redraw_job = self.after(16, self._flush_spectrum_redraw)

    def _flush_spectrum_redraw(self) -> None:
        self.spectrum_redraw_job = None
        if self.current_tab() == "Results":
            self.draw_spectra()

    def _on_spectrum_mousewheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            factor = 1.02 ** (delta / 120)
        else:
            factor = 1.02 if getattr(event, "num", None) == 4 else 1 / 1.02
        self.zoom_spectra_at(factor, event.x, event.y)
        return "break"

    def enter_spectrum(self, _event=None) -> None:
        self.bind_all("<MouseWheel>", self._on_spectrum_mousewheel)

    def leave_spectrum(self, _event=None) -> None:
        self.spectrum.delete("marker")
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def update_spectrum_marker(self, event) -> None:
        self.spectrum.delete("marker")
        if not self.spectrum_plot or not self.spectrum_view:
            return
        left, top, right, bottom = self.spectrum_plot
        if not (left <= event.x <= right and top <= event.y <= bottom):
            return
        xmin, xmax, ymin, ymax = self.spectrum_view
        best = None
        for _name, points in (self.current_spectra or self.selected_spectra())[-8:]:
            for x_value, y_value in nearest_points(points, xmin + (event.x - left) / (right - left) * (xmax - xmin)):
                if not (ymin <= y_value <= ymax):
                    continue
                px = left + (x_value - xmin) / (xmax - xmin) * (right - left)
                py = bottom - (y_value - ymin) / (ymax - ymin) * (bottom - top)
                distance = (px - event.x) ** 2 + (py - event.y) ** 2
                if best is None or distance < best[0]:
                    best = (distance, px, py, x_value, y_value)
        if best is None or best[0] > 900:
            return
        _distance, px, py, x_value, y_value = best
        self.spectrum.create_oval(px - 5, py - 5, px + 5, py + 5, fill=ACCENT, outline="#ffffff", width=2, tags="marker")
        text = f"x={tick_label(x_value)} nm  y={tick_label(y_value)} dBm"
        anchor = "ne" if px > (left + right) / 2 else "nw"
        tx = px - 8 if anchor == "ne" else px + 8
        ty = max(top + 12, py - 12)
        box = self.spectrum.create_text(tx, ty, anchor=anchor, text=text, fill=TEXT, font=("Segoe UI", 10, "bold"), tags="marker")
        bounds = self.spectrum.bbox(box)
        if bounds:
            x1, y1, x2, y2 = bounds
            self.spectrum.create_rectangle(x1 - 5, y1 - 3, x2 + 5, y2 + 3, fill="#ffffff", outline=LINE, tags="marker")
            self.spectrum.tag_raise(box)

    def start_spectrum_pan(self, event) -> None:
        if self.spectrum_view is None:
            spectra = self.selected_spectra()
            self.spectrum_view = padded_bounds(spectra) if spectra else None
        self.spectrum_drag = (event.x, event.y, self.spectrum_view)

    def pan_spectrum(self, event) -> None:
        if not self.spectrum_drag or not self.spectrum_plot:
            return
        start_x, start_y, view = self.spectrum_drag
        if view is None:
            return
        left, top, right, bottom = self.spectrum_plot
        if right <= left or bottom <= top:
            return
        xmin, xmax, ymin, ymax = view
        dx = (event.x - start_x) / (right - left) * (xmax - xmin)
        dy = (event.y - start_y) / (bottom - top) * (ymax - ymin)
        spectra = self.current_spectra or self.selected_spectra()
        bounds = self.spectrum_data_bounds or (padded_bounds(spectra) if spectra else None)
        self.spectrum_data_bounds = bounds
        self.spectrum_view = clamp_view((xmin - dx, xmax - dx, ymin + dy, ymax + dy), bounds) if bounds else view
        self.schedule_spectrum_redraw()

    def draw_spectra(self) -> None:
        canvas = self.spectrum
        canvas.delete("all")
        w = max(canvas.winfo_width(), 500)
        h = max(canvas.winfo_height(), 260)
        pad_l, pad_r, pad_t, pad_b = 74, 22, 28, 60
        canvas.create_rectangle(0, 0, w, h, fill=CARD, outline="")
        spectra = self.current_spectra or self.selected_spectra()
        if not spectra:
            canvas.create_text(w / 2, h / 2, text="No spectra yet", fill=MUTED, font=("Segoe UI", 12))
            self.spectrum_dirty = False
            return
        self.current_spectra = spectra
        data_bounds = self.spectrum_data_bounds or padded_bounds(spectra)
        self.spectrum_data_bounds = data_bounds
        if self.spectrum_view is None:
            self.spectrum_view = data_bounds
        xmin, xmax, ymin, ymax = self.spectrum_view
        left, top, right, bottom = pad_l, pad_t, w - pad_r, h - pad_b
        self.spectrum_plot = (left, top, right, bottom)
        canvas.create_rectangle(left, top, right, bottom, fill="#ffffff", outline=LINE)

        x_ticks = nice_ticks(xmin, xmax, 6)
        y_ticks = nice_ticks(ymin, ymax, 6)
        for value in x_ticks:
            x = left + (value - xmin) / (xmax - xmin) * (right - left)
            canvas.create_line(x, top, x, bottom, fill="#eef2f6")
            canvas.create_line(x, bottom, x, bottom + 5, fill="#98a2b3")
            canvas.create_text(x, bottom + 20, text=tick_label(value), fill=MUTED, font=("Segoe UI", 10))
        for value in y_ticks:
            y = bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
            canvas.create_line(left, y, right, y, fill="#eef2f6")
            canvas.create_line(left - 5, y, left, y, fill="#98a2b3")
            canvas.create_text(left - 9, y, anchor="e", text=tick_label(value), fill=MUTED, font=("Segoe UI", 10))
        canvas.create_line(left, top, left, bottom, fill="#98a2b3")
        canvas.create_line(left, bottom, right, bottom, fill="#98a2b3")

        palette = [ACCENT, BLUE, PURPLE, AMBER, GREEN, "#f04438", "#475467", "#2e90fa"]
        for index, (name, points) in enumerate(spectra[-8:]):
            coords: list[float] = []
            visible = visible_points(points, xmin, xmax)
            for x, yv in decimate_points(visible, max(200, int((right - left) / 2))):
                if not (xmin <= x <= xmax and ymin <= yv <= ymax):
                    continue
                px = left + (x - xmin) / (xmax - xmin) * (right - left)
                py = bottom - (yv - ymin) / (ymax - ymin) * (bottom - top)
                coords.extend((px, py))
            if len(coords) >= 4:
                color = palette[index % len(palette)]
                canvas.create_line(*coords, fill=color, width=3.0)
                canvas.create_oval(coords[-2] - 3, coords[-1] - 3, coords[-2] + 3, coords[-1] + 3, fill=color, outline="")
                canvas.create_text(right - 6, top + 16 + index * 17, anchor="e", text=Path(name).stem[:34], fill=color, font=("Segoe UI", 9))
        canvas.create_text((left + right) / 2, h - 18, text="Wavelength (nm)", fill=TEXT, font=("Segoe UI", 11, "bold"))
        canvas.create_text(20, (top + bottom) / 2, text="Power (dBm)", fill=TEXT, font=("Segoe UI", 11, "bold"), angle=90)
        canvas.create_text(left, top - 12, anchor="w", text="Middle-drag to pan | Wheel/+/- to zoom", fill=MUTED, font=("Segoe UI", 9))
        self.spectrum_dirty = False

    def draw_operation(self) -> None:
        canvas = self.operation
        canvas.delete("all")
        self.operation_hits = []
        w = max(canvas.winfo_width(), 360)
        h = max(canvas.winfo_height(), 220)
        canvas.create_rectangle(0, 0, w, h, fill=CARD, outline="")
        devices = load_devices_safe(resolve_user_path(self.devices_path.get()))
        measured = self.measured_results
        points = []
        for device in devices:
            points.extend([(device.input_gc_x, device.input_gc_y), (device.output_gc_x, device.output_gc_y)])
        if not points:
            canvas.create_text(w / 2, h / 2, text="Load a devices CSV", fill=MUTED, font=("Segoe UI", 11))
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        margin = 40
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if xmin == xmax:
            xmax = xmin + 1
        if ymin == ymax:
            ymax = ymin + 1

        def map_xy(x: float, y: float) -> tuple[float, float]:
            px = margin + (x - xmin) / (xmax - xmin) * (w - 2 * margin)
            py = h - margin - (y - ymin) / (ymax - ymin) * (h - 2 * margin)
            return px, py

        canvas.create_rectangle(margin / 2, margin / 2, w - margin / 2, h - margin / 2, outline=LINE, width=2)
        selected = self.device_id.get().strip()
        for device in devices:
            color = ACCENT if device.device_id == selected else "#98a2b3"
            x1, y1 = map_xy(device.input_gc_x, device.input_gc_y)
            x2, y2 = map_xy(device.output_gc_x, device.output_gc_y)
            x0, y0 = min(x1, x2) - 11, min(y1, y2) - 11
            x3, y3 = max(x1, x2) + 11, max(y1, y2) + 11
            self.operation_hits.append((x0, y0, x3, y3, device.device_id))
            if device.device_id in measured:
                canvas.create_rectangle(x0, y0, x3, y3, outline=GREEN, width=2)
            canvas.create_line(x1, y1, x2, y2, fill=color, width=2)
            canvas.create_oval(x1 - 5, y1 - 5, x1 + 5, y1 + 5, fill=color, outline="")
            canvas.create_oval(x2 - 5, y2 - 5, x2 + 5, y2 + 5, fill=color, outline="")
            if device.device_id == selected:
                canvas.create_text(x1, y1 - 14, text=device.device_id, fill=TEXT, font=("Segoe UI", 9, "bold"))

        latest = latest_stage_position()
        if latest:
            fx = latest.get("x", 0.0) * 1000.0
            fy = latest.get("y", 0.0) * 1000.0
            px, py = map_xy(fx, fy)
            canvas.create_line(px - 11, py, px + 11, py, fill=RED, width=2)
            canvas.create_line(px, py - 11, px, py + 11, fill=RED, width=2)
            canvas.create_text(px + 12, py + 12, anchor="w", text="fiber", fill=RED, font=("Segoe UI", 8, "bold"))

    def on_operation_click(self, event) -> None:
        for x0, y0, x1, y1, device_id in reversed(self.operation_hits):
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self.device_id.set(device_id)
                self.draw_operation()
                measured = self.measured_results.get(device_id)
                if measured:
                    self.show_measured_device(*measured)
                return

    def show_measured_device(self, label: str, path: Path) -> None:
        points = cached_spectrum_points(path)
        if not points:
            return
        self.refresh_results()
        self.files.selection_clear(0, "end")
        for index in range(self.files.size()):
            if self.files.get(index) == label:
                self.files.selection_set(index)
                self.files.see(index)
                break
        self.current_spectra = [(label, points)]
        self.spectrum_data_bounds = None
        self.spectrum_view = None
        self.tabs.select(self.results_tab)
        self.draw_spectra()

    def toggle_camera(self) -> None:
        if self.camera_live:
            self.camera_live = False
            self.camera_stop.set()
            self.camera_button.configure(text="Live", bg="#eef2f6", fg=TEXT)
            self.show_latest_capture()
            return
        try:
            index = parse_camera_index(self.camera_index.get())
            self.camera_stop.clear()
            self.camera_live = True
            self.camera_button.configure(text="Pause", bg="#e8f3ff", fg=BLUE)
            threading.Thread(target=self._camera_worker, args=(index,), daemon=True).start()
            self.update_camera()
        except Exception as exc:
            messagebox.showerror("Camera", str(exc))

    def _camera_worker(self, index: int) -> None:
        cap = None
        try:
            import cv2

            from labauto.camera import camera_backends

            for backend in camera_backends(cv2):
                candidate = cv2.VideoCapture(index, backend)
                if candidate.isOpened():
                    cap = candidate
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FPS, 30)
                    break
                candidate.release()
            if cap is None:
                raise RuntimeError(f"camera {index} did not open")
            self.camera_cap = cap
            while not self.camera_stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"camera {index} did not return a frame")
                try:
                    self.camera_frames.get_nowait()
                except queue.Empty:
                    pass
                self.camera_frames.put_nowait(frame)
        except Exception as exc:
            self.log_queue.put(("camera_error", str(exc)))
        finally:
            if cap is not None:
                cap.release()
            self.camera_cap = None

    def zoom_camera(self, factor: float) -> None:
        self.camera_zoom = min(8.0, max(0.25, self.camera_zoom * factor))
        if self.camera_live:
            return
        self.show_latest_capture()

    def reset_camera_zoom(self) -> None:
        self.camera_zoom = 1.0
        if not self.camera_live:
            self.show_latest_capture()

    def _on_camera_mousewheel(self, event):
        self.zoom_camera(1.15 if event.delta > 0 else 1 / 1.15)
        return "break"

    def update_camera(self) -> None:
        if not self.camera_live:
            return
        frame = None
        try:
            while True:
                frame = self.camera_frames.get_nowait()
        except queue.Empty:
            pass
        if frame is not None:
            self.camera_last_frame = frame
            self.camera_frame_id += 1
            self.camera_frame_timestamp = time.monotonic()
            viewer_open = any(
                dialog is not None and dialog.winfo_exists()
                for dialog in (self.grating_dialog, self.vision_dialog)
            )
            if not viewer_open:
                self.camera_photo = photo_from_bgr(
                    self.camera_frame_with_gratings(frame),
                    max(self.camera.winfo_width(), 320),
                    max(self.camera.winfo_height(), 220),
                    self.camera_zoom,
                )
                self.camera.delete("all")
                self.camera.create_rectangle(0, 0, max(self.camera.winfo_width(), 320), max(self.camera.winfo_height(), 220), fill="#101828", outline="")
                self.camera.create_image(self.camera.winfo_width() / 2, self.camera.winfo_height() / 2, image=self.camera_photo)
        self.after(40, self.update_camera)

    def camera_frame_with_gratings(self, frame):
        profile = self.grating_map
        if not profile:
            return frame
        try:
            import cv2

            from labauto.grating_map import is_compatible

            height, width = frame.shape[:2]
            if not is_compatible(profile, parse_camera_index(self.camera_index.get()), (width, height)):
                return frame
            annotated = frame.copy()
            selected = self.device_id.get().strip()
            radius = max(3, min(width, height) // 250)
            for device_id, pair in profile["devices"].items():
                point_in = tuple(round(value * size) for value, size in zip(pair["input_norm"], (width, height)))
                point_out = tuple(round(value * size) for value, size in zip(pair["output_norm"], (width, height)))
                active = device_id == selected
                cv2.line(annotated, point_in, point_out, (40, 210, 210) if active else (150, 150, 150), 3 if active else 1)
                cv2.circle(annotated, point_in, radius + (2 if active else 0), (40, 190, 70), -1)
                cv2.circle(annotated, point_out, radius + (2 if active else 0), (210, 80, 220), -1)
                if active:
                    cv2.putText(annotated, device_id, (point_in[0] + 8, point_in[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
            return annotated
        except Exception:
            return frame

    def show_latest_capture(self) -> None:
        if self.camera_live:
            return
        self.camera.delete("all")
        path = latest_file(ROOT / "workspace" / "captures", {".png", ".gif"})
        if path:
            try:
                self.camera_photo = photo_from_file(path, max(self.camera.winfo_width(), 320), max(self.camera.winfo_height(), 220), self.camera_zoom)
                self.camera.create_image(self.camera.winfo_width() / 2, self.camera.winfo_height() / 2, image=self.camera_photo)
                return
            except Exception:
                pass
        self.camera.create_rectangle(0, 0, max(self.camera.winfo_width(), 320), max(self.camera.winfo_height(), 220), fill="#101828", outline="")
        self.camera.create_text(
            self.camera.winfo_width() / 2,
            self.camera.winfo_height() / 2,
            text="Camera not started",
            fill="#d0d5dd",
            font=("Segoe UI", 12),
        )

    def confirm(self, text: str) -> bool:
        return messagebox.askyesno("Confirm", text)

    def require_device(self) -> str | None:
        device_id = self.device_id.get().strip()
        if not device_id:
            messagebox.showwarning("Missing device", "Enter the device_id from the CSV.")
            return None
        return device_id

    def run_module(self, module: str, args: list[str], label: str) -> None:
        if self.motion_locked:
            messagebox.showerror("Safety lock", "Emergency stop is active. Acknowledge the safety lock before continuing.")
            return
        connected_panels = self.equipment.connected_devices() if hasattr(self, "equipment") else []
        if connected_panels and module in {
            "scripts.alinear_xy", "scripts.aproximar_z", "scripts.inicializar_setup", "scripts.medir_espectro",
            "scripts.medir_lote", "scripts.mover_a_dispositivo",
        }:
            messagebox.showwarning(
                "Equipment connected",
                "Disconnect the equipment tabs before starting an automatic hardware action: " + ", ".join(connected_panels),
            )
            return
        if self.manual_stage_connected and module in {
            "scripts.alinear_xy", "scripts.aproximar_z", "scripts.inicializar_setup", "scripts.medir_espectro",
            "scripts.medir_lote", "scripts.mover_a_dispositivo",
        }:
            messagebox.showwarning("Manual motion", "Disconnect Manual motion before starting an automatic stage action.")
            return
        if module in {"scripts.alinear_xy", "scripts.aproximar_z", "scripts.medir_espectro", "scripts.medir_lote", "scripts.mover_a_dispositivo"}:
            from labauto.config_validator import validate_hardware_config

            errors, _warnings = validate_hardware_config(read_config(resolve_user_path(self.config_path.get())))
            if errors:
                messagebox.showerror("Preflight failed", "Fix the configuration before running:\n\n" + "\n".join(errors))
                return
        if self.process is not None:
            messagebox.showwarning("Active process", "An action is already running.")
            return
        command = module_command(module, args)
        self._activity(f"{label}: starting...\n")
        self._technical("> " + " ".join(command) + "\n")
        self.status_label.configure(text="Running", fg=BLUE, bg="#e8f3ff")
        threading.Thread(target=self._worker, args=(command, label), daemon=True).start()

    def _worker(self, command: list[str], label: str) -> None:
        try:
            self.process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert self.process.stdout is not None
            last_line = ""
            for line in self.process.stdout:
                if line.strip():
                    last_line = line.strip()
                self.log_queue.put(("activity", line))
            code = self.process.wait()
            if code == 0:
                self.log_queue.put(("activity", f"{label}: completed.\n"))
                self.log_queue.put(("status", "Ready"))
            else:
                self.log_queue.put(("activity", f"{label}: finished with code {code}.\n"))
                self.log_queue.put(("status", "Review"))
                self.log_queue.put(("run_error", f"{label} failed:\n{last_line or f'Exit code {code}'}"))
            self.log_queue.put(("technical", f"[exit {code}]\n"))
        except Exception as exc:
            self.log_queue.put(("activity", f"{label}: {exc}\n"))
            self.log_queue.put(("status", "Error"))
        finally:
            self.process = None
            self.log_queue.put(("refresh", ""))

    def _drain_log(self) -> None:
        while True:
            try:
                kind, text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "activity":
                self._activity(str(text))
            elif kind == "technical":
                self._technical(str(text))
            elif kind == "status":
                text = str(text)
                color = {"Ready": BLUE, "Review": AMBER, "Error": RED}.get(text, BLUE)
                self.status_label.configure(text=text, fg=color)
                set_metric(self.metric_status, "Status", text)
            elif kind == "refresh":
                self.refresh_dashboard()
            elif kind == "hardware":
                self.apply_hardware_report(text)  # type: ignore[arg-type]
            elif kind == "hardware_error":
                self.hardware_status.set(str(text))
            elif kind == "run_error":
                messagebox.showerror("PICBench", str(text))
            elif kind == "camera_error":
                self.camera_live = False
                self.camera_button.configure(text="Live", bg="#eef2f6", fg=TEXT)
                messagebox.showerror("Camera", str(text))
            elif kind == "grating_preview":
                self._show_grating_move_preview(text)  # type: ignore[arg-type]
            elif kind == "grating_preview_error":
                self.grating_move_pending = False
                self.status_label.configure(text="Review", fg=AMBER, bg="#fff7e8")
                set_metric(self.metric_status, "Status", "Review")
                messagebox.showerror("Position fibers", str(text))
            elif kind == "grating_verified":
                self._finish_grating_move(text)  # type: ignore[arg-type]
            elif kind == "grating_correction":
                self._execute_grating_correction(text)  # type: ignore[arg-type]
            elif kind == "grating_move_error":
                self._grating_move_failed(str(text))
            elif kind == "emergency":
                self._activity(f"Emergency stop: {text}\n")
                messagebox.showwarning("Emergency stop", str(text))
        self.after(100, self._drain_log)

    def _activity(self, text: str) -> None:
        self.activity.insert("end", text)
        self.activity.see("end")

    def _technical(self, text: str) -> None:
        self.technical.insert("end", text)
        self.technical.see("end")

    def send_enter(self) -> None:
        if self.process and self.process.stdin:
            self.process.stdin.write("\n")
            self.process.stdin.flush()
            self._activity("Continuing...\n")

    def stop_process(self) -> None:
        if self.process is not None or self.grating_move_pending:
            self.emergency_stop()

    def emergency_stop(self) -> None:
        self.motion_locked = True
        self.grating_move_pending = False
        connected_panels = self.equipment.connected_devices() if hasattr(self, "equipment") else []
        if hasattr(self, "equipment"):
            self.equipment.emergency_stop()
        process = self.process
        self.status_label.configure(text="Emergency stop", fg=RED, bg="#fef3f2")
        self._activity("Emergency stop requested.\n")
        threading.Thread(target=self._emergency_stop_worker, args=(process, not connected_panels), daemon=True).start()

    def _emergency_stop_worker(self, process, run_fallback: bool = True) -> None:
        self._terminate_process(process)
        if not run_fallback:
            self.log_queue.put(("emergency", "Emergency commands sent through the connected equipment panels."))
            return
        command = module_command("scripts.emergency_stop", ["--config", self.config_path.get()])
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
            output = result.stdout.strip() or result.stderr.strip() or "Emergency stop command finished."
            self.log_queue.put(("emergency", output if result.returncode == 0 else f"Emergency stop incomplete: {output}"))
        except Exception as exc:
            self.log_queue.put(("emergency", f"Emergency stop command failed: {exc}"))

    @staticmethod
    def _terminate_process(process) -> None:
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def acknowledge_safety_lock(self) -> None:
        if self.motion_locked and self.confirm("Confirm that the setup is safe before unlocking controls."):
            self.motion_locked = False
            self.status_label.configure(text="Review", fg=AMBER, bg="#fffaeb")
            self._activity("Safety lock acknowledged; run Initialize before moving.\n")

    def self_test(self) -> None:
        self.run_module("scripts.caracterizacion_fotonica", ["--self-test"], "Self-test")

    def validate_config(self) -> None:
        self.run_module("scripts.validar_config", ["--config", self.config_path.get()], "Validate configuration")

    def diagnostics(self) -> None:
        self.run_module("labauto.diagnostics", ["--save", "config/hardware.discovered.json"], "Diagnostics")

    def build_real_config(self) -> None:
        self.run_module(
            "scripts.crear_config_real",
            ["--discovered", "config/hardware.discovered.json", "--out", "config/hardware.real.json"],
            "Build real config",
        )

    def identify_hardware(self) -> None:
        self.run_module("scripts.probar_hardware", ["--config", self.config_path.get(), "identify"], "Identify hardware")

    def capture_camera(self) -> None:
        if self.camera_last_frame is not None and self.camera_live:
            try:
                import cv2

                path = ROOT / "workspace" / "captures" / "frame.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(path), self.camera_last_frame):
                    raise RuntimeError(f"could not write {path}")
                self._activity(f"Camera capture saved: {path}\n")
                self.refresh_results()
            except Exception as exc:
                messagebox.showerror("Camera", str(exc))
            return
        self.run_module(
            "scripts.probar_hardware",
            ["--config", self.config_path.get(), "capture", "--out", "workspace/captures/frame.png"],
            "Capture camera",
        )

    def initialize_setup(self) -> None:
        if self.confirm("Initialization can home and move axes. Continue?"):
            self.run_module("scripts.inicializar_setup", ["--config", self.config_path.get(), "--yes"], "Initialize")

    def register_reference(self) -> None:
        if self.motion_locked:
            messagebox.showerror("Safety lock", "Emergency stop is active. Acknowledge the safety lock before continuing.")
            return
        if self.manual_stage_connected:
            messagebox.showwarning("Manual motion", "Disconnect Manual motion before registering a reference.")
            return
        device_id = self.require_device()
        if not device_id:
            return
        try:
            ReferenceJogDialog(
                self,
                resolve_user_path(self.config_path.get()),
                resolve_user_path(self.devices_path.get()),
                device_id,
                self._activity,
            )
        except Exception as exc:
            messagebox.showerror("Reference", str(exc))

    def open_manual_motion(self) -> None:
        if self.motion_locked:
            messagebox.showerror("Safety lock", "Emergency stop is active. Acknowledge the safety lock before continuing.")
            return
        try:
            if self.manual_dialog is not None and self.manual_dialog.winfo_exists():
                self.manual_dialog.lift()
                self.manual_dialog.focus_set()
                return
            self.manual_dialog = ManualStageDialog(self, resolve_user_path(self.config_path.get()), self._activity)
        except Exception as exc:
            messagebox.showerror("Manual motion", str(exc))

    def open_vision_calibration(self) -> None:
        if self.vision_dialog is not None and self.vision_dialog.winfo_exists():
            self.vision_dialog.lift()
            return
        try:
            self.vision_dialog = VisionCalibrationDialog(self)
        except Exception as exc:
            self.vision_dialog = None
            messagebox.showerror("Vision calibration", str(exc))

    def open_grating_map(self) -> None:
        if self.grating_dialog is not None and self.grating_dialog.winfo_exists():
            self.grating_dialog.lift()
            return
        try:
            self.grating_dialog = GratingMapDialog(self)
        except Exception as exc:
            self.grating_dialog = None
            messagebox.showerror("Grating map", str(exc))

    def grating_map_path(self) -> Path:
        config = read_config(self.resolve_config_path())
        return resolve_user_path(str(config.get("startup", {}).get("state_dir", "workspace/state"))) / "grating_map.json"

    def load_grating_overlay(self) -> None:
        try:
            from labauto.grating_map import load_grating_map

            path = self.grating_map_path()
            self.grating_map = load_grating_map(path) if path.exists() else None
            if self.grating_map:
                valid_ids = {device.device_id for device in load_devices_safe(resolve_user_path(self.devices_path.get()))}
                self.grating_map["devices"] = {
                    device_id: pair for device_id, pair in self.grating_map["devices"].items() if device_id in valid_ids
                }
        except Exception:
            self.grating_map = None

    def position_fibers(self) -> None:
        if self.grating_move_pending:
            messagebox.showinfo("Position fibers", "A fiber-positioning action is already being prepared or executed.")
            return
        if self.motion_locked:
            messagebox.showerror("Safety lock", "Acknowledge the safety lock before moving the stages.")
            return
        if self.process is not None or self.manual_stage_connected:
            messagebox.showwarning("Position fibers", "Stop the active action and disconnect Manual motion first.")
            return
        device_id = self.require_device()
        if not device_id:
            return
        panels = {"a": self.equipment.panels[0], "b": self.equipment.panels[1]}
        if any(not panel.connected or panel.controller is None for panel in panels.values()):
            messagebox.showinfo("Position fibers", "Connect Stage A and Stage B in Devices first.")
            return
        if any(panel.busy for panel in panels.values()):
            messagebox.showinfo("Position fibers", "Wait for both stage panels to become idle.")
            return
        if not self.camera_live or self.camera_last_frame is None or time.monotonic() - self.camera_frame_timestamp > 0.5:
            messagebox.showerror("Position fibers", "Start the live camera and wait for a fresh frame.")
            return
        if not self.grating_map or device_id not in self.grating_map.get("devices", {}):
            messagebox.showerror("Position fibers", "Map and save this device's input/output gratings first.")
            return
        try:
            config = read_config(self.resolve_config_path())
            calibration_value = config.get("z_approach", {}).get("vision_calibration_path")
            if not calibration_value:
                raise ValueError("vision_calibration_path is not configured")
            calibration_path = resolve_user_path(str(calibration_value))
            z_travel_mm = parse_number(config.get("motion", {}).get("z_travel_mm"))
            camera_index = parse_camera_index(self.camera_index.get())
            positioning = config.get("grating_positioning", {})
            tolerance_um = parse_number(positioning.get("tolerance_um", 5))
            max_correction_um = parse_number(positioning.get("max_correction_um", 50))
            max_corrections_value = parse_number(positioning.get("max_corrections", 3))
            max_corrections = int(max_corrections_value)
            if tolerance_um <= 0 or max_correction_um < tolerance_um:
                raise ValueError("invalid grating_positioning tolerance or correction limit")
            if max_corrections_value != max_corrections or not 0 <= max_corrections <= 10:
                raise ValueError("grating_positioning.max_corrections must be an integer from 0 to 10")
            stage_configs = {stage: panel._config() for stage, panel in panels.items()}
            for stage, stage_config in stage_configs.items():
                lower, upper = stage_config["limits_mm"]["z"]
                if not lower <= z_travel_mm <= upper:
                    raise ValueError(
                        f"Stage {stage.upper()} travel Z {z_travel_mm:.6f} mm is outside [{lower:.6f}, {upper:.6f}] mm"
                    )
        except Exception as exc:
            messagebox.showerror("Position fibers", str(exc))
            return

        positions = {}
        self.grating_move_pending = True
        self.status_label.configure(text="Preparing move", fg=BLUE, bg="#e8f3ff")
        set_metric(self.metric_status, "Status", "Preparing move")

        def failed(exc: Exception) -> None:
            if not self.grating_move_pending:
                return
            self.grating_move_pending = False
            self.status_label.configure(text="Review", fg=AMBER, bg="#fff7e8")
            set_metric(self.metric_status, "Status", "Review")
            messagebox.showerror("Position fibers", f"Could not read both stages:\n{exc}")

        def collected(stage: str, value) -> str:
            positions[stage] = value
            if len(positions) == 2:
                if not self.camera_live or time.monotonic() - self.camera_frame_timestamp > 0.5:
                    failed(RuntimeError("camera frames became stale; restart the live camera"))
                else:
                    payload = {
                        "device_id": device_id,
                        "camera_index": camera_index,
                        "frame": self.camera_last_frame.copy(),
                        "grating_map": json.loads(json.dumps(self.grating_map)),
                        "calibration_path": calibration_path,
                        "positions": positions,
                        "stage_configs": stage_configs,
                        "z_travel_mm": z_travel_mm,
                        "tolerance_um": tolerance_um,
                        "max_corrections": max_corrections,
                        "max_correction_um": max_correction_um,
                    }
                    threading.Thread(target=self._grating_preview_worker, args=(payload,), daemon=True).start()
            return "Ready"

        for stage, panel in panels.items():
            panel.run(
                "Reading position",
                panel._positions,
                lambda value, stage=stage: collected(stage, value),
                failed,
            )

    def _grating_preview_worker(self, payload: dict) -> None:
        try:
            payload["plan"] = self._build_grating_plan(payload, payload.pop("frame"), payload["positions"])
            self.log_queue.put(("grating_preview", payload))
        except Exception as exc:
            self.log_queue.put(("grating_preview_error", str(exc)))

    @staticmethod
    def _build_grating_plan(payload: dict, frame, positions: dict) -> dict:
        from labauto.grating_map import is_compatible, plan_xy_move
        from labauto.vision_calibration import VisionGuard, load_profile

        height, width = frame.shape[:2]
        resolution = (width, height)
        profile = load_profile(payload["calibration_path"])
        if profile["camera"] != {"index": payload["camera_index"], "resolution": [width, height]}:
            raise ValueError("vision calibration does not match the selected camera and resolution")
        if not is_compatible(payload["grating_map"], payload["camera_index"], resolution):
            raise ValueError("grating map does not match the selected camera and resolution")

        stage_data = {}
        for stage in ("a", "b"):
            data = profile.get("stages", {}).get(stage)
            if not data or "xy_mapping" not in data:
                raise ValueError(f"Stage {stage.upper()} needs a saved XY vision calibration")
            if str(data.get("serial_number", "")) != str(payload["stage_configs"][stage].get("serial_number", "")):
                raise ValueError(f"Stage {stage.upper()} vision calibration belongs to another controller")
            for axis, (_position, status) in positions[stage].items():
                if not status.get("enabled") or not status.get("homed"):
                    raise RuntimeError(f"Stage {stage.upper()} {axis.upper()} is not enabled and homed")
                if any(status.get(key) for key in ("cw_hardware_limit", "ccw_hardware_limit", "cw_software_limit", "ccw_software_limit")):
                    raise RuntimeError(f"Stage {stage.upper()} {axis.upper()} has an active limit")
            located = VisionGuard(payload["calibration_path"], profile, stage).locate_tip(frame, full_frame=True)
            if not located["ok"] or located["confidence"] < float(data["confidence_min"]):
                raise RuntimeError(f"Stage {stage.upper()} fiber was not detected with sufficient confidence")
            stage_data[stage] = {
                "tip_px": located["tip_px"],
                "confidence": located["confidence"],
                "pixel_to_stage_um": data["xy_mapping"]["pixel_to_stage_um"],
                "position_mm": {axis: float(positions[stage][axis][0]) for axis in ("x", "y", "z")},
            }

        plan = plan_xy_move(payload["grating_map"]["devices"][payload["device_id"]], resolution, stage_data)
        for stage, move in plan.items():
            move["confidence"] = stage_data[stage]["confidence"]
            for axis in ("x", "y"):
                lower, upper = payload["stage_configs"][stage]["limits_mm"][axis]
                target = move["target_mm"][axis]
                if not lower <= target <= upper:
                    raise RuntimeError(
                        f"Stage {stage.upper()} {axis.upper()} target {target:.6f} mm is outside "
                        f"[{lower:.6f}, {upper:.6f}] mm"
                    )
        return plan

    def _show_grating_move_preview(self, payload: dict) -> None:
        if not self.grating_move_pending:
            return
        lines = [f"Device: {payload['device_id']}", f"Safe travel Z: {payload['z_travel_mm']:.6f} mm", ""]
        for stage in ("a", "b"):
            move = payload["plan"][stage]
            lines.extend(
                (
                    f"Stage {stage.upper()} -> {move['point'].upper()}  (vision {move['confidence']:.0%})",
                    f"  X {move['current_mm']['x']:.6f} -> {move['target_mm']['x']:.6f} mm  ({move['delta_um'][0]:+.1f} um)",
                    f"  Y {move['current_mm']['y']:.6f} -> {move['target_mm']['y']:.6f} mm  ({move['delta_um'][1]:+.1f} um)",
                    "",
                )
            )
        lines.append("Both Z axes will retract before either XY move. Continue?")
        lines.append(
            f"Vision will then correct XY up to {payload['max_corrections']} time(s): "
            f"{payload['tolerance_um']:.1f} um tolerance, {payload['max_correction_um']:.1f} um maximum correction."
        )
        if not messagebox.askyesno("Position fibers", "\n".join(lines)):
            self.grating_move_pending = False
            self.status_label.configure(text="Ready", fg=BLUE, bg="#e8f3ff")
            set_metric(self.metric_status, "Status", "Ready")
            return
        self._execute_grating_move(payload)

    def _execute_grating_move(self, payload: dict) -> None:
        panels = {"a": self.equipment.panels[0], "b": self.equipment.panels[1]}
        if self.motion_locked or any(not panel.connected or panel.busy for panel in panels.values()):
            self.grating_move_pending = False
            messagebox.showerror("Position fibers", "The stages are no longer ready; preview the move again.")
            return
        state = {"failed": False, "retracted": set(), "positions": {}}
        for panel in panels.values():
            panel.stop_requested.clear()
        self.status_label.configure(text="Retracting fibers", fg=BLUE, bg="#e8f3ff")
        set_metric(self.metric_status, "Status", "Retracting fibers")

        def failed(stage: str, exc: Exception) -> None:
            if state["failed"]:
                return
            state["failed"] = True
            for other in panels.values():
                other.stop_requested.set()
            self._grating_move_failed(f"Stage {stage.upper()}: {exc}")

        def retract(stage: str):
            panel = panels[stage]
            config = payload["stage_configs"][stage]
            channels = config["axis_channels"]
            if panel.stop_requested.is_set():
                raise RuntimeError("movement stopped")
            for axis in ("x", "y", "z"):
                status = panel.controller.status(int(channels[axis]))
                if not status.get("enabled") or not status.get("homed"):
                    raise RuntimeError(f"{axis.upper()} is not enabled and homed")
            for axis in ("x", "y"):
                current = panel.controller.position_mm(int(channels[axis]))
                if abs(current - payload["plan"][stage]["current_mm"][axis]) > 0.002:
                    raise RuntimeError("stage position changed after preview; preview the move again")
            panel.controller.move_to_mm(int(channels["z"]), payload["z_travel_mm"])
            return panel._positions()

        def retracted(stage: str, positions) -> str:
            panels[stage]._show_positions(positions)
            state["retracted"].add(stage)
            if len(state["retracted"]) == 2 and not state["failed"]:
                if self.motion_locked or any(panel.stop_requested.is_set() for panel in panels.values()):
                    failed(stage, RuntimeError("movement stopped"))
                else:
                    start_xy()
            return "At travel height"

        def move_xy(stage: str):
            panel = panels[stage]
            channels = payload["stage_configs"][stage]["axis_channels"]
            for axis in ("x", "y"):
                if panel.stop_requested.is_set():
                    raise RuntimeError("movement stopped")
                panel.controller.move_to_mm(int(channels[axis]), payload["plan"][stage]["target_mm"][axis])
            return panel._positions()

        def positioned(stage: str, positions) -> str:
            panels[stage]._show_positions(positions)
            state["positions"][stage] = positions
            if len(state["positions"]) == 2 and not state["failed"]:
                self._verify_grating_position(payload, state["positions"], corrections=0)
            return "Verifying"

        def start_xy() -> None:
            self.status_label.configure(text="Positioning fibers", fg=BLUE, bg="#e8f3ff")
            set_metric(self.metric_status, "Status", "Positioning fibers")
            for stage, panel in panels.items():
                panel.run(
                    "Positioning XY",
                    lambda stage=stage: move_xy(stage),
                    lambda positions, stage=stage: positioned(stage, positions),
                    lambda exc, stage=stage: failed(stage, exc),
                )

        for stage, panel in panels.items():
            panel.run(
                "Retracting Z",
                lambda stage=stage: retract(stage),
                lambda positions, stage=stage: retracted(stage, positions),
                lambda exc, stage=stage: failed(stage, exc),
            )

    def _verify_grating_position(
        self,
        payload: dict,
        positions: dict,
        *,
        corrections: int,
        previous_errors: dict[str, float] | None = None,
    ) -> None:
        if not self.grating_move_pending:
            return
        frame_id = self.camera_frame_id
        deadline = time.monotonic() + 2.0
        self.status_label.configure(text="Verifying fibers", fg=BLUE, bg="#e8f3ff")
        set_metric(self.metric_status, "Status", "Verifying fibers")

        def poll() -> None:
            if not self.grating_move_pending:
                return
            if not self.camera_live or self.camera_last_frame is None:
                self._grating_move_failed("live camera stopped during fiber positioning")
                return
            if self.camera_frame_id >= frame_id + 2 and time.monotonic() - self.camera_frame_timestamp < 0.5:
                frame = self.camera_last_frame.copy()
                threading.Thread(
                    target=self._grating_verification_worker,
                    args=(payload, frame, positions, corrections, previous_errors),
                    daemon=True,
                ).start()
            elif time.monotonic() >= deadline:
                self._grating_move_failed("no fresh camera frame after the stage move")
            else:
                self.after(30, poll)

        self.after(30, poll)

    def _grating_verification_worker(
        self,
        payload: dict,
        frame,
        positions: dict,
        corrections: int,
        previous_errors: dict[str, float] | None,
    ) -> None:
        try:
            from labauto.grating_map import assess_xy_correction

            plan = self._build_grating_plan(payload, frame, positions)
            errors, correct = assess_xy_correction(
                plan,
                tolerance_um=payload["tolerance_um"],
                max_correction_um=payload["max_correction_um"],
                corrections=corrections,
                max_corrections=payload["max_corrections"],
                previous_errors=previous_errors,
            )
            result = {
                "payload": payload,
                "plan": plan,
                "errors": errors,
                "corrections": corrections,
            }
            self.log_queue.put(("grating_correction" if correct else "grating_verified", result))
        except Exception as exc:
            self.log_queue.put(("grating_move_error", str(exc)))

    def _execute_grating_correction(self, result: dict) -> None:
        if not self.grating_move_pending:
            return
        payload = result["payload"]
        plan = result["plan"]
        panels = {"a": self.equipment.panels[0], "b": self.equipment.panels[1]}
        if self.motion_locked or any(not panel.connected or panel.busy for panel in panels.values()):
            self._grating_move_failed("the stages are no longer ready for visual correction")
            return
        correction_number = result["corrections"] + 1
        state = {"failed": False, "positions": {}}
        self.status_label.configure(
            text=f"Correcting fibers {correction_number}/{payload['max_corrections']}", fg=BLUE, bg="#e8f3ff"
        )
        set_metric(self.metric_status, "Status", f"Correcting {correction_number}/{payload['max_corrections']}")
        self._activity(
            f"Visual XY correction {correction_number}/{payload['max_corrections']}: "
            + ", ".join(f"Stage {stage.upper()} {result['errors'][stage]:.1f} um" for stage in ("a", "b"))
            + ".\n"
        )

        def failed(stage: str, exc: Exception) -> None:
            if state["failed"]:
                return
            state["failed"] = True
            for other in panels.values():
                other.stop_requested.set()
            self._grating_move_failed(f"Stage {stage.upper()}: {exc}")

        def correct(stage: str):
            panel = panels[stage]
            channels = payload["stage_configs"][stage]["axis_channels"]
            if panel.stop_requested.is_set():
                raise RuntimeError("movement stopped")
            for axis in ("x", "y", "z"):
                status = panel.controller.status(int(channels[axis]))
                if not status.get("enabled") or not status.get("homed"):
                    raise RuntimeError(f"{axis.upper()} is not enabled and homed")
            current_z = panel.controller.position_mm(int(channels["z"]))
            if abs(current_z - payload["z_travel_mm"]) > 0.002:
                raise RuntimeError("Z left the configured safe travel height")
            for axis in ("x", "y"):
                current = panel.controller.position_mm(int(channels[axis]))
                if abs(current - plan[stage]["current_mm"][axis]) > 0.002:
                    raise RuntimeError("stage position changed before visual correction")
                if result["errors"][stage] > payload["tolerance_um"]:
                    panel.controller.move_to_mm(int(channels[axis]), plan[stage]["target_mm"][axis])
            return panel._positions()

        def corrected(stage: str, positions) -> str:
            panels[stage]._show_positions(positions)
            state["positions"][stage] = positions
            if len(state["positions"]) == 2 and not state["failed"]:
                self._verify_grating_position(
                    payload,
                    state["positions"],
                    corrections=correction_number,
                    previous_errors=result["errors"],
                )
            return "Verifying"

        for stage, panel in panels.items():
            panel.run(
                f"Correcting XY {correction_number}",
                lambda stage=stage: correct(stage),
                lambda positions, stage=stage: corrected(stage, positions),
                lambda exc, stage=stage: failed(stage, exc),
            )

    def _finish_grating_move(self, result: dict) -> None:
        if not self.grating_move_pending:
            return
        payload = result["payload"]
        errors = result["errors"]
        self.grating_move_pending = False
        self.status_label.configure(text="Ready", fg=BLUE, bg="#e8f3ff")
        set_metric(self.metric_status, "Status", "Ready")
        summary = ", ".join(f"Stage {stage.upper()} {errors[stage]:.1f} um" for stage in ("a", "b"))
        self._activity(
            f"Fibers positioned at {payload['device_id']}: {summary}; {result['corrections']} correction(s), "
            f"travel Z {payload['z_travel_mm']:.6f} mm.\n"
        )
        messagebox.showinfo(
            "Position fibers",
            f"Both fibers are within {payload['tolerance_um']:.1f} um.\n{summary}\n\n"
            f"Z remains at the safe travel height. Corrections: {result['corrections']}.",
        )

    def _grating_move_failed(self, reason: str) -> None:
        if not self.grating_move_pending:
            return
        self.grating_move_pending = False
        self.status_label.configure(text="Review", fg=AMBER, bg="#fff7e8")
        set_metric(self.metric_status, "Status", "Review")
        self._activity(f"Position fibers stopped: {reason}\n")
        messagebox.showerror("Position fibers", reason)

    def preview_move(self) -> None:
        device_id = self.require_device()
        if not device_id:
            return
        self.run_module(
            "scripts.mover_a_dispositivo",
            [
                "--config",
                self.config_path.get(),
                "--devices",
                self.devices_path.get(),
                "--reference",
                self.reference_path.get(),
                "--device-id",
                device_id,
                "--dry-run",
            ],
            "Preview move",
        )

    def move_device(self) -> None:
        device_id = self.require_device()
        if not device_id or not self.confirm("Moving to a device can move x/y with z at travel height. Continue?"):
            return
        self.run_module(
            "scripts.mover_a_dispositivo",
            [
                "--config",
                self.config_path.get(),
                "--devices",
                self.devices_path.get(),
                "--reference",
                self.reference_path.get(),
                "--device-id",
                device_id,
                "--yes",
            ],
            "Move device",
        )

    def approach_z(self) -> None:
        if self.confirm("Approach Z can move z and turn on the laser. Continue?"):
            self.run_module("scripts.aproximar_z", ["--config", self.config_path.get(), "--yes"], "Approach Z")

    def align_xy(self) -> None:
        device_id = self.require_device()
        if not device_id or not self.confirm("XY alignment will move x/y around the current position. Continue?"):
            return
        self.run_module(
            "scripts.alinear_xy",
            [
                "--config",
                self.config_path.get(),
                "--device-id",
                device_id,
                "--span-um",
                self.span_um.get(),
                "--step-um",
                self.step_um.get(),
                "--yes",
            ],
            "Align XY",
        )

    def measure_spectrum(self) -> None:
        device_id = self.require_device()
        if not device_id or not self.confirm("Measuring a spectrum can tune the laser. Continue?"):
            return
        self.run_module(
            "scripts.medir_espectro",
            [
                "--config",
                self.config_path.get(),
                "--devices",
                self.devices_path.get(),
                "--device-id",
                device_id,
                "--yes",
            ],
            "Measure spectrum",
        )

    def measure_batch(self) -> None:
        if not self.confirm("Measuring a batch can move axes and turn on the laser. Continue?"):
            return
        args = [
            "--config",
            self.config_path.get(),
            "--devices",
            self.devices_path.get(),
            "--reference",
            self.reference_path.get(),
            "--span-um",
            self.span_um.get(),
            "--step-um",
            self.step_um.get(),
            "--yes",
        ]
        if self.start_after_reference.get():
            args.append("--start-after-reference")
        self.run_module("scripts.medir_lote", args, "Measure batch")

    def resume_batch(self) -> None:
        if not self.confirm("Resuming a batch can move axes and turn on the laser. Continue?"):
            return
        path = filedialog.askdirectory(initialdir=ROOT / "workspace" / "results")
        if path:
            self.run_module(
                "scripts.medir_lote",
                ["--config", self.config_path.get(), "--devices", self.devices_path.get(), "--resume", path, "--yes"],
                "Resume batch",
            )

    def refresh_results(self) -> None:
        previous_signature = self.result_signature
        self.files.delete(0, "end")
        self.result_paths.clear()
        entries = []
        for folder in (ROOT / "workspace" / "state", ROOT / "workspace" / "results", ROOT / "workspace" / "captures"):
            if folder.exists():
                for path in folder.rglob("*"):
                    if path.is_file():
                        try:
                            entries.append((path.stat().st_mtime_ns, path))
                        except OSError:
                            pass
        self.result_signature = tuple(sorted(entries, reverse=True))
        for _mtime, path in self.result_signature:
            label = str(path.relative_to(ROOT))
            self.result_paths[label] = path
            self.files.insert("end", label)
        if self.result_signature != previous_signature:
            result_root = ROOT / "workspace" / "results"
            self.measured_results = measured_spectra(
                [path for _mtime, path in self.result_signature if path.suffix.lower() == ".csv" and path.is_relative_to(result_root)]
            )
            self.spectrum_dirty = True

    def on_result_selection(self) -> None:
        self.spectrum_view = None
        self.spectrum_data_bounds = None
        self.current_spectra = []
        self.draw_spectra()

    def resolve_config_path(self) -> Path:
        return resolve_user_path(self.config_path.get())

    def close_app(self) -> None:
        self._hide_tooltip()
        self.camera_live = False
        self.camera_stop.set()
        process = self.process
        self._terminate_process(process)
        if self.manual_dialog is not None and self.manual_dialog.winfo_exists():
            self.manual_dialog.emergency_stop()
            self.manual_dialog.close()
        if hasattr(self, "equipment"):
            self.equipment.emergency_stop()
            self.equipment.close()
        if process is not None:
            try:
                subprocess.run(
                    module_command("scripts.emergency_stop", ["--config", self.config_path.get()]),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=True,
                )
            except Exception as exc:
                messagebox.showwarning("Emergency stop", f"Hardware stop could not be confirmed:\n{exc}")
        self.destroy()


def card(parent) -> tk.Frame:
    return tk.Frame(parent, bg=CARD, padx=14, pady=12, highlightbackground=LINE, highlightthickness=1)


def title_row(parent, title: str, subtitle: str) -> tk.Frame:
    frame = tk.Frame(parent, bg=CARD)
    frame.columnconfigure(0, weight=1)
    tk.Label(frame, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
    tk.Label(frame, text=subtitle, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w")
    return frame


def button(parent, text: str, command, *, primary: bool = False, compact: bool = False, danger: bool = False) -> tk.Button:
    bg = ACCENT if primary else "#eef2f6"
    fg = "#ffffff" if primary else (RED if danger else TEXT)
    active = ACCENT_DARK if primary else "#e4e9f0"
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active,
        activeforeground=fg,
        bd=0,
        relief="flat",
        padx=8 if compact else 13,
        pady=5 if compact else 8,
        font=("Segoe UI", 9, "bold" if primary else "normal"),
        cursor="hand2",
    )


def entry(parent, var: tk.StringVar, width: int | None = None) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=var,
        width=width or 12,
        bd=0,
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=ACCENT,
        bg="#fbfcfe",
        fg=TEXT,
        insertbackground=TEXT,
        font=("Segoe UI", 9),
    )


def pill(parent, text: str, fg: str, bg: str) -> tk.Label:
    return tk.Label(parent, text=text, bg=bg, fg=fg, padx=12, pady=6, font=("Segoe UI", 9, "bold"))


def metric(parent, label: str, value: str, color: str) -> tk.Frame:
    frame = card(parent)
    frame.configure(padx=12, pady=10)
    frame._accent = color  # type: ignore[attr-defined]
    tk.Label(frame, text=label.upper(), bg=CARD, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
    tk.Label(frame, text=value, bg=CARD, fg=TEXT, font=("Segoe UI", 15, "bold"), name="value").pack(anchor="w", pady=(4, 0))
    tk.Frame(frame, bg=color, height=3).pack(fill="x", pady=(8, 0))
    return frame


def set_metric(frame: tk.Frame, label: str, value: str) -> None:
    children = frame.winfo_children()
    if len(children) >= 2:
        children[0].configure(text=label.upper())
        children[1].configure(text=value)


def insert_help_text(text: tk.Text, content: str) -> None:
    text.tag_configure("h1", font=("Segoe UI", 20, "bold"), foreground=TEXT, spacing1=2, spacing3=12)
    text.tag_configure("h2", font=("Segoe UI", 14, "bold"), foreground=ACCENT_DARK, spacing1=14, spacing3=6)
    text.tag_configure("h3", font=("Segoe UI", 11, "bold"), foreground=TEXT, spacing1=8, spacing3=3)
    text.tag_configure("body", font=("Segoe UI", 10), foreground=TEXT, spacing3=5)
    text.tag_configure("list", font=("Segoe UI", 10), lmargin1=22, lmargin2=42, spacing3=3)
    text.tag_configure("number", font=("Segoe UI", 10), lmargin1=22, lmargin2=42, spacing3=3)
    text.tag_configure("mono", font=("Consolas", 10), foreground="#475467", lmargin1=22, lmargin2=42, spacing3=3)

    for raw in content.strip().splitlines():
        line = raw.strip()
        if not line:
            text.insert("end", "\n")
        elif line.startswith("# "):
            text.insert("end", line[2:] + "\n", "h1")
        elif line.startswith("## "):
            text.insert("end", line[3:] + "\n", "h2")
        elif line.startswith("### "):
            text.insert("end", line[4:] + "\n", "h3")
        elif line.startswith("- "):
            text.insert("end", "\u2022  " + line[2:] + "\n", "list")
        elif line[:1].isdigit() and ". " in line[:4]:
            text.insert("end", line + "\n", "number")
        elif any(line.startswith(prefix) for prefix in ("config/", "workspace/", "hardware.", "devices.")):
            text.insert("end", line + "\n", "mono")
        else:
            text.insert("end", line + "\n", "body")


def resolve_user_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def module_command(module: str, args: list[str], *, frozen: bool | None = None) -> list[str]:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return [sys.executable, "--run-module", module, *args] if frozen else [sys.executable, "-B", "-m", module, *args]


def read_config(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads((RESOURCE_ROOT / "examples" / "hardware.example.json").read_text(encoding="utf-8"))


def config_display(value) -> str:
    return "" if str(value).startswith("TODO") else str(value)


def set_float(section: dict, key: str, value: str) -> None:
    value = value.strip()
    section[key] = parse_number(value) if value else ""


def set_int(section: dict, key: str, value: str) -> None:
    value = value.strip()
    section[key] = int(value) if value else ""


def latest_file(root: Path, suffixes: set[str]) -> Path | None:
    if not root.exists():
        return None
    return max(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes),
        key=lambda path: path.stat().st_mtime,
        default=None,
    )


def collect_spectra(limit: int | None = None) -> list[tuple[str, list[tuple[float, float]]]]:
    spectra = []
    results_root = ROOT / "workspace" / "results"
    paths = sorted(results_root.rglob("*.csv"), key=lambda path: path.stat().st_mtime) if results_root.exists() else []
    if limit is not None:
        paths = paths[-limit:]
    for path in paths:
        points = cached_spectrum_points(path)
        if points:
            spectra.append((str(path.relative_to(ROOT)), points))
    return spectra


def measured_spectra(paths=None) -> dict[str, tuple[str, Path]]:
    results_root = ROOT / "workspace" / "results"
    if paths is None and not results_root.exists():
        return {}
    measured: dict[str, tuple[str, Path]] = {}
    if paths is None:
        paths = sorted(results_root.rglob("*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        device_id = spectrum_device_id(path)
        if device_id and device_id not in measured:
            measured[device_id] = (str(path.relative_to(ROOT)), path)
    return measured


def spectrum_device_id(path: Path) -> str | None:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            rows = csv.DictReader(f)
            if "device_id" not in (rows.fieldnames or []) or "wavelength_nm" not in (rows.fieldnames or []):
                return None
            row = next(rows, None)
            return row.get("device_id", "").strip() if row else None
    except Exception:
        return None


def cached_spectrum_points(path: Path) -> list[tuple[float, float]]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return []
    return _cached_spectrum_points(path, mtime)


@lru_cache(maxsize=32)
def _cached_spectrum_points(path: Path, _mtime: int) -> list[tuple[float, float]]:
    return spectrum_points(path)


def spectrum_points(path: Path) -> list[tuple[float, float]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            rows = csv.DictReader(f)
            fieldnames = rows.fieldnames or []
            if "wavelength_nm" not in fieldnames:
                return []
            points = []
            for row in rows:
                wl = float(row["wavelength_nm"])
                if "power_dbm" in fieldnames and row.get("power_dbm"):
                    power = float(row["power_dbm"])
                elif "power_w" in fieldnames and row.get("power_w"):
                    watts = float(row["power_w"])
                    if watts <= 0:
                        continue
                    power = 10.0 * math.log10(watts) + 30.0
                else:
                    continue
                points.append((wl, power))
            points.sort()
            return points
    except Exception:
        return []


def latest_power_label(spectra: list[tuple[str, list[tuple[float, float]]]]) -> str:
    if not spectra:
        return "-"
    _name, points = spectra[-1]
    if not points:
        return "-"
    return f"{points[-1][1]:.2f} dBm"


def padded_bounds(spectra: list[tuple[str, list[tuple[float, float]]]]) -> tuple[float, float, float, float]:
    xs = [x for _name, points in spectra for x, _y in points]
    ys = [y for _name, points in spectra for _x, y in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if xmin == xmax:
        xmax = xmin + 1
    if ymin == ymax:
        ymax = ymin + 1
    xpad = (xmax - xmin) * 0.03
    ypad = max((ymax - ymin) * 0.08, 0.5)
    return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad


def clamp_view(view: tuple[float, float, float, float], bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    xmin, xmax, ymin, ymax = view
    bxmin, bxmax, bymin, bymax = bounds
    span_x = xmax - xmin
    span_y = ymax - ymin
    bound_x = bxmax - bxmin
    bound_y = bymax - bymin
    if span_x >= bound_x:
        xmin, xmax = bxmin, bxmax
    elif xmin < bxmin:
        xmax += bxmin - xmin
        xmin = bxmin
    elif xmax > bxmax:
        xmin -= xmax - bxmax
        xmax = bxmax
    if span_y >= bound_y:
        ymin, ymax = bymin, bymax
    elif ymin < bymin:
        ymax += bymin - ymin
        ymin = bymin
    elif ymax > bymax:
        ymin -= ymax - bymax
        ymax = bymax
    return xmin, xmax, ymin, ymax


def nice_ticks(vmin: float, vmax: float, target: int) -> list[float]:
    span = abs(vmax - vmin)
    if span == 0:
        return [vmin]
    step0 = span / max(target - 1, 1)
    mag = 10 ** math.floor(math.log10(step0))
    step = min((1, 2, 5, 10), key=lambda item: abs(item * mag - step0)) * mag
    first = math.ceil(vmin / step) * step
    ticks = []
    value = first
    while value <= vmax + step * 0.5:
        ticks.append(value)
        value += step
    return ticks


def tick_label(value: float) -> str:
    if abs(value) < 0.0000005:
        return "0"
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text != "-0" else "0"


def visible_points(points: list[tuple[float, float]], xmin: float, xmax: float):
    start = lower_bound(points, xmin)
    stop = lower_bound(points, xmax)
    return points[max(0, start - 1) : min(len(points), stop + 2)]


def decimate_points(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
    """Reduce dense plot data while retaining each bucket's extrema."""
    if len(points) <= max_points or max_points < 4:
        return points
    bucket_size = math.ceil((len(points) - 2) / max(1, (max_points - 2) // 2))
    reduced = [points[0]]
    for start in range(1, len(points) - 1, bucket_size):
        bucket = points[start:min(len(points) - 1, start + bucket_size)]
        low = min(range(len(bucket)), key=lambda index: bucket[index][1])
        high = max(range(len(bucket)), key=lambda index: bucket[index][1])
        reduced.extend(bucket[index] for index in sorted({low, high}))
    reduced.append(points[-1])
    return reduced


def nearest_points(points: list[tuple[float, float]], x: float):
    index = lower_bound(points, x)
    return points[max(0, index - 1) : min(len(points), index + 2)]


def lower_bound(points: list[tuple[float, float]], x: float) -> int:
    return bisect_left(points, (x, float("-inf")))


def load_devices_safe(path: Path):
    try:
        from labauto.devices import load_devices

        return load_devices(path)
    except Exception:
        return []


def latest_stage_position() -> dict[str, float] | None:
    candidates = [
        ROOT / "state" / "alignment_latest.json",
        ROOT / "state" / "move_latest.json",
        ROOT / "state" / "reference_latest.json",
        ROOT / "state" / "startup_latest.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("final_position_mm", "positions_after_mm", "stage_position_mm", "positions_after_move_mm"):
                value = data.get(key)
                if isinstance(value, dict) and {"x", "y"}.issubset(value):
                    return {axis: float(value[axis]) for axis in value if axis in ("x", "y", "z")}
        except Exception:
            pass
    return None


def stage_label() -> str:
    position = latest_stage_position()
    if not position:
        return "-"
    return " ".join(f"{axis}:{position[axis]:.3f}" for axis in ("x", "y", "z") if axis in position)


def camera_choice_label(row: dict) -> str:
    text = str(row["index"])
    if row.get("backend"):
        text += f" {row['backend']}"
    if row.get("width") and row.get("height"):
        text += f" {row['width']}x{row['height']}"
    return text


def parse_camera_index(value: str) -> int:
    return int(value.strip().split()[0])


def photo_from_file(path: Path, max_w: int, max_h: int, zoom: float) -> tk.PhotoImage:
    import cv2

    frame = cv2.imread(str(path))
    if frame is None:
        raise RuntimeError(f"could not read {path}")
    return photo_from_bgr(frame, max_w, max_h, zoom)


def photo_from_bgr(frame, max_w: int, max_h: int, zoom: float = 1.0) -> tk.PhotoImage:
    import cv2

    h, w = frame.shape[:2]
    scale = min(max_w / w, max_h / h) * zoom
    if scale != 1:
        frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))))
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    data = b"P6\n" + f"{w} {h}\n255\n".encode("ascii") + rgb.tobytes()
    return tk.PhotoImage(data=data, format="PPM")


class GratingMapDialog(tk.Toplevel):
    """Sequential input/output grating annotation over the live camera image."""

    def __init__(self, parent: LabAutoUI) -> None:
        super().__init__(parent)
        from labauto.devices import load_devices

        self.parent = parent
        self.devices_path = resolve_user_path(parent.devices_path.get())
        self.devices = load_devices(self.devices_path)
        self.path = parent.grating_map_path()
        self.title("Grating coupler map")
        self.geometry("1080x820")
        self.minsize(900, 680)
        self.configure(bg=BG)
        self.transient(parent)
        self.prompt = tk.StringVar()
        self.pairs = {}
        self.index = 0
        self.input_point = None
        self.frame = None
        self.photo = None
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.drag = None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.frozen = False
        self.frozen_frame = None
        self.loaded = False
        self.incompatible_existing = False
        self._last_frame_id = -1
        self._draw_token = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._update_prompt()
        if not parent.camera_live and parent.camera_index.get():
            parent.toggle_camera()
        self.after(80, self._refresh)

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=16, pady=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        header = card(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        tk.Label(header, text="Grating coupler map", bg=CARD, fg=TEXT, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        tk.Label(
            header,
            text="Click input, then output. Devices follow the CSV row order; no hardware is moved.",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        toolbar = card(shell)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        tk.Label(toolbar, textvariable=self.prompt, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).pack(
            side="left", fill="x", expand=True
        )
        button(toolbar, "Undo", self.undo, compact=True).pack(side="left", padx=(6, 4))
        button(toolbar, "Skip", self.skip, compact=True).pack(side="left", padx=4)
        self.freeze_button = button(toolbar, "Freeze", self.toggle_freeze, compact=True)
        self.freeze_button.pack(side="left", padx=4)
        button(toolbar, "-", lambda: self.change_zoom(1 / 1.25), compact=True).pack(side="left", padx=4)
        button(toolbar, "+", lambda: self.change_zoom(1.25), compact=True).pack(side="left", padx=4)
        button(toolbar, "Reset", self.reset_view, compact=True).pack(side="left", padx=4)

        viewer = card(shell)
        viewer.grid(row=2, column=0, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewer, bg="#101828", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Button-1>", self.add_point)
        self.canvas.bind("<MouseWheel>", self._mousewheel)
        self.canvas.bind("<ButtonPress-2>", self.start_pan)
        self.canvas.bind("<B2-Motion>", self.pan_view)

        footer = tk.Frame(shell, bg=BG)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(footer, text="Green = input   Magenta = output", bg=BG, fg=MUTED).pack(side="left")
        button(footer, "Save map", self.save, primary=True).pack(side="right", padx=(8, 0))
        button(footer, "Close", self.close).pack(side="right")

    def _live_frame(self):
        if not self.parent.camera_live or self.parent.camera_last_frame is None:
            raise RuntimeError("start the live camera before mapping gratings")
        if time.monotonic() - self.parent.camera_frame_timestamp > 0.5:
            raise RuntimeError("camera frames are stale; restart the live camera")
        return self.parent.camera_last_frame.copy()

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self.frozen:
            self.frame = self.frozen_frame
            source = ("frozen", id(self.frozen_frame))
        elif self.parent.camera_last_frame is not None and self.parent.camera_frame_id != self._last_frame_id:
            self.frame = self.parent.camera_last_frame.copy()
            self._last_frame_id = self.parent.camera_frame_id
            source = ("live", self._last_frame_id)
        else:
            source = ("live", self._last_frame_id)
        if self.frame is not None and not self.loaded:
            self._load_existing()
        token = (
            source,
            self.index,
            tuple(self.input_point or ()),
            tuple(self.pairs),
            self.zoom,
            tuple(self.pan),
            self.canvas.winfo_width(),
            self.canvas.winfo_height(),
        )
        if token != self._draw_token:
            self._draw()
            self._draw_token = token
        self.after(80, self._refresh)

    def _load_existing(self) -> None:
        from labauto.grating_map import is_compatible, load_grating_map

        self.loaded = True
        if not self.path.exists():
            return
        profile = load_grating_map(self.path)
        height, width = self.frame.shape[:2]
        if not is_compatible(profile, parse_camera_index(self.parent.camera_index.get()), (width, height)):
            self.incompatible_existing = True
            return
        valid_ids = {device.device_id for device in self.devices}
        self.pairs = {device_id: pair for device_id, pair in profile["devices"].items() if device_id in valid_ids}
        self.index = self._next_unmapped(0)
        self._update_prompt()

    def add_point(self, event) -> None:
        if self.index >= len(self.devices):
            return
        if not self.frozen and (
            not self.parent.camera_live or time.monotonic() - self.parent.camera_frame_timestamp > 0.5
        ):
            messagebox.showerror("Grating map", "Start the live camera or freeze a valid frame before clicking.", parent=self)
            return
        point = self._frame_point(event.x, event.y)
        if point is None:
            return
        height, width = self.frame.shape[:2]
        normalized = [point[0] / width, point[1] / height]
        if self.input_point is None:
            self.input_point = normalized
        else:
            device_id = self.devices[self.index].device_id
            self.pairs[device_id] = {"input_norm": self.input_point, "output_norm": normalized}
            self.input_point = None
            self.index = self._next_unmapped(self.index + 1)
        self._update_prompt()

    def undo(self) -> None:
        if self.input_point is not None:
            self.input_point = None
        else:
            self.index = max(0, min(self.index - 1, len(self.devices) - 1))
            self.pairs.pop(self.devices[self.index].device_id, None)
        self._update_prompt()

    def skip(self) -> None:
        if self.index < len(self.devices):
            self.input_point = None
            self.index = self._next_unmapped(self.index + 1)
        self._update_prompt()

    def _next_unmapped(self, start: int) -> int:
        while start < len(self.devices) and self.devices[start].device_id in self.pairs:
            start += 1
        return start

    def _update_prompt(self) -> None:
        if self.index >= len(self.devices):
            self.prompt.set(f"Complete: {len(self.pairs)} / {len(self.devices)} devices mapped")
            return
        device_id = self.devices[self.index].device_id
        point = "OUTPUT" if self.input_point is not None else "INPUT"
        self.prompt.set(f"{self.index + 1} / {len(self.devices)}  {device_id}: click {point}")

    def toggle_freeze(self) -> None:
        try:
            if self.frozen:
                self.frozen = False
                self.frozen_frame = None
                self.freeze_button.configure(text="Freeze")
            else:
                self.frozen_frame = self._live_frame()
                self.frozen = True
                self.freeze_button.configure(text="Live")
        except Exception as exc:
            messagebox.showerror("Grating map", str(exc), parent=self)

    def change_zoom(self, factor: float) -> None:
        self.zoom = max(1.0, min(8.0, self.zoom * factor))

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.pan = [0.0, 0.0]

    def _mousewheel(self, event):
        self.change_zoom(1.15 if event.delta > 0 else 1 / 1.15)
        return "break"

    def start_pan(self, event) -> None:
        self.drag = (event.x, event.y, self.pan[0], self.pan[1])

    def pan_view(self, event) -> None:
        if self.drag:
            self.pan = [self.drag[2] + event.x - self.drag[0], self.drag[3] + event.y - self.drag[1]]

    def _frame_point(self, canvas_x: float, canvas_y: float):
        if self.frame is None:
            return None
        x = round((canvas_x - self.offset[0]) / self.scale)
        y = round((canvas_y - self.offset[1]) / self.scale)
        height, width = self.frame.shape[:2]
        return (x, y) if 0 <= x < width and 0 <= y < height else None

    def _draw(self) -> None:
        canvas_w, canvas_h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if self.frame is None:
            self.canvas.create_text(canvas_w / 2, canvas_h / 2, text="Start the live camera", fill="#d0d5dd", font=("Segoe UI", 12))
            return
        import cv2

        height, width = self.frame.shape[:2]
        annotated = self.frame.copy()
        radius = max(4, min(width, height) // 220)
        current_id = self.devices[self.index].device_id if self.index < len(self.devices) else ""
        for device_id, pair in self.pairs.items():
            point_in = tuple(round(value * size) for value, size in zip(pair["input_norm"], (width, height)))
            point_out = tuple(round(value * size) for value, size in zip(pair["output_norm"], (width, height)))
            cv2.line(annotated, point_in, point_out, (40, 210, 210), 2 if device_id == current_id else 1)
            cv2.circle(annotated, point_in, radius, (40, 190, 70), -1)
            cv2.circle(annotated, point_out, radius, (210, 80, 220), -1)
        if self.input_point is not None:
            point = tuple(round(value * size) for value, size in zip(self.input_point, (width, height)))
            cv2.circle(annotated, point, radius + 2, (40, 190, 70), -1)
        self.scale = min(canvas_w / width, canvas_h / height) * self.zoom
        self.offset = ((canvas_w - width * self.scale) / 2 + self.pan[0], (canvas_h - height * self.scale) / 2 + self.pan[1])
        self.photo = photo_from_bgr(annotated, canvas_w, canvas_h, self.zoom)
        self.canvas.create_image(self.offset[0], self.offset[1], image=self.photo, anchor="nw")

    def save(self) -> None:
        if not self.pairs:
            messagebox.showinfo("Grating map", "Record at least one input/output pair first.", parent=self)
            return
        if self.frame is None:
            return
        if self.incompatible_existing and not messagebox.askyesno(
            "Replace grating map",
            "The existing map belongs to another camera or resolution. Replace it?",
            parent=self,
        ):
            return
        try:
            from labauto.grating_map import save_grating_map

            height, width = self.frame.shape[:2]
            profile = save_grating_map(
                self.path,
                camera_index=parse_camera_index(self.parent.camera_index.get()),
                resolution=(width, height),
                devices_path=self.devices_path,
                pairs=self.pairs,
            )
            self.parent.grating_map = profile
            self.parent._activity(f"Grating map saved: {self.path} ({len(self.pairs)} devices)\n")
            self.incompatible_existing = False
            messagebox.showinfo("Grating map", f"Saved {len(self.pairs)} device pairs.", parent=self)
        except Exception as exc:
            messagebox.showerror("Grating map", str(exc), parent=self)

    def close(self) -> None:
        self.parent.grating_dialog = None
        self.destroy()


class VisionCalibrationDialog(tk.Toplevel):
    """Guided, non-moving enrollment of each fiber and its safe chip clearance."""

    def __init__(self, parent: LabAutoUI) -> None:
        super().__init__(parent)
        self.parent = parent
        self.title("Vision and fiber calibration")
        self.geometry("1080x820")
        self.minsize(900, 680)
        self.configure(bg=BG)
        self.transient(parent)
        self.stage = tk.StringVar(value="a")
        self.xy_step_um = tk.StringVar(value="50")
        self.instruction = tk.StringVar(value="Connect Stage A and start the camera, then set the ROI.")
        self.mode = None
        self.frame = None
        self.frozen_frame = None
        self.photo = None
        self.scale = 1.0
        self.offset = (0.0, 0.0)
        self.roi_px = None
        self.roi_start = None
        self.chip_line_px = []
        self.samples = {}
        self.xy_mapping = None
        self.pending_position = None
        self._last_frame_id = -1
        self._draw_token = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        if not parent.camera_live and parent.camera_index.get():
            parent.toggle_camera()
        self.after(80, self._refresh)

    def _build(self) -> None:
        shell = tk.Frame(self, bg=BG, padx=16, pady=16)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(2, weight=1)

        header = card(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        tk.Label(header, text="Vision calibration", bg=CARD, fg=TEXT, font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            header,
            text="Only Map XY moves the selected stage; move Z manually from the Devices tab.",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.parent.parameter_label(header, "Stage").grid(row=0, column=1, sticky="e", padx=(10, 6))
        stage_combo = ttk.Combobox(header, textvariable=self.stage, state="readonly", values=("a", "b"), width=5)
        stage_combo.grid(row=0, column=2, sticky="e")
        stage_combo.bind("<<ComboboxSelected>>", self._change_stage)

        steps = card(shell)
        steps.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        steps.columnconfigure(0, weight=1)
        tk.Label(steps, textvariable=self.instruction, bg=CARD, fg=TEXT, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=8, sticky="ew", pady=(0, 8)
        )
        button(steps, "1  Set ROI", self.set_roi).grid(row=1, column=0, sticky="w", padx=(0, 4))
        button(steps, "2  Chip line", self.set_chip_line).grid(row=1, column=1, padx=4)
        button(steps, "3  Far", lambda: self.record("far")).grid(row=1, column=2, padx=4)
        self.parent.parameter_label(steps, "XY step (um)").grid(row=1, column=3, padx=(14, 4))
        entry(steps, self.xy_step_um, width=7).grid(row=1, column=4, padx=(0, 4))
        button(steps, "4  Map XY", self.calibrate_xy).grid(row=1, column=5, padx=4)
        button(steps, "5  Near", lambda: self.record("near")).grid(row=1, column=6, padx=4)
        button(steps, "6  Minimum safe", lambda: self.record("minimum_safe")).grid(row=1, column=7, padx=(4, 0))

        viewer = card(shell)
        viewer.grid(row=2, column=0, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewer, bg="#101828", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<ButtonRelease-1>", self._release)

        footer = tk.Frame(shell, bg=BG)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        tk.Label(
            footer,
            text="Safety: use a known collision-free Z range. Minimum safe must remain above physical contact.",
            bg=BG,
            fg=RED,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        button(footer, "Save stage", self.save, primary=True).pack(side="right", padx=(8, 0))
        button(footer, "Close", self.close).pack(side="right")

    def _change_stage(self, _event=None) -> None:
        self.mode = None
        self.frozen_frame = None
        self.roi_px = None
        self.chip_line_px = []
        self.samples = {}
        self.xy_mapping = None
        self.instruction.set(f"Stage {self.stage.get().upper()}: set the ROI around the fiber tip and chip edge.")

    def _live_frame(self):
        if not self.parent.camera_live or self.parent.camera_last_frame is None:
            raise RuntimeError("start the live camera before recording calibration data")
        if time.monotonic() - self.parent.camera_frame_timestamp > 0.5:
            raise RuntimeError("camera frames are stale; restart the live camera")
        return self.parent.camera_last_frame.copy()

    def set_roi(self) -> None:
        try:
            self.frozen_frame = self._live_frame()
            self.mode = "roi"
            self.roi_start = None
            self.instruction.set("Drag a rectangle around the selected fiber tip and the nearby chip edge.")
        except Exception as exc:
            messagebox.showerror("Vision calibration", str(exc), parent=self)

    def set_chip_line(self) -> None:
        if self.roi_px is None:
            messagebox.showinfo("Vision calibration", "Set the ROI first.", parent=self)
            return
        try:
            self.frozen_frame = self._live_frame()
            self.mode = "line"
            self.chip_line_px = []
            self.instruction.set("Click two separated points along the visible chip surface.")
        except Exception as exc:
            messagebox.showerror("Vision calibration", str(exc), parent=self)

    def record(self, name: str) -> None:
        if self.roi_px is None or len(self.chip_line_px) != 2:
            messagebox.showinfo("Vision calibration", "Set the ROI and chip line first.", parent=self)
            return
        panel = self._stage_panel()
        if not panel.connected or panel.controller is None:
            messagebox.showinfo("Vision calibration", f"Connect Stage {self.stage.get().upper()} in Devices first.", parent=self)
            return
        if panel.busy:
            messagebox.showinfo("Vision calibration", "Wait for the stage operation to finish.", parent=self)
            return
        try:
            positions = panel._positions()
            self.pending_position = {axis: float(value[0]) for axis, value in positions.items()}
            self.frozen_frame = self._live_frame()
            self.mode = f"sample:{name}"
            label = name.replace("_", " ").title()
            self.instruction.set(f"{label}: click the visible fiber tip. Z = {self.pending_position['z']:.6f} mm")
        except Exception as exc:
            messagebox.showerror("Vision calibration", str(exc), parent=self)

    def calibrate_xy(self) -> None:
        if "far" not in self.samples or self.roi_px is None:
            messagebox.showinfo("Vision calibration", "Record Far before mapping X and Y.", parent=self)
            return
        if self.parent.motion_locked:
            messagebox.showerror("Vision calibration", "Acknowledge the safety lock before automatic XY mapping.", parent=self)
            return
        if self.parent.manual_stage_connected:
            messagebox.showwarning("Vision calibration", "Disconnect Manual motion before automatic XY mapping.", parent=self)
            return
        if self.parent.process is not None and self.parent.process.poll() is None:
            messagebox.showwarning("Vision calibration", "Stop the active measurement before automatic XY mapping.", parent=self)
            return
        panel = self._stage_panel()
        if not panel.connected or panel.controller is None:
            messagebox.showinfo("Vision calibration", f"Connect Stage {self.stage.get().upper()} in Devices first.", parent=self)
            return
        if panel.busy:
            messagebox.showinfo("Vision calibration", "Wait for the stage operation to finish.", parent=self)
            return
        try:
            from labauto.vision_calibration import calculate_xy_mapping, locate_tip

            step_um = parse_number(self.xy_step_um.get())
            if not 10 <= step_um <= 500:
                raise ValueError("XY calibration step must be between 10 and 500 um")
            positions = panel._positions()
            if any(not status.get("enabled") or not status.get("homed") for _position, status in positions.values()):
                raise RuntimeError("all three stage axes must be enabled and homed")
            origin = {axis: float(value[0]) for axis, value in positions.items()}
            far_position = self.samples["far"]["position_mm"]
            if any(abs(origin[axis] - far_position[axis]) > 0.005 for axis in ("x", "y", "z")):
                raise RuntimeError("return to the recorded Far position before XY mapping")
            current_frame = self._live_frame()
            initial = locate_tip(self.samples["far"]["frame"], self.samples["far"]["tip_px"], current_frame, self.roi_px)
            if initial["confidence"] < 0.55 or math.dist(initial["tip_px"], self.samples["far"]["tip_px"]) > 8:
                raise RuntimeError("the current fiber image no longer matches the recorded Far state")

            stage_config = panel._config()
            targets = {}
            for axis in ("x", "y"):
                lower, upper = stage_config["limits_mm"][axis]
                delta_mm = step_um / 1000.0
                if origin[axis] + delta_mm <= upper:
                    targets[axis] = origin[axis] + delta_mm
                elif origin[axis] - delta_mm >= lower:
                    targets[axis] = origin[axis] - delta_mm
                else:
                    raise RuntimeError(f"no room for a {step_um:g} um {axis.upper()} calibration move")
        except Exception as exc:
            messagebox.showerror("Vision calibration", str(exc), parent=self)
            return

        stage = self.stage.get().upper()
        if not messagebox.askyesno(
            "Automatic XY mapping",
            f"Stage {stage} will move X and Y separately by {step_um:g} um and return after each move.\n\n"
            "Confirm the fiber is at the collision-free Far height, the laser output is OFF, and the camera image is stable.",
            parent=self,
        ):
            return

        panel.stop_requested.clear()
        self.instruction.set(f"Stage {stage}: mapping X/Y. Use Emergency stop to abort immediately.")
        reference_frame = self.samples["far"]["frame"]
        reference_tip = self.samples["far"]["tip_px"]
        channels = stage_config["axis_channels"]

        def fresh_frame(previous_id: int):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if panel.stop_requested.is_set():
                    raise RuntimeError("XY mapping stopped")
                if (
                    self.parent.camera_frame_id >= previous_id + 2
                    and time.monotonic() - self.parent.camera_frame_timestamp < 0.5
                    and self.parent.camera_last_frame is not None
                ):
                    return self.parent.camera_last_frame.copy()
                time.sleep(0.02)
            raise RuntimeError("no fresh camera frame after the stage move")

        def action():
            moves = {}
            try:
                for axis in ("x", "y"):
                    channel = int(channels[axis])
                    moved = False
                    try:
                        if panel.stop_requested.is_set():
                            raise RuntimeError("XY mapping stopped")
                        previous_id = self.parent.camera_frame_id
                        panel.controller.move_to_mm(channel, targets[axis])
                        moved = True
                        observed = float(panel.controller.position_mm(channel))
                        moves[axis] = {
                            "delta_mm": observed - origin[axis],
                            "frame": fresh_frame(previous_id),
                        }
                    finally:
                        if moved and not panel.stop_requested.is_set():
                            panel.controller.move_to_mm(channel, origin[axis])
                            returned = float(panel.controller.position_mm(channel))
                            if abs(returned - origin[axis]) > 0.002:
                                raise RuntimeError(f"Stage {stage} {axis.upper()} did not return to its initial position")
                mapping = calculate_xy_mapping(reference_frame, reference_tip, self.roi_px, moves)
                mapping["origin_position_mm"] = origin
                return {"mapping": mapping}
            except Exception as exc:
                return {"error": str(exc)}

        def done(result) -> str:
            if "error" in result:
                self.instruction.set(f"XY mapping failed: {result['error']}")
                self.parent._activity(f"Stage {stage} XY mapping failed: {result['error']}\n")
                messagebox.showerror("Vision calibration", result["error"], parent=self)
                return "XY mapping failed"
            self.xy_mapping = result["mapping"]
            x_move = self.xy_mapping["moves"]["x"]["pixel_delta"]
            y_move = self.xy_mapping["moves"]["y"]["pixel_delta"]
            self.instruction.set(
                f"XY mapped. X -> ({x_move[0]:+.1f}, {x_move[1]:+.1f}) px; "
                f"Y -> ({y_move[0]:+.1f}, {y_move[1]:+.1f}) px. Continue with Near."
            )
            return "XY mapping ready"

        panel.run("Mapping XY", action, done)

    def _stage_panel(self):
        return self.parent.equipment.panels[0 if self.stage.get() == "a" else 1]

    def _press(self, event) -> None:
        point = self._frame_point(event.x, event.y)
        if point is None:
            return
        if self.mode == "roi":
            self.roi_start = point
        elif self.mode == "line":
            self.chip_line_px.append(point)
            if len(self.chip_line_px) == 2:
                self.mode = None
                self.frozen_frame = None
                self.instruction.set("Chip line recorded. Move to a clearly safe Far height and record the fiber tip.")
        elif isinstance(self.mode, str) and self.mode.startswith("sample:"):
            name = self.mode.split(":", 1)[1]
            if not self._inside_roi(point):
                messagebox.showwarning("Vision calibration", "The fiber tip must be inside the ROI.", parent=self)
                return
            self.samples[name] = {
                "frame": self.frozen_frame.copy(),
                "tip_px": point,
                "position_mm": self.pending_position,
            }
            self.mode = None
            self.frozen_frame = None
            self.pending_position = None
            recorded = ", ".join(name.replace("_", " ").title() for name in self.samples)
            self.instruction.set(f"Recorded: {recorded}. Move Z safely, then record the next height.")

    def _release(self, event) -> None:
        if self.mode != "roi" or self.roi_start is None:
            return
        end = self._frame_point(event.x, event.y)
        if end is None:
            return
        x0, x1 = sorted((self.roi_start[0], end[0]))
        y0, y1 = sorted((self.roi_start[1], end[1]))
        if x1 - x0 < 20 or y1 - y0 < 20:
            messagebox.showwarning("Vision calibration", "Draw a larger ROI.", parent=self)
            return
        self.roi_px = (x0, y0, x1 - x0, y1 - y0)
        self.mode = None
        self.frozen_frame = None
        self.instruction.set("ROI recorded. Mark the chip surface with two clicks.")

    def _inside_roi(self, point) -> bool:
        x, y, width, height = self.roi_px
        return x <= point[0] <= x + width and y <= point[1] <= y + height

    def _frame_point(self, canvas_x: float, canvas_y: float):
        if self.frame is None:
            return None
        x = round((canvas_x - self.offset[0]) / self.scale)
        y = round((canvas_y - self.offset[1]) / self.scale)
        height, width = self.frame.shape[:2]
        if not 0 <= x < width or not 0 <= y < height:
            return None
        return x, y

    def _refresh(self) -> None:
        if not self.winfo_exists():
            return
        if self.frozen_frame is not None:
            self.frame = self.frozen_frame
            source = ("frozen", id(self.frozen_frame))
        elif self.parent.camera_last_frame is not None and self.parent.camera_frame_id != self._last_frame_id:
            self.frame = self.parent.camera_last_frame.copy()
            self._last_frame_id = self.parent.camera_frame_id
            source = ("live", self._last_frame_id)
        else:
            source = ("live", self._last_frame_id)
        samples = tuple(sorted((name, tuple(sample["tip_px"])) for name, sample in self.samples.items()))
        token = (
            source,
            self.mode,
            tuple(self.roi_px or ()),
            tuple(self.chip_line_px),
            samples,
            self.canvas.winfo_width(),
            self.canvas.winfo_height(),
        )
        if token != self._draw_token:
            self._draw()
            self._draw_token = token
        self.after(80, self._refresh)

    def _draw(self) -> None:
        width, height = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.canvas.delete("all")
        if self.frame is None:
            self.canvas.create_text(width / 2, height / 2, text="Start the live camera", fill="#d0d5dd", font=("Segoe UI", 12))
            return
        frame_h, frame_w = self.frame.shape[:2]
        self.scale = min(width / frame_w, height / frame_h)
        shown_w, shown_h = frame_w * self.scale, frame_h * self.scale
        self.offset = ((width - shown_w) / 2, (height - shown_h) / 2)
        self.photo = photo_from_bgr(self.frame, width, height)
        self.canvas.create_image(width / 2, height / 2, image=self.photo)

        def display(point):
            return self.offset[0] + point[0] * self.scale, self.offset[1] + point[1] * self.scale

        if self.roi_px:
            x, y, roi_w, roi_h = self.roi_px
            x0, y0 = display((x, y))
            x1, y1 = display((x + roi_w, y + roi_h))
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#12b76a", width=3)
        if len(self.chip_line_px) == 1:
            x, y = display(self.chip_line_px[0])
            self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#f79009", outline="#ffffff")
        elif len(self.chip_line_px) == 2:
            self.canvas.create_line(*display(self.chip_line_px[0]), *display(self.chip_line_px[1]), fill="#f79009", width=3)
        for name, sample in self.samples.items():
            x, y = display(sample["tip_px"])
            self.canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline="#ffffff", fill="#2f80ed", width=2)
            self.canvas.create_text(x + 8, y - 8, text=name.replace("_", " "), fill="#ffffff", anchor="sw")

    def save(self) -> None:
        if (
            self.roi_px is None
            or len(self.chip_line_px) != 2
            or set(self.samples) != {"far", "near", "minimum_safe"}
            or self.xy_mapping is None
        ):
            messagebox.showinfo("Vision calibration", "Complete ROI, chip line, Far, XY mapping, Near and Minimum safe first.", parent=self)
            return
        try:
            from labauto.vision_calibration import save_stage_calibration

            config_path = self.parent.resolve_config_path()
            config = json.loads(config_path.read_text(encoding="utf-8"))
            state_dir = resolve_user_path(str(config.get("startup", {}).get("state_dir", "workspace/state")))
            profile_path = state_dir / "vision_calibration.json"
            stage = self.stage.get()
            serial = self.parent.stage_a_serial.get() if stage == "a" else self.parent.stage_b_serial.get()
            stage_profile = save_stage_calibration(
                profile_path,
                stage=stage,
                camera_index=parse_camera_index(self.parent.camera_index.get()),
                serial_number=serial,
                roi_px=self.roi_px,
                chip_line_px=(self.chip_line_px[0], self.chip_line_px[1]),
                samples=self.samples,
                xy_mapping=self.xy_mapping,
            )
            try:
                stored_path = str(profile_path.relative_to(ROOT))
            except ValueError:
                stored_path = str(profile_path)
            z_settings = config.setdefault("z_approach", {})
            z_settings["vision_calibration_path"] = stored_path
            z_settings.setdefault("roi_by_stage", {})[stage] = stage_profile["roi"]
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            self.parent._activity(f"Stage {stage.upper()} vision calibration saved: {profile_path}\n")
            self.instruction.set(f"Stage {stage.upper()} saved. Calibrate the other stage or close the assistant.")
            messagebox.showinfo(
                "Vision calibration",
                f"Stage {stage.upper()} calibration saved.\n\nAutomatic Z approach remains disabled until you enable it in Setup.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Vision calibration", str(exc), parent=self)

    def close(self) -> None:
        self.parent.vision_dialog = None
        self.destroy()


class ReferenceJogDialog(tk.Toplevel):
    def __init__(self, parent: LabAutoUI, config_path: Path, devices_path: Path, device_id: str, log) -> None:
        super().__init__(parent)
        self.title("Register reference")
        self.configure(bg=BG)
        self.transient(parent)
        self.grab_set()
        self.log = log

        from labauto.bsc_config import automatic_stage_configs, axis_channel, bsc_from_config, stage_position_mm
        from labauto.config import load_hardware_config
        from labauto.devices import find_device
        from labauto.manual_align import save_reference

        self.axis_channel = axis_channel
        self.stage_position_mm = stage_position_mm
        self.save_reference = save_reference
        self.config = load_hardware_config(config_path)
        self.device = find_device(devices_path, device_id)
        self.stage = tk.StringVar(value="a")
        self.stage_configs = automatic_stage_configs(self.config)
        self.controller_cms = {}
        self.controllers = {}
        try:
            for stage, stage_config in self.stage_configs.items():
                cm = bsc_from_config({"motion": stage_config})
                self.controller_cms[stage] = cm
                self.controllers[stage] = cm.__enter__()
        except Exception:
            for cm in reversed(list(self.controller_cms.values())):
                cm.__exit__(None, None, None)
            raise

        state_dir = Path(self.config.get("startup", {}).get("state_dir", "workspace/state"))
        self.state_dir = state_dir if state_dir.is_absolute() else ROOT / state_dir
        self.step_um = tk.StringVar(value="1")
        self.enable_z = tk.BooleanVar(value=False)
        self.position = tk.StringVar()

        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._bind_keys()
        self.update_position()

    def _build(self) -> None:
        frame = card(self)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(frame, text=f"Reference: {self.device.device_id}", bg=CARD, fg=TEXT, font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 8)
        )
        tk.Label(frame, textvariable=self.position, bg=CARD, fg=MUTED).grid(row=1, column=0, columnspan=5, sticky="w", pady=(0, 10))
        self.master.parameter_label(frame, "Step um").grid(row=2, column=0, sticky="w")
        tk.OptionMenu(frame, self.step_um, "0.5", "1", "5", "10", "50", "100", "250", "500").grid(row=2, column=1, sticky="w")
        allow_z = tk.Checkbutton(frame, text="Allow Z  \u24d8", variable=self.enable_z, bg=CARD, selectcolor=CARD)
        self.master.helped(allow_z, "Allow Z").grid(row=2, column=2, sticky="w")
        stage_menu = tk.OptionMenu(frame, self.stage, "a", "b")
        self.master.helped(stage_menu, "Stage").grid(row=2, column=3, sticky="w")
        button(frame, "Y+", lambda: self.move("y", 1)).grid(row=3, column=1, padx=5, pady=5)
        button(frame, "X-", lambda: self.move("x", -1)).grid(row=4, column=0, padx=5, pady=5)
        button(frame, "X+", lambda: self.move("x", 1)).grid(row=4, column=2, padx=5, pady=5)
        button(frame, "Y-", lambda: self.move("y", -1)).grid(row=5, column=1, padx=5, pady=5)
        button(frame, "Z+", lambda: self.move("z", 1)).grid(row=3, column=4, padx=(18, 5), pady=5)
        button(frame, "Z-", lambda: self.move("z", -1)).grid(row=5, column=4, padx=(18, 5), pady=5)
        button(frame, "Save reference", self.save, primary=True).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        button(frame, "Close", self.close).grid(row=6, column=2, columnspan=3, sticky="ew", pady=(14, 0))

    def _bind_keys(self) -> None:
        for key, axis, sign in (
            ("<Left>", "x", -1),
            ("<Right>", "x", 1),
            ("<Up>", "y", 1),
            ("<Down>", "y", -1),
            ("a", "x", -1),
            ("d", "x", 1),
            ("w", "y", 1),
            ("s", "y", -1),
            ("r", "z", 1),
            ("f", "z", -1),
        ):
            self.bind(key, lambda _event, ax=axis, sg=sign: self.move(ax, sg))
        self.bind("<Return>", lambda _event: self.save())
        self.focus_set()

    def move(self, axis: str, sign: int) -> None:
        if axis == "z" and not self.enable_z.get():
            return
        step_mm = float(self.step_um.get()) / 1000.0
        try:
            stage = self.stage.get()
            stage_config = {"motion": self.stage_configs[stage]}
            self.controllers[stage].move_by_mm(self.axis_channel(stage_config, axis), sign * step_mm)
            self.update_position()
        except Exception as exc:
            self.log(f"Manual {axis.upper()} move failed: {exc}\n")
            messagebox.showerror("Manual move", f"{axis.upper()} move failed:\n{exc}", parent=self)

    def update_position(self) -> None:
        parts = []
        for stage, controller in self.controllers.items():
            stage_config = {"motion": self.stage_configs[stage]}
            pos = self.stage_position_mm(stage_config, controller)
            parts.append(f"{stage.upper()}: " + ", ".join(f"{axis}={value:.6f}" for axis, value in pos.items()))
        self.position.set("  |  ".join(parts))

    def save(self) -> None:
        path = self.save_reference(self.config, self.device, self.controllers, self.state_dir)
        self.log(f"Reference saved: {path}\n")
        self.close()

    def close(self) -> None:
        try:
            for cm in reversed(list(self.controller_cms.values())):
                cm.__exit__(None, None, None)
        finally:
            self.destroy()


class ManualStageDialog(tk.Toplevel):
    """Isolated jog control for the two physical NanoMax stages."""

    def __init__(self, parent: LabAutoUI, config_path: Path, log) -> None:
        super().__init__(parent)
        self.title("Manual motion")
        self.configure(bg=BG)
        self.transient(parent)
        self.parent = parent
        self.config_path = config_path
        self.log = log
        self.stage = tk.StringVar(value="a")
        self.step_um = tk.StringVar(value="1")
        self.enable_z = tk.BooleanVar(value=False)
        self.position = tk.StringVar(value="Select a stage and connect.")
        self.controller_cm = None
        self.controller = None
        self.stage_config = None
        self.stopped = False
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self._bind_keys()

    def _build(self) -> None:
        frame = card(self)
        frame.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(frame, text="Manual motion", bg=CARD, fg=TEXT, font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 4)
        )
        tk.Label(frame, text="Logical sample axes; no laser, camera, CSV, or reference is used.", bg=CARD, fg=MUTED).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 10)
        )
        self.parent.parameter_label(frame, "Stage").grid(row=2, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.stage, state="readonly", values=("a", "b"), width=10).grid(row=2, column=1, sticky="w")
        button(frame, "Connect", self.connect_stage, primary=True).grid(row=2, column=2, sticky="ew", padx=(8, 0))
        button(frame, "Home", self.home_stage).grid(row=2, column=3, sticky="ew", padx=(8, 0))
        tk.Label(frame, textvariable=self.position, bg=CARD, fg=MUTED, wraplength=430, justify="left").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(10, 8)
        )
        self.parent.parameter_label(frame, "Step um").grid(row=4, column=0, sticky="w")
        tk.OptionMenu(frame, self.step_um, "0.5", "1", "5", "10", "50", "100", "250", "500").grid(row=4, column=1, sticky="w")
        allow_z = tk.Checkbutton(
            frame, text="Allow Z  \u24d8", variable=self.enable_z, bg=CARD, activebackground=CARD, selectcolor=CARD
        )
        self.parent.helped(allow_z, "Allow Z").grid(row=4, column=2, sticky="w")
        button(frame, "Y+", lambda: self.move("y", 1)).grid(row=5, column=1, padx=5, pady=5)
        button(frame, "X-", lambda: self.move("x", -1)).grid(row=6, column=0, padx=5, pady=5)
        button(frame, "X+", lambda: self.move("x", 1)).grid(row=6, column=2, padx=5, pady=5)
        button(frame, "Y-", lambda: self.move("y", -1)).grid(row=7, column=1, padx=5, pady=5)
        button(frame, "Z+", lambda: self.move("z", 1)).grid(row=5, column=3, padx=(18, 5), pady=5)
        button(frame, "Z-", lambda: self.move("z", -1)).grid(row=7, column=3, padx=(18, 5), pady=5)
        button(frame, "Emergency stop", self.emergency_stop, danger=True).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        button(frame, "Close", self.close).grid(row=8, column=2, columnspan=2, sticky="ew", padx=(8, 0), pady=(12, 0))

    def _bind_keys(self) -> None:
        for key, axis, sign in (
            ("<Left>", "x", -1), ("<Right>", "x", 1), ("<Up>", "y", 1), ("<Down>", "y", -1),
            ("a", "x", -1), ("d", "x", 1), ("w", "y", 1), ("s", "y", -1), ("r", "z", 1), ("f", "z", -1),
        ):
            self.bind(key, lambda _event, ax=axis, sg=sign: self.move(ax, sg))
        self.focus_set()

    def connect_stage(self) -> None:
        from labauto.bsc_config import bsc_from_config, manual_stage_config
        from labauto.config import load_hardware_config

        self.disconnect()
        try:
            config = load_hardware_config(self.config_path)
            self.stage_config = manual_stage_config(config, self.stage.get())
            self.controller_cm = bsc_from_config({"motion": self.stage_config})
            self.controller = self.controller_cm.__enter__()
            self.parent.manual_stage_connected = True
            self.stopped = False
            self.update_position()
            profiles = ", ".join(
                f"{axis.upper()}={self.controller.settings_name(int(channel))}"
                for axis, channel in self.stage_config["axis_channels"].items()
            )
            self.log(f"Manual Stage {self.stage.get().upper()} connected; profiles: {profiles}\n")
        except Exception as exc:
            self.disconnect()
            messagebox.showerror("Manual motion", str(exc), parent=self)

    def move(self, axis: str, sign: int) -> None:
        if axis == "z" and not self.enable_z.get():
            return
        if self.controller is None or self.stage_config is None:
            messagebox.showinfo("Manual motion", "Connect a stage before jogging.", parent=self)
            return
        if self.stopped:
            messagebox.showerror("Manual motion", "Emergency stop is active. Close this dialog and acknowledge the safety lock.", parent=self)
            return
        try:
            channel = int(self.stage_config["axis_channels"][axis])
            current = self.controller.position_mm(channel)
            target = current + sign * float(self.step_um.get()) / 1000.0
            lower, upper = self.stage_config["limits_mm"][axis]
            if not lower <= target <= upper:
                messagebox.showwarning(
                    "Configured safe limit",
                    f"Blocked {axis.upper()} move before sending it to Kinesis.\n\n"
                    f"Current: {current:.6f} mm\nRequested: {target:.6f} mm\n"
                    f"Configured safe range: [{lower:.6f}, {upper:.6f}] mm",
                    parent=self,
                )
                self.update_position()
                return
            self.controller.move_to_mm(channel, target)
            observed = self.controller.position_mm(channel)
            self.log(
                f"Manual Stage {self.stage.get().upper()} {axis.upper()}: requested {target - current:+.6f} mm, "
                f"encoder {observed - current:+.6f} mm.\n"
            )
            self.update_position()
        except Exception as exc:
            self.log(f"Manual Stage {self.stage.get().upper()} {axis.upper()} move failed: {exc}\n")
            messagebox.showerror("Manual motion", f"{axis.upper()} move failed:\n{exc}", parent=self)

    def home_stage(self) -> None:
        if self.controller is None or self.stage_config is None:
            messagebox.showinfo("Manual motion", "Connect a stage before homing.", parent=self)
            return
        if not messagebox.askyesno(
            "Home",
            "Home the selected stage in Z, X, Y order using the active Kinesis profiles?",
            parent=self,
        ):
            return
        try:
            self.position.set(f"Homing Stage {self.stage.get().upper()}...")
            self.update_idletasks()
            for axis in ("z", "x", "y"):
                self.controller.home(int(self.stage_config["axis_channels"][axis]))
            self.update_position()
            self.log(f"Manual Stage {self.stage.get().upper()} homed using its Kinesis profiles.\n")
        except Exception as exc:
            self.log(f"Manual Stage {self.stage.get().upper()} home failed: {exc}\n")
            messagebox.showerror("Home", str(exc), parent=self)

    def update_position(self) -> None:
        if self.controller is None or self.stage_config is None:
            return
        values = []
        needs_home = False
        outside_limits = False
        for axis, channel in self.stage_config["axis_channels"].items():
            position = self.controller.position_mm(int(channel))
            status = self.controller.status(int(channel))
            needs_home |= status.get("enabled") is False or status.get("homed") is False
            lower, upper = self.stage_config["limits_mm"][axis]
            outside_limits |= not lower <= position <= upper
            flags = "/".join(name for name, value in status.items() if value and name.endswith("limit"))
            values.append(
                f"{axis.upper()}={position:.6f} mm  safe [{lower:.6f}, {upper:.6f}]"
                + (f" ({flags})" if flags else "")
            )
        suffix = " | Use Home stage before jogging." if needs_home else ""
        if outside_limits:
            suffix += " | Current position is outside the configured safe range."
        self.position.set(f"Stage {self.stage.get().upper()}: " + ", ".join(values) + suffix)

    def emergency_stop(self) -> None:
        if self.controller is None or self.stage_config is None:
            return
        channels = [int(channel) for channel in self.stage_config["axis_channels"].values()]
        result = self.controller.emergency_stop(channels)
        self.stopped = True
        self.parent.motion_locked = True
        self.parent.status_label.configure(text="Emergency stop", fg=RED, bg="#fef3f2")
        self.log(f"Manual Stage {self.stage.get().upper()} emergency stop: {result}\n")
        self.position.set("Emergency stop sent. Close this dialog and acknowledge the safety lock after inspection.")

    def disconnect(self) -> None:
        if self.controller_cm is not None:
            self.controller_cm.__exit__(None, None, None)
        self.controller_cm = None
        self.controller = None
        self.stage_config = None
        self.parent.manual_stage_connected = False

    def close(self) -> None:
        self.disconnect()
        self.parent.manual_dialog = None
        self.destroy()


def _self_check() -> None:
    from labauto.equipment_ui import compact_equipment_layout

    assert set(HELP_PAGES) == {"Overview", "Setup", "Devices", "Live", "Results"}
    assert all(title and content.lstrip().startswith("# ") for title, content in HELP_PAGES.values())
    assert all(field in FIELD_HELP for fields in HELP_PAGE_FIELDS.values() for field in fields)
    assert compact_equipment_layout(1180) and not compact_equipment_layout(1920)
    points = [(float(index), float(index % 7)) for index in range(100)]
    reduced = decimate_points(points, 20)
    assert len(reduced) <= 20
    assert reduced[0] == points[0] and reduced[-1] == points[-1]
    assert min(point[1] for point in reduced) == min(point[1] for point in points)
    assert max(point[1] for point in reduced) == max(point[1] for point in points)
    assert module_command("scripts.validar_config", ["--help"], frozen=False)[2:4] == ["-m", "scripts.validar_config"]
    assert module_command("scripts.validar_config", ["--help"], frozen=True)[1:3] == ["--run-module", "scripts.validar_config"]


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--run-module":
        module = sys.argv[2]
        if not module.startswith(("labauto.", "scripts.")):
            raise SystemExit(f"unsupported module: {module}")
        sys.argv = [module, *sys.argv[3:]]
        import runpy

        runpy.run_module(module, run_name="__main__")
        return
    if "--self-check" in sys.argv:
        _self_check()
        print("ui self-check ok")
        return
    LabAutoUI().mainloop()


if __name__ == "__main__":
    main()

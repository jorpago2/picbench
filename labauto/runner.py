from __future__ import annotations

import csv
import json
import math
import tempfile
from datetime import datetime
from pathlib import Path

from labauto.devices import Device, load_devices, wavelengths_nm
from labauto.motion import SafeMotion, now_utc
from labauto.simulation import SimulatedPowerMeter
from labauto.thorlabs_bsc203 import BSC203


SPECTRA_COLUMNS = [
    "device_id",
    "wavelength_nm",
    "power_dbm",
    "power_w",
    "x_um",
    "y_um",
    "z_um",
    "input_gc_x",
    "input_gc_y",
    "output_gc_x",
    "output_gc_y",
    "polarization",
    "timestamp",
]


def run(devices_csv: Path, out_root: Path) -> Path:
    devices = load_devices(devices_csv)
    run_dir = out_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    motion = SafeMotion()
    meter = SimulatedPowerMeter()

    with (run_dir / "spectra.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SPECTRA_COLUMNS)
        writer.writeheader()
        for device in devices:
            motion.move_xy(device.input_gc_x, device.input_gc_y)
            align_xy(device, motion, meter)
            for wavelength in wavelengths_nm(
                device.lambda_start_nm, device.lambda_stop_nm, device.lambda_step_nm
            ):
                power_dbm = meter.read_dbm(device, motion.x_um, motion.y_um, wavelength)
                writer.writerow(
                    {
                        "device_id": device.device_id,
                        "wavelength_nm": f"{wavelength:.6f}",
                        "power_dbm": f"{power_dbm:.4f}",
                        "power_w": f"{10 ** ((power_dbm - 30.0) / 10.0):.12g}",
                        "x_um": f"{motion.x_um:.3f}",
                        "y_um": f"{motion.y_um:.3f}",
                        "z_um": f"{motion.z_um:.3f}",
                        "input_gc_x": f"{device.input_gc_x:.3f}",
                        "input_gc_y": f"{device.input_gc_y:.3f}",
                        "output_gc_x": f"{device.output_gc_x:.3f}",
                        "output_gc_y": f"{device.output_gc_y:.3f}",
                        "polarization": device.polarization,
                        "timestamp": now_utc(),
                    }
                )

    with (run_dir / "motion_log.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(motion.events[0]))
        writer.writeheader()
        writer.writerows(motion.events)
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "devices_csv": str(devices_csv),
                "mode": "simulation",
                "z_policy": "no automatic descent; xy moves retract before long travel",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_dir


def align_xy(device: Device, motion: SafeMotion, meter: SimulatedPowerMeter) -> tuple[float, float, float]:
    best = (motion.x_um, motion.y_um, float("-inf"))
    for step_um in (3.0, 1.0):
        center_x, center_y = best[0], best[1]
        for ix in range(-2, 3):
            for iy in range(-2, 3):
                motion.move_xy(center_x + ix * step_um, center_y + iy * step_um)
                power_dbm = meter.read_dbm(device, motion.x_um, motion.y_um, device.lambda_start_nm)
                if power_dbm > best[2]:
                    best = (motion.x_um, motion.y_um, power_dbm)
        motion.move_xy(best[0], best[1])
    return best


def self_test() -> None:
    from labauto.alignment import align_xy_with_sessions, grid_offsets_um
    from labauto.batch import select_batch_devices
    from labauto.bsc_config import MANUAL_STAGE_AXES, NANOMAX_DRV208_SETTINGS, bsc_from_config, manual_stage_config
    from labauto.config import parse_number
    from labauto.config_builder import build_real_config
    from labauto.config_validator import validate_hardware_config
    from labauto.manual_align import key_move
    from labauto.move_to_device import move_to_device, plan_move
    from labauto.spectrum import SPECTRUM_COLUMNS, prepare_measurement_laser
    from labauto.thorlabs_bsc203 import decimal_text, dotnet_float, safe_limits
    from labauto.visa_devices import VisaLaser, VisaPowerMeter, response_number
    from labauto.z_approach import approach_z_with_sessions, prepare_z_laser

    assert list(wavelengths_nm(1500, 1501, 0.5)) == [1500.0, 1500.5, 1501.0]
    assert SPECTRUM_COLUMNS[:3] == ["device_id", "wavelength_nm", "power_w"]
    assert grid_offsets_um(2, 1) == [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert grid_offsets_um(2, 1.5) == [-2.0, -0.5, 1.0, 2.0]

    class FakeController:
        axes = {1: "x", 2: "y", 3: "z"}

        def __init__(self) -> None:
            self.position = {"x": 0.0, "y": 0.0, "z": 0.0}

        def position_mm(self, channel: int) -> float:
            return self.position[self.axes[channel]]

        def move_to_mm(self, channel: int, position_mm: float) -> None:
            self.position[self.axes[channel]] = position_mm

    controller = FakeController()

    class FakeMeter:
        def read_power_w(self) -> float:
            return 1.0 - (controller.position["x"] - 0.003) ** 2 - (controller.position["y"] + 0.001) ** 2

    alignment = align_xy_with_sessions(
        {"motion": {"axis_channels": {"x": 1, "y": 2, "z": 3}}},
        controller,
        FakeMeter(),
        device_id="test_001",
        span_um=4,
        step_um=4,
        settle_ms=0,
    )
    assert [item["name"] for item in alignment["passes"]] == ["coarse", "fine"]
    assert round(alignment["best"]["x_mm"], 6) == 0.003
    assert round(alignment["best"]["y_mm"], 6) == -0.001

    class FakeZMeter:
        def read_power_w(self) -> float:
            return 1.0 if controller.position["z"] <= 0.004 else 0.0

    class FakeCamera:
        def read(self):
            import numpy as np

            return np.zeros((4, 4, 3), dtype=np.uint8)

    controller.position = {"x": 0.0, "y": 0.0, "z": 0.010}
    z_report = approach_z_with_sessions(
        {
            "motion": {"axis_channels": {"x": 1, "y": 2, "z": 3}},
            "z_approach": {
                "stop_mm": 0.0,
                "step_um": 2.0,
                "settle_ms": 0,
                "target_power_w": 0.5,
                "fiber_angle_deg": 10.0,
                "angle_axis": "x",
                "angle_sign": 1.0,
            },
        },
        controller,
        FakeZMeter(),
        FakeCamera(),
    )
    assert z_report["status"] == "ok"
    assert z_report["stop_reason"] == "target_power"
    assert round(z_report["final_position_mm"]["z"], 6) == 0.004
    expected_x = (0.004 - 0.010) * math.tan(math.radians(10.0))
    assert round(z_report["final_position_mm"]["x"], 6) == round(expected_x, 6)

    controller.position = {"x": 0.0, "y": 0.0, "z": 0.010}
    failed_z = approach_z_with_sessions(
        {
            "motion": {"axis_channels": {"x": 1, "y": 2, "z": 3}},
            "z_approach": {"stop_mm": 0.008, "step_um": 2.0, "settle_ms": 0, "target_power_w": 2.0},
        },
        controller,
        FakeZMeter(),
        FakeCamera(),
    )
    assert failed_z["status"] == "failed"
    assert controller.position["z"] == 0.010

    class FakeLaser:
        def __init__(self) -> None:
            self.wavelength_nm = None
            self.enabled = False

        def set_wavelength_nm(self, wavelength_nm: float) -> None:
            self.wavelength_nm = wavelength_nm

        def output(self, enabled: bool) -> None:
            self.enabled = enabled

    class FakeWavelengthMeter:
        def __init__(self) -> None:
            self.wavelength_nm = None

        def set_wavelength_nm(self, wavelength_nm: float) -> None:
            self.wavelength_nm = wavelength_nm

    laser = FakeLaser()
    pm = FakeWavelengthMeter()
    prepared = prepare_z_laser({"z_approach": {"wavelength_nm": 1550.0}}, laser, pm)
    assert prepared == {"wavelength_nm": 1550.0, "output": "on"}
    assert laser.enabled is True
    assert laser.wavelength_nm == pm.wavelength_nm == 1550.0
    laser.enabled = False
    prepare_measurement_laser(laser, pm, 1550.0)
    assert laser.enabled is True
    assert key_move("left", 0.001, False) == ("x", -0.001)
    assert key_move("r", 0.001, False) is None
    assert key_move("r", 0.001, True) == ("z", 0.001)
    assert decimal_text(0.001) == "0.001"
    assert decimal_text(0.0) == "0"
    assert dotnet_float("0,001") == 0.001
    assert parse_number("0,001") == 0.001
    laser_commands = []
    laser_state = {"wavelength": 1550.0, "power": 1.0, "enabled": False}
    osics = VisaLaser({"laser": {
        "visa_resource": "GPIB0::1::INSTR", "slot": 3, "power_mw": 1.0, "tuning_margin_ms": 0,
        "commands": {
            "set_wavelength_nm": "CH{slot}:L={wavelength_nm}",
            "get_wavelength_nm": "CH{slot}:L?",
            "set_power_unit_mw": "CH{slot}:MW",
            "set_power_mw": "CH{slot}:P={power_mw}",
            "get_power_mw": "CH{slot}:P?", "get_power_limit_mw": "CH{slot}:LIMIT?",
            "output_on": "CH{slot}:ENABLE", "output_off": "CH{slot}:DISABLE",
            "get_output": "CH{slot}:ENABLE?",
        },
    }})
    def laser_write(command: str) -> None:
        laser_commands.append(command)
        if ":L=" in command:
            laser_state["wavelength"] = float(command.split("=")[-1])
        elif ":P=" in command:
            laser_state["power"] = float(command.split("=")[-1])
        elif command.endswith(":ENABLE"):
            laser_state["enabled"] = True
        elif command.endswith(":DISABLE"):
            laser_state["enabled"] = False

    def laser_query(command: str) -> str:
        if command.endswith(":L?"):
            return f"CH3:L={laser_state['wavelength']}"
        if command.endswith(":P?"):
            return f"CH3:P={laser_state['power']}"
        if command.endswith(":LIMIT?"):
            return "CH3:LIMIT=10"
        return f"CH3:ENABLE={int(laser_state['enabled'])}"

    osics.write = laser_write
    osics.query = laser_query
    osics.set_wavelength_nm(1550.0)
    osics.output(True)
    assert laser_commands == ["CH3:L=1550.0", "CH3:MW", "CH3:P=1.0", "CH3:ENABLE"]
    assert response_number("CH1:P=1.25E-3") == 1.25e-3
    pm320 = VisaPowerMeter({"power_meter": {
        "visa_resource": "USB::PM320E", "channel": 2,
        "commands": {
            "set_wavelength_nm": ":WAVEL{channel}:VAL {wavelength_nm}",
            "get_wavelength_nm": ":WAVEL{channel}:VAL?",
            "read_power_w": ":POW{channel}:VAL?",
        },
    }})
    pm_commands = []
    pm320.write = pm_commands.append
    pm320.query = lambda command: "1550" if command.startswith(":WAVEL") else "1e-3"
    pm320.set_wavelength_nm(1550)
    assert pm_commands == [":WAVEL2:VAL 1550"]
    assert pm320.read_power_w() == 1e-3
    assert safe_limits((0.0, 10.0), 1) == (0.0, 10.0)
    assert MANUAL_STAGE_AXES == {"a": {"x": 1, "y": 2, "z": 3}, "b": {"x": 2, "y": 1, "z": 3}}
    assert manual_stage_config(
        {"manual_stages": {"b": {"axis_channels": {"x": 2, "y": 1, "z": 3}, "limits_mm": {"x": [-1.0, 1.0], "y": [-1.0, 1.0], "z": [-1.0, 1.0]}}}},
        "b",
    )["axis_channels"]["x"] == 2
    stage_b = bsc_from_config({"motion": {"serial_number": "test", "axis_channels": {"x": 2, "y": 1, "z": 3}, "axis_stage_settings": NANOMAX_DRV208_SETTINGS}})
    assert stage_b.stage_name[2] == "HS NanoMax 300 X Axis (DRV208)"
    assert stage_b.stage_name[1] == "HS NanoMax 300 Y Axis (DRV208)"
    batch_devices = [
        Device("a", 0, 0, 1, 0, "TE", 1500, 1501, 1),
        Device("b", 1, 0, 2, 0, "TE", 1500, 1501, 1),
        Device("c", 2, 0, 3, 0, "TE", 1500, 1501, 1),
    ]
    assert [d.device_id for d in select_batch_devices(batch_devices, "b", True)] == ["c"]
    built = build_real_config(
        {
            "laser": {"visa_resource": "TODO"},
            "power_meter": {"visa_resource": "TODO"},
            "camera": {"opencv_index": "TODO"},
            "motion": {"serial_number": "TODO"},
        },
        {
            "visa": [
                {"role": "laser", "resource": "GPIB0::1::INSTR"},
                {"role": "power_meter", "resource": "USB0::PM320::INSTR"},
            ],
            "cameras": [{"status": "ok", "index": 0}],
            "thorlabs_kinesis": [{"status": "ok", "serial": "70200000"}],
        },
    )
    assert built["laser"]["visa_resource"] == "GPIB0::1::INSTR"
    assert built["motion"]["serial_number"] == "70200000"
    errors, warnings = validate_hardware_config(built)
    assert "missing motion.z_travel_mm" in errors
    assert "motion.piezo_controller is not configured" in warnings

    motion = SafeMotion(z_chip_um=10, z_margin_um=5, z_travel_um=50)
    try:
        motion.move_z(14.99)
    except RuntimeError:
        pass
    else:
        raise AssertionError("unsafe z move was not blocked")

    limited_bsc = BSC203("test", limits_mm={1: (0.1, 3.9)})
    try:
        limited_bsc.move_to_mm(1, 4.0)
    except RuntimeError:
        pass
    else:
        raise AssertionError("out-of-range BSC move was not blocked")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        devices = root / "devices.csv"
        devices.write_text(
            "device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,"
            "lambda_start_nm,lambda_stop_nm,lambda_step_nm\n"
            "test_001,10,20,80,20,TE,1500,1501,0.5\n",
            encoding="utf-8",
        )
        run_dir = run(devices, root / "results")
        rows = list(csv.DictReader((run_dir / "spectra.csv").open(encoding="utf-8")))
        assert len(rows) == 3
        assert (run_dir / "motion_log.csv").exists()
        plan = plan_move(
            {
                "device_id": "test_001",
                "stage_position_mm": {"x": 0.01, "y": 0.02, "z": 0.03},
                "stage_positions_mm": {
                    "a": {"x": 0.01, "y": 0.02, "z": 0.03},
                    "b": {"x": 1.01, "y": 1.02, "z": 1.03},
                },
                "device_layout_um": {"input_gc_x": 10.0, "input_gc_y": 20.0, "output_gc_x": 80.0, "output_gc_y": 20.0},
            },
            Device("test_002", 110.0, 220.0, 180.0, 220.0, "TE", 1500.0, 1501.0, 0.5),
        )
        assert plan["target_stage_position_mm"]["x"] == 0.11
        assert plan["target_stage_position_mm"]["y"] == 0.22
        assert plan["target_stage_positions_mm"]["b"]["x"] == 1.11
        assert plan["target_stage_positions_mm"]["b"]["y"] == 1.22
        reference = root / "reference_latest.json"
        reference.write_text(
            json.dumps(
                {
                    "device_id": "test_001",
                    "stage_position_mm": {"x": 0.01, "y": 0.02, "z": 0.03},
                    "stage_positions_mm": {
                        "a": {"x": 0.01, "y": 0.02, "z": 0.03},
                        "b": {"x": 1.01, "y": 1.02, "z": 1.03},
                    },
                    "device_layout_um": {"input_gc_x": 10.0, "input_gc_y": 20.0, "output_gc_x": 80.0, "output_gc_y": 20.0},
                }
            ),
            encoding="utf-8",
        )
        move_log = move_to_device(
            {"motion": {"z_travel_mm": 1.0}, "startup": {"state_dir": str(root / "state")}},
            Device("test_002", 110.0, 220.0, 180.0, 220.0, "TE", 1500.0, 1501.0, 0.5),
            reference_path=reference,
            dry_run=True,
        )
        move_report = json.loads(move_log.read_text(encoding="utf-8"))
        assert move_report["z_retract_mm"] == 1.0

        bad = root / "bad_devices.csv"
        bad.write_text(
            "device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,"
            "lambda_start_nm,lambda_stop_nm,lambda_step_nm\n"
            "bad,10,20,80,20,TE,1501,1500,0.5\n",
            encoding="utf-8",
        )
        try:
            load_devices(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid wavelength range was not rejected")

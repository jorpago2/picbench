from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from labauto.camera import camera_backends
from labauto.thorlabs_bsc203 import find_kinesis_dir


def discover_visa(timeout_ms: int) -> list[dict[str, str]]:
    try:
        import pyvisa
    except ImportError:
        return [{"status": "missing pyvisa"}]

    try:
        rm = pyvisa.ResourceManager()
    except Exception as exc:
        return [{"status": f"VISA runtime not available: {exc}"}]
    records = []
    for resource in rm.list_resources():
        record = {"resource": resource, "status": "ok", "idn": "", "role": "unknown"}
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout_ms
            inst.read_termination = "\n"
            inst.write_termination = "\n"
            try:
                record["idn"] = inst.query("*IDN?").strip()
                record["role"] = classify_visa(record["idn"], resource)
            except Exception as exc:
                record["status"] = f"no *IDN? response: {exc}"
            finally:
                inst.close()
        except Exception as exc:
            record["status"] = f"open failed: {exc}"
        records.append(record)
    return records or [{"status": "no VISA resources found"}]


def classify_visa(idn: str, resource: str) -> str:
    text = f"{idn} {resource}".lower()
    if any(word in text for word in ("yenista", "exfo", "osics", "tunics", "t100")):
        return "laser"
    if "thorlabs" in text and any(word in text for word in ("pm", "power", "tlpm")):
        return "power_meter"
    if "gpib" in text:
        return "gpib_instrument"
    return "unknown"


def discover_cameras(max_index: int) -> list[dict[str, int | str]]:
    try:
        import cv2
    except ImportError:
        return [{"status": "missing opencv-python"}]
    if hasattr(cv2, "setLogLevel"):
        cv2.setLogLevel(0)

    records = []
    for index in range(max_index + 1):
        for backend in camera_backends(cv2):
            cap = cv2.VideoCapture(index, backend)
            try:
                if not cap.isOpened():
                    continue
                ok, _frame = cap.read()
                if not ok:
                    continue
                backend_name = backend_label(cv2, backend)
                records.append(
                    {
                        "index": index,
                        "status": "ok",
                        "backend": backend_name,
                        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    }
                )
                break
            finally:
                cap.release()
    return records or [{"status": "no cameras found"}]


def backend_label(cv2, backend: int) -> str:
    for name in ("CAP_DSHOW", "CAP_MSMF", "CAP_ANY"):
        if getattr(cv2, name, None) == backend:
            return name.replace("CAP_", "")
    return str(backend)


def discover_thorlabs(kinesis_dir: Path | None) -> list[dict[str, str]]:
    dll = find_kinesis_dll(kinesis_dir)
    if dll is None:
        return [{"status": "Kinesis DeviceManagerCLI DLL not found"}]

    try:
        import clr
    except ImportError:
        return [{"status": "missing pythonnet; install it on the measurement PC to query Kinesis serials"}]

    sys.path.append(str(dll.parent))
    try:
        clr.AddReference("Thorlabs.MotionControl.DeviceManagerCLI")
        from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI

        DeviceManagerCLI.BuildDeviceList()
        serials = [str(serial) for serial in DeviceManagerCLI.GetDeviceList()]
    except Exception as exc:
        return [{"status": f"Kinesis discovery failed: {exc}", "dll": str(dll)}]

    return [{"serial": serial, "status": "ok", "source": str(dll)} for serial in serials] or [
        {"status": "no Thorlabs Kinesis devices found", "source": str(dll)}
    ]


def find_kinesis_dll(kinesis_dir: Path | None) -> Path | None:
    try:
        return find_kinesis_dir(kinesis_dir) / "Thorlabs.MotionControl.DeviceManagerCLI.dll"
    except RuntimeError:
        return None


def discover_windows_pnp() -> list[dict[str, str]]:
    if not sys.platform.startswith("win"):
        return [{"status": "not Windows"}]

    command = r"""
Get-PnpDevice -PresentOnly |
  Where-Object { $_.FriendlyName -match 'Thorlabs|Kinesis|\bAPT\b|Yenista|EXFO|\bGPIB\b|\bVISA\b|PM320|USB Video|Camera' } |
  Select-Object Class,FriendlyName,InstanceId |
  ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return [{"status": f"PnP discovery failed: {exc}"}]

    if result.returncode != 0:
        return [{"status": result.stderr.strip() or "PnP discovery failed"}]
    if not result.stdout.strip():
        return [{"status": "no matching PnP devices found"}]

    data = json.loads(result.stdout)
    return data if isinstance(data, list) else [data]


def print_section(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover lab hardware without moving anything.")
    parser.add_argument("--skip-visa", action="store_true")
    parser.add_argument("--skip-cameras", action="store_true")
    parser.add_argument("--skip-thorlabs", action="store_true")
    parser.add_argument("--skip-pnp", action="store_true")
    parser.add_argument("--max-camera-index", type=int, default=5)
    parser.add_argument("--visa-timeout-ms", type=int, default=1000)
    parser.add_argument("--kinesis-dir", type=Path)
    parser.add_argument("--save", type=Path, help="write discovery JSON, e.g. config/hardware.discovered.json")
    args = parser.parse_args()

    report: dict[str, list[dict]] = {}
    if not args.skip_visa:
        report["visa"] = discover_visa(args.visa_timeout_ms)
    if not args.skip_cameras:
        report["cameras"] = discover_cameras(args.max_camera_index)
    if not args.skip_thorlabs:
        report["thorlabs_kinesis"] = discover_thorlabs(args.kinesis_dir)
    if not args.skip_pnp:
        report["windows_pnp"] = discover_windows_pnp()

    for title, rows in report.items():
        print_section(title, rows)

    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nsaved {args.save}")


if __name__ == "__main__":
    main()

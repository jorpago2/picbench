# Laboratory PC installation

PICBench is developed away from the laboratory computer. The target PC therefore requires the Python dependencies and vendor drivers described below.

## 1. Create the Python environment

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements-hardware.txt
```

If PowerShell blocks environment activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Install Windows drivers

- Thorlabs BSC203: Thorlabs Kinesis.
- Yenista/EXFO T100 through GPIB-USB: the GPIB adapter driver and a VISA runtime, normally NI-VISA or Keysight VISA.
- Thorlabs PM320E: Thorlabs software/driver and NI-VISA if the instrument is not exposed as a VISA resource.

## 3. Verify without moving hardware

```powershell
python -m scripts.caracterizacion_fotonica --self-test
python -m labauto.diagnostics --save .\config\hardware.discovered.json
python -m scripts.crear_config_real --discovered .\config\hardware.discovered.json --out .\config\hardware.real.json
python -m scripts.validar_config --config .\config\hardware.real.json
```

Diagnostics only enumerates resources. It does not move axes, home stages or enable the laser.

## 4. Preserve the discovery report

Keep `config/hardware.discovered.json`. `python -m scripts.crear_config_real` uses it to populate the BSC203, laser, power meter and camera resources when each match is unambiguous.

## 5. Test hardware incrementally

Review `config/hardware.real.json` and replace any remaining `TODO` values. Set `motion.z_travel_mm` to a physically verified safe travel height before moving between devices.

```powershell
python -m scripts.probar_hardware --config .\config\hardware.real.json identify
python -m scripts.probar_hardware --config .\config\hardware.real.json read-power
python -m scripts.probar_hardware --config .\config\hardware.real.json pm-wavelength --nm 1550
python -m scripts.probar_hardware --config .\config\hardware.real.json capture --out .\workspace\captures\frame.png
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-position --axis x
python -m scripts.inicializar_setup --config .\config\hardware.real.json --yes
python -m scripts.registrar_referencia --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id ring_001 --yes
python -m scripts.mover_a_dispositivo --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --dry-run
python -m scripts.alinear_xy --config .\config\hardware.real.json --device-id mzi_001 --span-um 10 --step-um 2 --yes
python -m scripts.medir_espectro --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --yes
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --start-after-reference --yes
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --resume .\workspace\results\batch_YYYYMMDD_HHMMSS --yes
```

Commands that move hardware or change laser state require explicit confirmation:

```powershell
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-home --axis x --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-move --axis x --to-mm 0.1 --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-wavelength --nm 1550 --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-output --on --yes
```

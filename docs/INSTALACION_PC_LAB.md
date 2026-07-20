# Instalacion en el PC del laboratorio

Este proyecto se esta desarrollando fuera del PC del laboratorio. En el PC del laboratorio hay que instalar dependencias Python y drivers de fabricante.

## 1. Crear entorno Python

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements-hardware.txt
```

Si PowerShell bloquea la activacion:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Instalar drivers Windows

- Thorlabs BSC203: Thorlabs Kinesis.
- Yenista/EXFO T100 por GPIB-USB: driver del adaptador GPIB + runtime VISA, normalmente NI-VISA o Keysight VISA.
- Thorlabs PM320E: software/driver Thorlabs y NI-VISA si no aparece como instrumento VISA.

## 3. Verificar sin mover hardware

```powershell
python -m scripts.caracterizacion_fotonica --self-test
python -m labauto.diagnostics --save .\config\hardware.discovered.json
python -m scripts.crear_config_real --discovered .\config\hardware.discovered.json --out .\config\hardware.real.json
python -m scripts.validar_config --config .\config\hardware.real.json
```

El diagnostico solo enumera recursos. No mueve ejes, no hace homing y no enciende el laser.

## 4. Guardar resultado

Conservar `config/hardware.discovered.json`. `python -m scripts.crear_config_real` lo usa para rellenar los recursos reales del BSC203, laser, power meter y camara cuando no hay ambiguedad.

## 5. Probar hardware por partes

Revisar `config/hardware.real.json`; si quedan entradas `TODO`, rellenarlas a mano. Luego:

Antes de mover entre dispositivos, rellenar `motion.z_travel_mm` con una altura de viaje segura medida tras homing.

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

Movimientos solo con confirmacion explicita:

```powershell
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-home --axis x --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-move --axis x --to-mm 0.1 --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-wavelength --nm 1550 --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-output --on --yes
```


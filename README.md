# PICBench

Desktop automation software for photonic integrated circuit alignment and characterization.

PICBench is intended for transparent, reproducible laboratory automation. The repository contains the complete Python source, simulated workflows and documented CSV/configuration formats. Real hardware configuration, serial numbers, calibration state and measurement results are deliberately excluded from version control.

Released under the [MIT License](LICENSE).

## Windows release

Download `PICBench.exe` and `PICBench.exe.sha256` from the GitHub Releases page. It is a portable application; place it in a writable folder and run it directly. Thorlabs Kinesis, a VISA implementation and the camera drivers must still be installed on the laboratory PC. Releases are not code-signed yet, so Windows SmartScreen may show a warning; verify the SHA-256 file before running the executable.

To build the executable locally:

```powershell
.\scripts\build_windows.ps1
```

Pushing a tag such as `v0.1.0` runs `.github/workflows/release.yml`, verifies the software, builds the Windows executable and attaches it to a GitHub Release.

Primer prototipo del plan en `docs/plan_caracterizacion_fotonica.md`.

Estamos desarrollando fuera del PC del laboratorio. Para instalarlo alli, seguir `docs/INSTALACION_PC_LAB.md`.

```powershell
.\PICBench.bat
python -m labauto.ui
python -m scripts.caracterizacion_fotonica --self-test
python -m scripts.caracterizacion_fotonica --validate-devices .\examples\devices.example.csv
python -m scripts.caracterizacion_fotonica --simulate --devices .\examples\devices.example.csv
python -m labauto.diagnostics --save .\config\hardware.discovered.json
python -m scripts.crear_config_real --discovered .\config\hardware.discovered.json --out .\config\hardware.real.json
python -m scripts.validar_config --config .\config\hardware.real.json
python -m scripts.probar_hardware --config .\examples\hardware.example.json identify
python -m scripts.inicializar_setup --config .\config\hardware.real.json --yes
python -m scripts.registrar_referencia --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id ring_001 --yes
python -m scripts.mover_a_dispositivo --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --dry-run
python -m scripts.aproximar_z --config .\config\hardware.real.json --yes
python -m scripts.alinear_xy --config .\config\hardware.real.json --device-id mzi_001 --span-um 10 --step-um 2 --yes
python -m scripts.medir_espectro --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --yes
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --start-after-reference --yes
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --resume .\workspace\results\batch_YYYYMMDD_HHMMSS --yes
```

Genera `workspace/results/<timestamp>/spectra.csv`, `motion_log.csv` y `metadata.json`.
El diagnostico solo enumera recursos; no mueve ejes ni hace homing.
El formato de entrada esta definido en `docs/FORMATO_CSV_DISPOSITIVOS.md`.

Estructura:

- `PICBench.bat`: lanzador de doble click en Windows.
- `config/`: configuracion local y descubrimiento de hardware; los JSON reales no se publican.
- `workspace/`: CSV activo, calibraciones, capturas y resultados de medida.
- `release/`: ejecutable local y checksum generados; no se versionan.
- `assets/picbench.ico`: icono multirresolucion para la ventana y el futuro ejecutable.
- `labauto/ui.py`: interfaz grafica local para ejecutar flujos y ver resultados.
- `scripts/`: comandos CLI, ejecutables con `python -m scripts.<nombre>`.
- `docs/`: instalacion, formato CSV y plan de caracterizacion.
- `examples/`: `hardware.example.json` y `devices.example.csv`.
- `labauto/devices.py`: CSV de dispositivos y longitudes de onda.
- `labauto/motion.py`: movimiento seguro.
- `labauto/thorlabs_bsc203.py`: controlador BSC203 via Kinesis.
- `labauto/visa_devices.py`: laser y power meter via VISA.
- `labauto/camera.py`: captura con OpenCV.
- `labauto/simulation.py`: power meter simulado.
- `labauto/runner.py`: ejecucion de medidas.
- `labauto/diagnostics.py`: descubrimiento VISA, Thorlabs, camaras y PnP.

El lote baja `z` automaticamente solo si `z_approach.enabled` esta activo en la config.

Calibracion visual guiada:

1. Conectar Stage A o B desde `Devices` e iniciar la camara.
2. Abrir `Setup` -> `Vision calibration`.
3. Dibujar la ROI y marcar dos puntos de la superficie del chip.
4. Registrar `Far` y ejecutar `Map XY`; el stage mueve X/Y por separado, mide el desplazamiento de la punta y vuelve al origen.
5. Registrar `Near` y `Minimum safe`, moviendo Z desde el panel independiente del stage.
6. Guardar y repetir con el otro stage.

Se crea `workspace/state/vision_calibration.json` junto con las imagenes de referencia y las matrices `stage_um_to_pixel` / `pixel_to_stage_um`. El perfil queda ligado a la camara, resolucion y numero de serie de cada stage. Durante la aproximacion automatica, perder la fibra provoca fallo y retraccion; alcanzar `Minimum safe` detiene el descenso correctamente. Guardar la calibracion no activa `z_approach.enabled`.

Mapa visual de gratings:

1. Cargar el CSV de dispositivos e iniciar la camara.
2. Abrir `Live` -> `Map gratings`.
3. Para cada dispositivo, hacer clic en el grating de entrada y despues en el de salida.
4. Usar `Freeze`, zoom con rueda y paneo con el boton central cuando sea necesario.
5. Guardar el progreso; se puede continuar posteriormente.

El mapa se guarda en `workspace/state/grating_map.json` con coordenadas normalizadas y solo se muestra si coinciden la camara y la resolucion. En Live, verde identifica la entrada y magenta la salida.

Posicionamiento visual de fibras:

1. Calibrar XY para Stage A y Stage B, guardar el mapa de gratings y conectar ambos stages en `Devices`.
2. Seleccionar un dispositivo en `Operation area` y pulsar `Position fibers`.
3. Revisar las puntas detectadas, confianza, desplazamientos y posiciones destino.
4. Confirmar el movimiento. PICBench lleva ambos Z a `motion.z_travel_mm` antes de mover cualquier XY y deja las fibras a esa altura.
5. Tras cada movimiento espera una imagen nueva, vuelve a detectar ambas fibras y corrige XY hasta alcanzar `grating_positioning.tolerance_um` o agotar `max_corrections`.

El movimiento se bloquea si la camara, resolucion o numeros de serie no coinciden con la calibracion; si falta homing, hay un limite activo o el destino queda fuera de los limites configurados; o si la posicion cambia despues de la previsualizacion. El lazo visual tambien se detiene si pierde confianza, no recibe una imagen reciente, una correccion supera `max_correction_um` o el error aumenta mas de un 25 %. Z no se mueve durante las correcciones.

Interfaz grafica:

```powershell
.\PICBench.bat
python -m labauto.ui
```

La interfaz sigue el flujo `Setup` -> `Devices` -> `Live` -> `Results`: primero se prepara la sesion, despues se conectan y prueban los equipos, se ejecuta la medida y finalmente se revisan los espectros. `Devices` reúne Stage A, Stage B, laser, power meter y camara en un dashboard compacto. Cada equipo mantiene su conexion y usa su propio worker para no bloquear los otros paneles.

Para abrir con doble click en Windows, usar `PICBench.bat`.

Pruebas reales por partes:

```powershell
python -m scripts.probar_hardware --config .\config\hardware.real.json identify
python -m scripts.probar_hardware --config .\config\hardware.real.json read-power
python -m scripts.probar_hardware --config .\config\hardware.real.json pm-wavelength --nm 1550
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-wavelength --nm 1550 --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json laser-output --on --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json capture --out .\workspace\captures\frame.png
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-position --axis x
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-home --axis x --yes
python -m scripts.probar_hardware --config .\config\hardware.real.json bsc-move --axis x --to-mm 0.1 --yes
```

`laser-wavelength`, `laser-output`, `home` y `move` exigen `--yes`.

Inicializacion segura:

```powershell
python -m scripts.inicializar_setup --config .\config\hardware.real.json --yes
```

Pasos:

1. Carga `config/hardware.real.json`.
2. Identifica laser y power meter si estan configurados.
3. Manda apagar salida del laser si `startup.laser_output_off_on_start` es `true`.
4. Conecta al BSC203.
5. Lee posiciones iniciales de `x/y/z`.
6. Hace homing automatico en `startup.home_order`, por defecto `z, x, y`, usando la direccion, final de carrera y `Zero Offset` del perfil Kinesis activo. No mueve despues al centro.
7. Guarda `workspace/state/startup_<timestamp>.json` y `workspace/state/startup_latest.json`.

Si el comando de apagado del laser no esta configurado, la inicializacion se detiene antes del homing. Para apagar el laser manualmente y saltar ese comando, usar `"laser_output_off_on_start": false` en `config/hardware.real.json`.

Los limites iniciales `0-4 mm` coinciden con el recorrido nominal del perfil NanoMax. Se pueden estrechar en `Setup` para dejar margen mecanico; los movimientos fuera de esos intervalos quedan bloqueados.

Configurar tambien `Max velocity mm/s` y `Acceleration mm/s2` tras una prueba con la fibra lejos del chip; cuando ambos valores estan definidos PICBench los aplica a los canales BSC203. `Emergency stop` intenta parar inmediatamente X/Y/Z y apagar el laser, pero no sustituye un paro fisico que corte la energia del controlador.

Alineamiento manual del primer dispositivo:

```powershell
python -m scripts.registrar_referencia --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id ring_001 --yes
```

Teclas:

- Flechas o `WASD`: mover `x/y`.
- `1/2/3/4`: paso de `0.5/1/5/10 um`.
- `Enter`: guardar referencia en `workspace/state/reference_latest.json`.
- `q` o `Esc`: cancelar sin guardar.

Para permitir jog en `z`:

```powershell
python -m scripts.registrar_referencia --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id ring_001 --enable-z --yes
```

Con `--enable-z`, `PageUp/PageDown` o `R/F` mueven `z`.

Movimiento al siguiente dispositivo:

```powershell
python -m scripts.mover_a_dispositivo --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --dry-run
python -m scripts.mover_a_dispositivo --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --yes
```

Pasos:

1. Carga `workspace/state/reference_latest.json`.
2. Busca el `device_id` destino en el CSV.
3. Calcula `dx/dy` para el grating de entrada (Stage A) y de salida (Stage B).
4. Convierte `um` a `mm`.
5. Calcula las posiciones destino de ambos stages.
6. Si no es `--dry-run`, sube ambos `z` a `motion.z_travel_mm`.
7. Mueve los `x/y` de ambos stages.
8. Deja `z` en altura de viaje; no baja automaticamente.
9. Guarda `workspace/state/move_<device_id>_<timestamp>.json` y `workspace/state/move_latest.json`.

Aproximacion automatica de `z`:

```powershell
python -m scripts.aproximar_z --config .\config\hardware.real.json --yes
```

Pasos:

1. Lee la posicion actual de `z`.
2. Si `z_approach.laser_output_on` es `true`, ajusta longitud de onda y enciende la salida del laser.
3. Toma una imagen base de la camara y una potencia base del PM320E.
4. Baja/sube `z` en pasos de `z_approach.step_um` hacia `z_approach.stop_mm`.
5. Compensa el desplazamiento lateral de la fibra con `dx = dz * tan(fiber_angle_deg) * angle_sign`.
6. En cada paso lee potencia y cambio visual en la ROI de camara.
7. Para si llega a `z_approach.target_power_w` o si `visual_change_stop` detecta sombra/cambio suficiente.
8. Si llega al limite sin senal, vuelve a la posicion inicial si `retract_on_failure` es `true` y falla.
9. Si falla y `laser_output_off_on_failure` es `true`, apaga la salida del laser.
10. Guarda `workspace/state/z_approach_<timestamp>.json` y `workspace/state/z_approach_latest.json`.

Calibracion de `z_approach` en el PC del laboratorio:

1. Mantener `"z_approach.enabled": false` hasta terminar esta calibracion.
2. Hacer homing e ir a una posicion segura con `z = motion.z_travel_mm`.
3. Capturar imagen de camara:

```powershell
python -m scripts.probar_hardware --config .\config\hardware.real.json capture --out .\workspace\captures\z_roi.png
```

4. Ajustar `z_approach.roi` para que incluya fibra/sombra y la zona cercana al grating.
5. Fijar `z_approach.stop_mm` como el limite minimo permitido de `z`; debe quedar por encima de contacto.
6. Usar `step_um` grande al principio, por ejemplo `5.0`, y bajarlo a `2.0` o `1.0` cuando sea estable.
7. Poner `wavelength_nm` para probar `aproximar_z.py` fuera del lote.
8. Ejecutar `aproximar_z.py` desde una altura segura y revisar `workspace/state/z_approach_latest.json`.
9. Si `x` se aleja de la senal al bajar `z`, cambiar `angle_sign` entre `1.0` y `-1.0`.
10. Ajustar `target_power_w` con una potencia claramente por encima del ruido del PM320E.
11. Ajustar `visual_change_stop` mirando los valores `visual_change` del reporte.
12. Activar `"z_approach.enabled": true` solo cuando pare de forma repetible.

Alineamiento local `x/y`:

```powershell
python -m scripts.alinear_xy --config .\config\hardware.real.json --device-id mzi_001 --span-um 10 --step-um 2 --yes
```

Pasos:

1. Lee posicion actual `x/y/z`.
2. Hace un barrido grueso en `x/y` alrededor de la posicion actual.
3. Hace un barrido fino alrededor del mejor punto grueso.
4. Lee potencia del PM320E en cada punto.
5. Mueve `x/y` al maximo.
6. No mueve `z`.
7. Guarda `workspace/state/alignment_<device_id>_<timestamp>.json` y `workspace/state/alignment_latest.json`.

Durante el barrido mantiene abiertas las conexiones al BSC203 y al PM320E; no abre/cierra por cada punto.

Medida espectral:

```powershell
python -m scripts.medir_espectro --config .\config\hardware.real.json --devices .\workspace\devices.csv --device-id mzi_001 --yes
```

Pasos:

1. Lee el rango espectral del CSV.
2. Abre conexiones persistentes al laser, PM320E y BSC203.
3. Para cada longitud de onda:
   - configura y verifica el canal del PM320E,
   - sintoniza laser,
   - espera `settle-ms`,
   - lee potencia,
   - lee posicion actual.
4. Guarda `workspace/results/spectrum_<device_id>_<timestamp>/spectrum.csv`.
5. Guarda `metadata.json`.

Medida de lote semiautomatica:

```powershell
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --start-after-reference --yes
```

Pasos por dispositivo:

1. Calcula offset desde `workspace/state/reference_latest.json`.
2. Sube los dos `z` a `motion.z_travel_mm`.
3. Mueve Stage A al grating de entrada y Stage B al de salida.
4. Enciende el laser y aproxima ambos stages si `z_approach.enabled` es `true`; si no, pausa para bajarlos manualmente.
5. Alinea secuencialmente `x/y` de Stage A y Stage B.
6. Pausa para confirmar medida.
7. Mide espectro.
8. Guarda resultados en `workspace/results/batch_<timestamp>/`.

Durante todo el lote mantiene abiertas las conexiones a ambos BSC203, laser y PM320E.

Reanudar lote:

```powershell
python -m scripts.medir_lote --config .\config\hardware.real.json --devices .\workspace\devices.csv --resume .\workspace\results\batch_YYYYMMDD_HHMMSS --yes
```

`batch.json` marca cada dispositivo como `pending`, `moving`, `moved`, `aligning`, `aligned`, `measuring`, `measured` o `failed`. Al reanudar salta los `measured` y continua con el resto.

Equipo previsto:

- Stage: Thorlabs MAX381/M, 3 ejes stepper.
- Controlador stepper: Thorlabs BSC203, 3 canales.
- Piezos: integrados, closed-loop.
- Laser: Yenista/EXFO OSICS T100 por GPIB-USB.
- En `Devices`, el Yenista permite seleccionar el slot `1-8` del mainframe y la potencia de salida en mW. El valor inicial es `1 mW`; PICBench selecciona la unidad mW y aplica esa potencia antes de habilitar la salida.
- Power meter: Thorlabs PM320E, canal 1 o 2 configurable.
- Camara: USB generica, modelo pendiente.

Pendiente antes de mover hardware real:

- Confirmar controlador piezo y numeros de serie.
- Ejecutar `python -m labauto.diagnostics --save .\config\hardware.discovered.json` en el PC del laboratorio.
- Registrar de nuevo la referencia para guardar las posiciones de Stage A y Stage B.

Dependencias opcionales para diagnostico:

- VISA: `pyvisa` + runtime VISA instalado.
- Thorlabs BSC203: Kinesis instalado + `pythonnet`.
- Camara: `opencv-python`.

Instalacion Python:

```powershell
python -m pip install -r .\requirements-hardware.txt
```

Drivers Windows que no instala `pip`:

- BSC203: Thorlabs Kinesis.
- Laser T100 por GPIB-USB: driver del adaptador GPIB + runtime VISA, normalmente NI-VISA/Keysight VISA.
- PM320E: software/driver Thorlabs y NI-VISA si no aparece como instrumento VISA.


# Formato CSV de dispositivos

El programa no lee el GDS directamente. Recibe una tabla CSV exportada desde el flujo de layout/GDS.

Cada fila representa una estructura optica a medir.

## Columnas obligatorias

| Columna | Tipo | Unidad | Descripcion |
|---|---:|---:|---|
| `device_id` | texto | - | Identificador unico de la estructura. |
| `input_gc_x` | numero | um | Coordenada X del grating coupler de entrada en coordenadas de layout/chip. |
| `input_gc_y` | numero | um | Coordenada Y del grating coupler de entrada en coordenadas de layout/chip. |
| `output_gc_x` | numero | um | Coordenada X del grating coupler de salida. |
| `output_gc_y` | numero | um | Coordenada Y del grating coupler de salida. |
| `polarization` | texto | - | Polarizacion esperada, por ejemplo `TE` o `TM`. |
| `lambda_start_nm` | numero | nm | Longitud de onda inicial del barrido. |
| `lambda_stop_nm` | numero | nm | Longitud de onda final del barrido. |
| `lambda_step_nm` | numero | nm | Paso del barrido. Debe ser mayor que cero. |

## Reglas

- Separador: coma.
- Codificacion: UTF-8.
- Cabecera obligatoria en la primera linea.
- `device_id` no puede estar vacio ni repetirse.
- Las coordenadas son las del layout/chip, no posiciones absolutas del stage.
- `lambda_stop_nm` debe ser mayor o igual que `lambda_start_nm`.
- `lambda_step_nm` debe ser mayor que cero.
- Columnas extra estan permitidas y se ignoran por ahora.

## Ejemplo

```csv
device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,lambda_start_nm,lambda_stop_nm,lambda_step_nm
ring_001,1200.0,500.0,1270.0,500.0,TE,1500,1600,0.02
mzi_001,1500.0,500.0,1570.0,500.0,TE,1500,1600,0.02
```

## Validacion

```powershell
python -m scripts.caracterizacion_fotonica --validate-devices .\examples\devices.example.csv
```


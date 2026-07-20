# Device CSV format

PICBench does not read the GDS directly. It receives a CSV table exported from the layout/GDS workflow.

Each row represents one optical structure to be measured.

## Required columns

| Column | Type | Unit | Description |
|---|---:|---:|---|
| `device_id` | text | - | Unique identifier for the structure. |
| `input_gc_x` | number | um | X coordinate of the input grating coupler in layout/chip coordinates. |
| `input_gc_y` | number | um | Y coordinate of the input grating coupler in layout/chip coordinates. |
| `output_gc_x` | number | um | X coordinate of the output grating coupler. |
| `output_gc_y` | number | um | Y coordinate of the output grating coupler. |
| `polarization` | text | - | Expected polarization, for example `TE` or `TM`. |
| `lambda_start_nm` | number | nm | Start wavelength of the sweep. |
| `lambda_stop_nm` | number | nm | Stop wavelength of the sweep. |
| `lambda_step_nm` | number | nm | Sweep step. It must be greater than zero. |

## Rules

- Delimiter: comma.
- Encoding: UTF-8.
- The first row must contain the header.
- `device_id` must not be empty or duplicated.
- Coordinates refer to the layout/chip, not to absolute stage positions.
- `lambda_stop_nm` must be greater than or equal to `lambda_start_nm`.
- `lambda_step_nm` must be greater than zero.
- Additional columns are allowed and currently ignored.

## Example

```csv
device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,lambda_start_nm,lambda_stop_nm,lambda_step_nm
ring_001,1200.0,500.0,1270.0,500.0,TE,1500,1600,0.02
mzi_001,1500.0,500.0,1570.0,500.0,TE,1500,1600,0.02
```

## Validation

```powershell
python -m scripts.caracterizacion_fotonica --validate-devices .\examples\devices.example.csv
```

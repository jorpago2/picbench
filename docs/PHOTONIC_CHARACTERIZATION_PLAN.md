# Automated photonic device characterization plan

## Objective

Develop a Python system that automatically measures spectra from grating-coupled photonic integrated devices using:

- Thorlabs motors and piezoelectric actuators for fiber positioning;
- a top-view camera for observing the chip and fibers;
- Python-controlled tunable lasers and optical power meters;
- optical alignment and spectral acquisition routines.

The primary design requirement is preventing mechanical damage, especially from excessive movement along `z`.

## General strategy

The system should be introduced incrementally rather than starting as a fully autonomous platform:

1. Manually align the first device.
2. Use the GDS or a table exported from it to obtain offsets between devices.
3. Move automatically between structures.
4. Realign in `x/y` using small scans and local optimization.
5. Measure each spectrum.
6. Store images, positions, spectra and state information.
7. Automate vision and `z` only after sufficient calibration and validation.

## Proposed architecture

```text
layout/
  Read GDS data, labels, ports, grating couplers and devices.

motion/
  Control motors, piezos, limits, homing and safe movements.

vision/
  Capture images and detect fiducials, fibers, shadows and grating couplers.

alignment/
  Run coarse alignment, x/y scans, fine optimization and safety checks.

instruments/
  Control the laser, power meter, spectral sweeps and references.

runner/
  Execute the device queue, measure, save results and resume interrupted runs.
```

PICBench now implements these responsibilities as modules under `labauto/` and user-facing commands under `scripts/`.

## Recommended input data

Although direct GDS parsing is possible, a measurement table exported by the layout workflow is easier to validate:

```csv
device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,lambda_start_nm,lambda_stop_nm,lambda_step_nm
ring_001,1200.0,500.0,1270.0,500.0,TE,1500,1600,0.02
mzi_001,1500.0,500.0,1570.0,500.0,TE,1500,1600,0.02
```

The GDS should contain labels or follow a clear convention for identifying:

- the device;
- input and output grating couplers;
- expected polarization;
- expected spectral range.

Inferring this information from unlabeled geometry is possible but more fragile. The current CSV contract is defined in [DEVICE_CSV_FORMAT.md](DEVICE_CSV_FORMAT.md).

## Mapping layout coordinates to the physical chip

PICBench must convert layout coordinates into physical stage coordinates.

Minimum calibration flow:

1. Select or detect several visible fiducials.
2. Obtain their known layout coordinates.
3. Measure their image or stage coordinates.
4. Fit an affine transform:

```text
[x_stage, y_stage] = A * [x_layout, y_layout] + b
```

Three points are sufficient for a basic affine transform. Additional points improve fitting and expose outliers or incorrect correspondence.

## Z-axis safety

This is the critical part of the system. Free height searches based only on optical power are unsafe.

### Primary rule

`z` must remain inside a calibrated safe window:

```text
z_min(x, y) = z_chip(x, y) + safety_margin
```

The software must never move below `z_min`.

### Chip plane

Measure at least three chip points and fit a plane:

```text
z_chip(x, y) = ax + by + c
```

Then define:

```text
z_safe(x, y) = z_chip(x, y) + safety_margin
```

The safety margin must be selected experimentally and conservatively.

### Safe movement sequence

For every long translation:

1. Retract both fibers to the verified travel height.
2. Move in `x/y`.
3. Approach slowly in `z`, stopping within the permitted window.
4. Perform fine optical alignment inside that window.

Large lateral movements must never occur close to the chip.

### Minimum interlocks

- software `z` limits;
- hardware limits when supported by the controller;
- low vertical approach velocity;
- a small maximum `z` step;
- an accessible emergency-stop control;
- automatic retraction if the camera loses the fiber or expected region;
- automatic retraction when visual analysis indicates danger;
- a record of every movement.

## Camera-based proximity estimation

A top-view camera can estimate fiber height from the relative positions of the fiber and its shadow under fixed lateral illumination:

```text
fiber-shadow separation in pixels -> approximate height above the chip
```

The fiber and shadow generally converge as the fiber approaches the chip. This relationship can be calibrated from images acquired at known heights.

Vision should operate as an interlock:

```text
far       -> continue approach
working   -> allow optical alignment
danger    -> stop and retract
uncertain -> stop and retract
```

Vision must not be the only safety sensor until repeated approaches have been validated.

## Classical vision before neural networks

Start with OpenCV techniques:

- grayscale conversion;
- filtering and normalization;
- edge detection;
- adaptive thresholding;
- Hough line detection;
- contrast-based segmentation;
- fiber tracking between frames.

Minimum output:

```text
image -> fiber axis, shadow axis, pixel separation, confidence
```

A neural network is unnecessary if the classical method is repeatable over the intended operating conditions.

## Dataset from the first day

Store enough information to support later model development:

```text
timestamp
image
x_stage, y_stage, z_stage
power
wavelength
device_id
manual_state: far / working / danger / uncertain
fiber_shadow_separation_px
comments
```

Real setup data are much more useful than generic images for training a future model.

## Possible neural-network tasks

If classical vision is not sufficiently robust:

### Classification

Input: image or region of interest.

Output:

```text
safe / working / danger / uncertain
```

This is the easiest task to label.

### Object detection

Detect bounding boxes for:

- fiber;
- shadow;
- grating coupler;
- fiducials.

### Segmentation

Generate pixel-level masks for the fiber, shadow, chip and grating coupler. This can be more precise but requires more annotation.

### Regression

Directly predicting `estimated_z_height` is not the recommended first approach because a wrong estimate can create an unsafe command.

### AI safety rule

A neural network must not command a downward movement. It may only block or permit motion that is already constrained by independently verified limits.

Low confidence must result in:

```text
stop -> retract -> request intervention
```

## Optical alignment

### Minimum workflow

1. Move to the device using its layout offset.
2. Perform a small `x/y` scan.
3. Locate the maximum optical power.
4. Refine around the maximum.
5. Measure the spectrum.

### X/Y scan

```text
5x5 or 7x7 grid
initial step: several micrometres
measure power at every point
move to the maximum
repeat with a smaller step
```

Simple coordinate search, hill climbing or bounded Nelder-Mead are sufficient. Complex optimizers should only be introduced after a measured need.

## Spectral acquisition

Recommended sequence:

1. Configure the laser.
2. Configure the power meter.
3. Measure dark power when applicable.
4. Measure a reference when applicable.
5. Sweep wavelength.
6. Save raw power and metadata.
7. Calculate corrected transmission.

Always retain raw measurements alongside processed data.

Example schema:

```csv
device_id,wavelength_nm,power_dbm,power_w,x,y,z,input_fiber_id,output_fiber_id,timestamp
```

## Implementation phases

### Phase 0: assisted manual control

- Control instruments from Python.
- Capture camera frames.
- Measure one spectrum manually.
- Store complete metadata.

Expected result: a manual measurement is reproducible and traceable.

### Phase 1: automatic acquisition from the initial position

- The user aligns the first device.
- PICBench sweeps the laser and stores the spectrum.
- `z` remains manual except for safe retraction.

Expected result: reliable spectra from one device.

### Phase 2: device queue using layout offsets

- Read the table exported from the GDS flow.
- Move in `x/y` using relative offsets.
- Retract before every long movement.
- Run local `x/y` alignment and measure.

Expected result: automated measurement of a row or matrix of devices.

### Phase 3: chip plane and Z limits

- Measure several chip points.
- Fit `z_chip(x, y)`.
- Define the safety margin.
- Block any movement that crosses `z_min`.
- Record blocked commands.

Expected result: software cannot move below the permitted height.

### Phase 4: vision interlock

- Fix the illumination geometry.
- Detect the fiber and shadow with OpenCV.
- Calibrate pixel separation against height.
- Stop and retract on danger or low confidence.

Expected result: a second safety layer independent of optical power.

### Phase 5: neural recognition

- Label images from the real setup.
- Train and validate a classifier or detector.
- Integrate it only as an interlock.

Expected result: more robust visual-state detection when classical vision is insufficient.

### Phase 6: supervised chip automation

- Detect fiducials and fit the layout-to-stage transform.
- Visit devices and realign in `x/y`.
- Adjust `z` only inside the safe window.
- Measure spectra and resume interrupted runs.

Expected result: robust semiautomatic characterization of complete chips.

## Recommended tests

### Without a chip

- Verify movement limits and emergency stop.
- Verify that long movements retract first.
- Simulate dangerous target positions.

### With a sacrificial sample

- Calibrate the chip plane.
- Test slow approaches.
- Record images at known heights.
- Validate fiber-shadow detection.

### With the real chip

- Begin with manual `z`.
- Automate only `x/y` and spectral acquisition.
- Enable visual interlocks.
- Introduce small automatic `z` corrections last.

## Main risks

| Risk | Mitigation |
|---|---|
| Fiber-chip collision | `z` limits, chip plane, travel height and visual interlock |
| Loss of alignment | Local `x/y` scan, retries and logs |
| Incorrect layout interpretation | Clear labels, exported table and fiducials |
| Unstable vision | Fixed illumination, calibration and confidence threshold |
| Incorrect neural prediction | Use only to block or warn, never to command descent |
| Damage caused by software error | Hardware limits, low speed and physical emergency stop |

## Candidate Python libraries

- `opencv-python`: classical vision, filtering, edges and tracking;
- `numpy`, `scipy`: geometry, optimization and numerical processing;
- `pandas`: device and result tables when its added weight is justified;
- `gdsfactory` or the KLayout API: GDS data export;
- Thorlabs Kinesis through `pythonnet`: BSC203 control;
- `pyvisa`: VISA instrument control;
- `pytorch` or `ultralytics`: optional future vision models.

Useful references:

- OpenCV: <https://opencv-opencv.mintlify.app/>
- PyTorch transfer learning: <https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html>
- Ultralytics YOLO: <https://docs.ultralytics.com/>
- gdsfactory: <https://gdsfactory.github.io/gdsfactory/>

## Recommended minimum implementation

Start with:

```text
GDS/CSV -> safe x/y movement -> local x/y scan -> spectrum -> complete logging
```

In parallel, collect:

```text
images + known z + manual label
```

This provides useful automation early while building the dataset required for reliable vision.

## Criteria for automatic Z

Enable automatic `z` only after all of the following are true:

- the chip plane is calibrated and repeatable;
- software limits have been tested;
- hardware limits or equivalent mitigation are available;
- the travel height has been physically validated;
- the visual proximity detector works as an interlock;
- repeated trials with a sacrificial sample have succeeded;
- logs are sufficient to audit failures.

Until then, `z` must remain manual, semiautomatic or restricted to a small verified window.

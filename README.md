# CANary

CANary currently contains only a synthetic automotive CAN data generator.
Requires Python 3.12 or newer; no third-party dependencies are needed.

Run from the repository root:

```sh
python -m unittest discover -v
python -m simulator.generate
```

The generator overwrites `datasets/synthetic/can_log.csv` and
`datasets/synthetic/speed_reference.csv`. Optional settings:

```sh
python -m simulator.generate --speed-scale 0.02 --seed 42 --output-dir datasets/synthetic
```

The default drive has 6,000 samples at 100 Hz over [0, 60) seconds. A scripted
pedal schedule drives a simple longitudinal model with drag and braking.
Engine RPM follows speed and throttle with a lag, assuming a simplified fixed
gear. This is a plausible synthetic exercise, not a calibrated vehicle model.

Six standard 11-bit CAN IDs each emit an 8-byte frame per sample (36,000 frames).
Timestamps are seconds since drive start; frames in a sample share a timestamp
and do not model bus arbitration or transmission delay. IDs use `0x1A4` notation
and payloads use eight space-separated uppercase hexadecimal bytes.
Three IDs carry physical signals, with random spare bytes; three unrelated IDs
carry random data and a rolling counter. Seed 42 makes output reproducible.
The reference contains unquantized simulated speed rounded to six decimals,
aligned to the same sample times, without sensor noise or delay.

## Source layout and ground truth

- `simulator/drive.py`: physical samples and pedal schedule.
- `simulator/ground_truth.py`: generator-only layout and unsigned field codec.
- `simulator/generate.py`: CAN frames, CSV writing, and command-line entry point.
- `tests/test_simulator.py`: standard-library unit and output tests.

Ground truth is deliberately separate from observation CSVs. Future discovery
code must read the CSVs without importing generator ground truth. Changing the
scale requires retaining that generation setting separately; observations do
not contain layout metadata.

Speed uses bytes 2–3 (zero-based) of ID `0x1A4`, unsigned 16-bit little-endian,
with `physical = raw * scale + offset`. Default scale is 0.01 km/h and offset
is zero, allowing 0–655.35 km/h. Encoding rounds to the nearest raw integer
(ties to even); decoding differs by at most half a scale unit. Out-of-range
values and invalid scales raise errors rather than wrap or silently saturate.
The field codec also supports nonzero offsets, covered by tests.

Accelerator is byte 5 of `0x245` at 0.5 percent per unit; brake is bit 2 of
byte 1 on that ID. RPM occupies bytes 0–1 of `0x316` at 1 RPM per unit.
All multibyte fields are little-endian. No discovery, correlation, DBC, AI,
or user interface is implemented.

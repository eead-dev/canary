# comma2k19 blind real-data experiment

Source: [comma.ai comma2k19](https://github.com/commaai/comma2k19), MIT license
(copyright 2018 comma.ai; retained in SOURCE_LICENSE).
Pinned commit: `4c7f1a6e1957745beadc1def0e7225f559b09a2a`.
Segment: `Example_1/b0c9d2329ad1606b|2018-08-02--08-34-47/40`.
This is the official approximately one-minute repository example, not a full chunk.

The repository's dongle mapping identifies a RAV4. During post-discovery validation,
[the dataset paper, section IV-A](https://arxiv.org/html/1812.05752v1#S4.SS1)
established the 2017 Toyota RAV4 Platinum. The preparation manifest preserves the
initial, pre-validation vehicle description; validation records the later evidence.

## Sources and conversion

Only these arrays enter preparation, all under the pinned example's `processed_log/`:

- `CAN/raw_can/t`, `address`, `src`, `data`: NPY vectors with 135,468 rows.
- `GNSS/live_gnss_ublox/t`, `value`: 579 timestamps and a 579-by-6 numeric array.

The six files total 4,368,168 bytes. Exact source URLs, SHA-256 hashes, input sizes,
output hashes, counts, timestamp basis, and exclusions are in `provenance.json`.
No decoded CAN speed, wheel-speed array, pose estimate, video, or raw Cap'n Proto
log was downloaded for discovery. Source downloads and the larger regenerated
observation CSVs are git-ignored; the scripts, license, provenance, and small result
artifacts are retained. Local source filenames avoid Windows' forbidden pipe character.

CAN source tag **0 only** is selected explicitly. Counts are 53,800 (0), 45,000 (1),
12,434 (128), and 24,234 (129); the latter three groups are excluded, not mixed.
All selected IDs are standard 11-bit. The converter counts and excludes extended
IDs if encountered and rejects malformed arrays, ordering, IDs, and payload storage.

The data dtype is fixed-width `S8`. Preserve the entire eight-byte storage, including
trailing NULs; converting NumPy byte scalars directly would lose trailing NULs.
**Original DLC is absent from these published arrays.** Eight stored bytes are not
proof that every source message originally had DLC 8; upstream zero padding cannot
be distinguished from actual trailing zeros. This limitation is recorded explicitly.

Both CAN and GNSS use original device-boot seconds. CAN timestamps are nondecreasing;
GNSS timestamps must strictly increase. Do not use GNSS UTC column 3 for alignment.
Speed is the independent u-blox navigation speed in column 2, converted from m/s
to km/h by multiplying by 3.6. Latitude/longitude are not written to observations.

## Reproduce, in order

From the repository root, using Python 3.12+:

```powershell
python -m pip install -e ".[comma2k19]"
python -m tools.prepare_comma2k19 --download --bus 0
python -m tools.run_comma2k19
# Only after blind_results.json exists:
python -m validation.validate_comma2k19
python -m unittest discover -v
```

NumPy is optional and used only for preparation (this run used NumPy 2.5.2).
Core dependencies remain empty. Downloads are whitelisted, size-limited, pinned,
and SHA-256 checked. Tests create tiny official-format arrays locally; there are
no network calls. Preparation tests needing NumPy skip when the optional extra
is absent; all tests ran with it installed for this experiment.

The blind runner reads only `real_can_log.csv` and `real_speed_reference.csv`.
It does not import preparation or validation code, read provenance, or load DBCs.
Core `canary` files are unchanged. Dependency tests prohibit imports from the
preparation/validation packages. The truth files are isolated under
`validation/comma2k19/`; the validator checks the saved blind input hash before
reading its pinned DBC. Blind completion time and a hash of the blind result are
retained for the phase ordering audit.

Analysis settings were declared before discovery: existing nearest alignment,
20 ms tolerance, and 300 minimum matched samples. The latter rejects tiny-sample
perfect correlations when searching many real IDs, and requires more than half
of the 579 reference observations. No ranking, fitting, or alignment formula was
changed. All times remain in seconds; no lag fitting or interpolation was added.

## Observed results

- 53,800 CAN frames, 90 unique IDs, duration 59.992699426 s.
- 579 GNSS samples, 28.1628 to 72.2088 km/h.
- 55,800 layouts enumerated, 7,856 rankable, 14,895 unique aligned series/classes.
- 40,905 equivalent layouts grouped; 35,236 constant candidates skipped.
- Blind analysis wall time about 11.77 s, including about 8.01 s decoding and 1.99 s correlation.
- Winner: 0x0AA, normalized MSB0 start 34, signed 16-bit big-endian.
- Pearson r 0.998667442065; scale 0.00255002265437; offset 97.4535935402.
- RMSE 0.447962950432 km/h; MAE 0.328805269565 km/h; R-squared 0.997336659840.
- All 579 GNSS observations matched. The selected ID has 4,974 frames, so the
  candidate-side match ratio is 0.116405. Mean/max absolute timestamp error:
  14.4371/19.9606 ms. Low CAN-side ratio reflects unequal sampling rates.

Top distinct hypotheses (all on 0x0AA, 16-bit big-endian, with essentially identical
RMSE/R-squared):

| Flat rank | Start | Signed | Scale | Offset | Exact-raw class size |
| --- | ---: | --- | ---: | ---: | ---: |
| 1 | 34 | yes | 0.00255002265437 | 97.4535935402 | 1 |
| 2 | 35 | no | 0.00127501132719 | 13.8931761905 | 1 |
| 3 | 32 | no | 0.0102000906175 | -69.6646911366 | 2 |
| 5 | 33 | no | 0.00510004530874 | -69.6646911366 | 2 |
| 7 | 34 | no | 0.00255002265437 | -69.6646911366 | 1 |

The first two have r 0.9986674420646726; the following entries have
0.9986674420646725. These last-bit numerical differences are retained, not used
to claim superior physical meaning. Exact-raw equivalence does not group different
raw values that become identical after affine fitting. A singleton class therefore
is not proof of a uniquely identifiable physical layout.

See `results/comma2k19/blind_results.json`, `report.html`, and `reconstructed.csv`.

## Post-discovery public-definition validation

The pinned opendbc definition identifies `WHEEL_SPEED_RR` at ID 170, DBC sawtooth
start 38 = normalized MSB0 start 33, **15-bit unsigned big-endian**, scale 0.01,
offset -67.67 km/h. Vehicle mapping and DBC composition are retained separately.
CANary's supported widths remain 8/12/16; 15-bit truth is read only by the isolated
validator. It is not added to discovery or CandidateSpec.

For all 4,974 frames on this ID, with zero raw residual:

```
discovered_raw = 4 * defined_wheel_speed_raw - 65536
```

Thus `signal_match=true` means a confirmed *capture-specific affine wheel-speed
proxy*, while `layout_match=false`. It is not an exact vehicle-speed DBC recovery,
and a wheel speed is not automatically a fused vehicle-speed signal. Public
vehicle definitions establish this comparison, not an OEM/VIN-specific certification.

On the DBC raw basis, the fitted scale/offset are 0.0102000906175/-69.6646911366;
the errors versus the public coefficients are +0.0002000906175/-1.9946911366.
The raw winning coefficients cannot be directly compared as though they used the
same encoding; the structured validation contains both direct and mapped errors.
Timing, GNSS error and wheel-speed calibration are possible contributors, not
causes established by this experiment. No synthetic-style quantization guarantee
applies to these independent real sensors.

## Manual agent run (not executed automatically)

```powershell
python -m canary.agent_cli datasets/real/comma2k19/real_can_log.csv datasets/real/comma2k19/real_speed_reference.csv --value-column speed_kph --provider gemini
```

Use your existing credentials and add `--model YOUR_ENABLED_MODEL_ID` if needed.
The existing agent CLI has no global alignment/min-sample options. For comparison
with this experiment, its tool calls must use `tolerance=0.02, min_samples=300`;
inspect the trace to verify that. Default exact matching will not align these
independent timestamps. No agent prompts, reasoning, or providers were changed.

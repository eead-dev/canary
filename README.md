# CANary

CANary contains a synthetic automotive CAN data generator and a generic CAN
observation/parsing layer with deterministic reference-based candidate ranking.
Requires Python 3.12 or newer; no third-party dependencies are needed.

Run from the repository root:

```sh
python -m unittest discover -v
python -m simulator.generate
python -m canary.inspect datasets/synthetic/can_log.csv
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
All multibyte fields are little-endian. No DBC, AI, or graphical user interface
is implemented.

## CAN observations

`canary/observation.py` reads CSVs into immutable frames with finite timestamps,
integer standard 11-bit IDs, and exactly eight payload bytes. IDs accept decimal
or `0x`-prefixed hexadecimal. Payloads accept contiguous hex or whitespace between
byte pairs. Required columns are `timestamp`, `can_id`, and `data`; extra named
columns are ignored. Missing/duplicate headers, ragged rows (including blank
rows), invalid values, and malformed CSV raise `ValueError` with row context
where applicable.

Inspection provides sorted unique IDs, counts, timestamp bounds, per-ID frame
selection, and estimated frequency. Frequency is `(count - 1) / (latest - earliest)`
in Hz, including duplicate timestamps in the count. It describes observed average
traffic, not a guaranteed transmitter period. Singleton IDs or zero elapsed time
report unavailable. Unordered rows are accepted; selection and extraction retain
file order. Empty captures have no timestamp bounds or duration.

`byte_aligned_candidates()` returns eight unsigned 8-bit configurations and seven
unsigned 16-bit little-endian configurations. For example:

```python
from canary.observation import Candidate, extract_candidate, read_csv

frames = read_csv("datasets/synthetic/can_log.csv")
series = extract_candidate(frames, frames[0].can_id, Candidate(0, 16))
# series contains (timestamp, raw_unsigned_value) pairs; no physical interpretation.
```

The production `canary` package has no simulator dependency. It does not read
ground-truth layouts.
Tests for observations live in `tests/test_observation.py`.

## Reference-based discovery

Run from the repository root. Windows CMD multiline invocation (the caret must
be the last character on each continued line):

```bat
python -m canary.discover ^
  datasets/synthetic/can_log.csv ^
  datasets/synthetic/speed_reference.csv ^
  --value-column speed_kph ^
  --top 10
```

For PowerShell or other shells, use one line:

```sh
python -m canary.discover datasets/synthetic/can_log.csv datasets/synthetic/speed_reference.csv --value-column speed_kph --top 10
```

`canary/reference.py` parses the named numeric column and finite timestamps.
Timestamps must strictly increase; duplicates, malformed rows, and missing or
duplicate headers raise clear errors. Extra named columns are ignored.

`canary/discovery.py` exposes `discover_signal(frames, reference_series)` returning
ranked raw candidates. Reference series are lists of `(timestamp, value)` pairs.
All 15 supported configurations are searched for each observed ID. Candidate
samples are sorted by timestamp and matched exactly by default. `--tolerance`
sets an inclusive distance in seconds for greedy nearest matching, with earlier
reference timestamps winning ties. Matches are monotonic and one-to-one; no
interpolation or delay search occurs. Duplicate candidate times retain input
order, and a reference observation cannot be reused.

Pearson correlation uses normalized, centered sums from the standard library.
`--min-samples` defaults to 3 and cannot be lower. Constant series and candidates
with insufficient matches are omitted from ranking and counted as skipped.
Empty inputs yield no ranked candidates. Scores sort by descending absolute
correlation, preserving the sign; exact ties sort by ID, byte offset, then width.
Results include encoding and aligned sample count. For 8-bit fields the reported
little endianness is immaterial. Correlation measures tracking, not semantic
identity or statistical significance; overlapping fields can score similarly.

`canary/discover.py` provides the CLI; `tests/test_discovery.py` validates it and
the engine. Production code uses only observation APIs and supplied reference
data; only tests consult the generator layout. This stage does not name signals
beyond the user-supplied reference column or detect counters.

## Scale/offset fitting and reconstruction

Add `--fit` to fit the top candidates in correlation order. Windows CMD:

```bat
python -m canary.discover ^
  datasets/synthetic/can_log.csv ^
  datasets/synthetic/speed_reference.csv ^
  --value-column speed_kph --top 10 --fit ^
  --output-reconstruction results/speed_reconstructed.csv
```

PowerShell or other shells, as one line:

```sh
python -m canary.discover datasets/synthetic/can_log.csv datasets/synthetic/speed_reference.csv --value-column speed_kph --top 10 --fit --output-reconstruction results/speed_reconstructed.csv
```

`canary/fitting.py` provides `fit_linear(x, y)`, `reconstruct(raw, scale, offset)`,
`reconstruction_metrics(reference, reconstructed)`, and
`discover_and_fit(frames, reference_series, top_n=10)`. OLS fits
`scale = sum((x-mean(x))*(y-mean(y))) / sum((x-mean(x))**2)` and
`offset = mean(y) - scale*mean(x)`. Negative scales are supported.
The same timestamp alignment and minimum sample count as discovery apply.
Constant raw inputs or insufficient samples return no fit; non-finite inputs,
unequal lengths, and numeric overflow raise errors.

Reconstruction is `raw*scale + offset`. RMSE is the square root of mean squared
residual, MAE is mean absolute residual, and R-squared is `1-SSE/SST`.
R-squared is unavailable for constant references (which discovery already skips).
Metrics describe the aligned samples used to fit, not held-out validation.
Correlation ranking is preserved; no semantic inference is performed.

The optional export requires `--fit`, creates parent directories, and overwrites
the output CSV. It contains `timestamp,reference,reconstructed,raw` for the best
candidate's aligned samples, using candidate timestamps even when tolerance
matching is enabled. Unmatched samples are omitted. The CLI rejects input paths
as output destinations and fails clearly if there is no fitted candidate.
Production fitting uses only observation APIs and supplied reference values;
existing package-wide dependency tests also cover this module.

## Static discovery report

Fit mode prints a capture summary, the best candidate's encoding and equation,
then the existing ranked top-N results. Add `--report` to write a self-contained
HTML report with embedded CSS and SVG, requiring no server, scripts, network,
fonts, or plotting dependencies:

```sh
python -m canary.discover datasets/synthetic/can_log.csv datasets/synthetic/speed_reference.csv --value-column speed_kph --top 5 --fit --output-reconstruction results/speed_reconstructed.csv --report results/speed_report.html
```

Open the HTML file directly in a browser. `--report` requires `--fit`, creates
parent directories, and overwrites the report destination. Its path must differ
from both input files and the reconstruction output. No fitted candidates means
a clear error. All user-controlled report text is HTML-escaped.

The report shows the capture summary, best candidate, fitted equation, metrics,
and the requested top candidates in unchanged correlation order. The SVG plots
every aligned reference/reconstruction sample at the candidate timestamp, with
axes and a legend. Near-identical lines may overlap. Start bits are zero-based
byte offsets multiplied by eight. Metrics remain in-sample measurements; the
report does not assert signal identity beyond the supplied reference name.

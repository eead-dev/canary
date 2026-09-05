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

## Structured engineering tools

`canary/tools.py` exposes model-independent functions accepting a parsed
`list[Frame]` and, where needed, a numeric reference series. Parse files using
`read_csv` and `read_reference` first. Tools return JSON-serializable dictionaries
with integer CAN IDs, numeric statistics, and `None` for unavailable values.
They invoke the existing extraction, alignment, discovery, and fitting APIs.

| Function | Returned fields |
| --- | --- |
| `summarize_capture(frames)` | `total_frames`, `unique_can_id_count`, `first_timestamp`, `last_timestamp`, `duration_seconds` |
| `list_can_ids(frames)` | `can_ids`: records with `can_id`, `frame_count`, `update_frequency_hz` |
| `inspect_can_id(frames, can_id)` | ID, count, frequency, `changing_byte_positions`, `byte_ranges` containing offset/min/max |
| `list_candidate_fields(frames, can_id)` | ID and all 15 `candidates`, each with `can_id`, `byte_offset`, `start_bit`, `width_bits`, `endian`, `signed` |
| `analyze_candidate(frames, can_id, byte_offset, width_bits, reference)` | Encoding, `correlation`, `aligned_samples`, aligned `raw_min`/`raw_max`; optional `fit` with `include_fit=True` |
| `search_candidates(frames, reference, top_n=10)` | `candidates_searched`, `candidates_ranked`, ranked `results` using existing discovery result fields |
| `fit_candidate(frames, can_id, byte_offset, width_bits, reference)` | Encoding, `aligned_samples`, `fit` containing `scale`, `offset`, `rmse`, `mae`, `r_squared` |

Analysis, search, and fit accept keyword-only `tolerance=0.0` and `min_samples=3`.
Search's `top_n` and analysis's `include_fit` are also keyword-only. Invalid
arguments and absent selected IDs raise `ValueError`. Empty captures have null
timestamp bounds/duration; empty searches return no results. Insufficient or
constant raw observations produce a null fit, and undefined correlation is null.
Inspection ranges cover the whole selected capture; analysis ranges cover only
aligned samples. No tool mutates inputs or writes files.

Run all seven tools deterministically, selecting the top-ranked field for the
candidate-specific calls, without a model:

```sh
python -m canary.tool_demo datasets/synthetic/can_log.csv datasets/synthetic/speed_reference.csv --value-column speed_kph
```

The demo prints one JSON object. If no candidate ranks, it prints capture/search
outputs and a selection status. A future agent can call these ordinary functions
and consume their structured outputs without requiring a particular model,
provider SDK, or transport protocol. Package-wide dependency tests cover both
the tools and demo modules.

## Engineering agent (optional Gemini provider)

The bounded agent in `canary/agent.py` exposes only the seven structured tools.
It loads the two user-specified CSVs locally and binds them to the tool dispatcher;
the model cannot supply paths, execute a shell, or access arbitrary files.
Tool argument JSON schemas reject missing/extra properties, invalid types,
unsupported fields, and out-of-range values. Invalid calls return structured
errors to the model. No deterministic ranking or fitting algorithms change.

`canary/llm/base.py` defines plain message, tool-call, response, and provider
contracts. `llm/fake.py` supplies an offline scripted provider. `llm/gemini.py`
alone imports the optional official `google-genai` SDK (lazily). Its SDK chat
retains conversation metadata, with automatic function execution disabled.
Use a new provider instance for each run. The default model is
`gemini-3.7-flash`; `--model` overrides it according to account availability.

Offline test, requiring neither an SDK nor a key:

```sh
python -m canary.agent_cli datasets/synthetic/can_log.csv datasets/synthetic/speed_reference.csv --value-column speed_kph --dry-run
python -m unittest discover -v
```

For a real run, install the optional extra and set the key in the current
Windows CMD session. Replace the placeholder locally; never commit credentials:

```bat
python -m pip install -e ".[gemini]"
set GEMINI_API_KEY=YOUR_API_KEY_HERE
python -m canary.agent_cli ^
  datasets/synthetic/can_log.csv ^
  datasets/synthetic/speed_reference.csv ^
  --value-column speed_kph ^
  --provider gemini ^
  --model gemini-3.7-flash
```

The adapter reads the key only from `GEMINI_API_KEY`; it does not load `.env`
files. Core requirements remain empty. Setuptools is build-time packaging only.
A real run sends the supplied reference name and deterministic tool results to
Google. It does not send source code or raw files; tool results contain capture
statistics and signal evidence. No real API calls occur in tests or dry-run.

Output is JSON with `status`, `conclusion`, `trace`, and `turns`. A completed
`AgentConclusion` contains the reference name, selected encoding, correlation,
scale/offset, RMSE/MAE/R-squared, qualitative confidence, and rationale. Completion
requires search evidence and a matching `analyze_candidate(include_fit=true)`
result. Numeric claims are checked against that evidence; rationale/confidence
remain model judgments, not proof of semantic identity. Gemini submits this
object through an internal `submit_conclusion` declaration, which grants no
additional engineering capability.

`--max-turns` defaults to 12 and `--max-tool-calls` to 30. Each Gemini request has
a 60-second HTTP timeout. Exhaustion, unavailable evidence, or provider failure
returns no conclusion and a nonzero CLI exit code. Malformed responses receive
bounded correction opportunities. Provider failures are sanitized to avoid
printing credential-bearing exceptions. The fake provider's fixed sequence is
summary/search, inspection/analysis, conclusion; it does not represent live model
quality. All agent and adapter tests are offline, including SDK-shaped stubs.

### Transient provider retries

Provider calls retry only structured HTTP 429, 500, 502, 503, and 504 errors
(or `RESOURCE_EXHAUSTED` / `UNAVAILABLE` status names when no HTTP code exists).
Authentication, request/model errors, validation failures, and other statuses
are not retried; arbitrary exception messages are not used for classification.
Retries repeat the same model turn and its pending tool results, preserving the
analysis trace. Gemini's internal retries are disabled to avoid nested attempts.

Defaults are three retries per model turn, a one-second initial backoff cap, and
an eight-second maximum cap. The cap doubles after each failure; each delay is
uniformly jittered between half and all of the cap. Override with
`--max-retries`, `--base-delay-seconds`, and `--max-delay-seconds`, or the matching
`run_agent` keyword arguments. Zero retries disables retries. Tests inject
`retry_sleep` / `retry_jitter` and never wait in real time.

Agent JSON includes cumulative `retry_count` and `provider_attempts` for the run.
Retries do not consume model-turn or tool-call budgets. On exhaustion, status
remains `provider_error` with sanitized diagnostics and the existing tool trace.

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

`byte_aligned_candidates()` returns 44 configurations: signed/unsigned 8-bit
fields and signed/unsigned 16-bit fields in either byte order. For example:

```python
from canary.observation import Candidate, extract_candidate, read_csv

frames = read_csv("datasets/synthetic/can_log.csv")
series = extract_candidate(frames, frames[0].can_id, Candidate(0, 16))
# series contains (timestamp, decoded_integer) pairs; no physical interpretation.
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
All 620 supported configurations are searched for each observed ID. Candidate
samples are sorted by timestamp and matched exactly by default. `--tolerance`
sets an inclusive distance in seconds for greedy nearest matching, with earlier
reference timestamps winning ties. Matches are monotonic and one-to-one; no
interpolation or delay search occurs. Duplicate candidate times retain input
order, and a reference observation cannot be reused.

Pearson correlation uses normalized, centered sums from the standard library.
`--min-samples` defaults to 3 and cannot be lower. Constant series and candidates
with insufficient matches are omitted from ranking and counted as skipped.
Empty inputs yield no ranked candidates. Scores sort by descending absolute
correlation, preserving the sign; exact ties sort by ID, start bit, then width.
Results include encoding and aligned sample count. For byte-aligned 8-bit fields the reported
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
| `list_candidate_fields(frames, can_id)` | ID and all 620 `candidates`, each with `can_id`, `byte_offset`, `start_bit`, `width_bits`, `endian`, `signed` |
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

## Controlled synthetic challenges

Run the current deterministic engine against nine controlled fixtures:

```sh
python -m simulator.evaluate_challenges
```

The command creates the suite if all fixtures are absent, otherwise evaluates
existing files. It prints a full summary and writes `datasets/challenges/evaluation.json`
with top-five fit details, true-field rank, and distractor rank. Partial suites
raise an error. Explicitly regenerate with:

```sh
python -m simulator.challenges --seed 42
python -m simulator.evaluate_challenges --regenerate --seed 42
```

Both commands accept a dataset directory (`--output-dir` for generation,
`--dataset-dir` for evaluation). Generation overwrites fixture files in that
directory. Each scenario contains `can_log.csv`, `reference.csv` (column `value`),
and separate `ground_truth.json` with seed, encoding, and perturbation settings.
Each has 6,000 samples over 60 seconds at 100 Hz, three standard CAN IDs and
18,000 eight-byte frames. The original synthetic dataset is unchanged.

| Scenario | Controlled difference | Expected support |
| --- | --- | --- |
| baseline_easy | Unsigned 16-bit LE target at bytes 2–3, scale 0.01, offset 0 | supported |
| noisy_reference | Gaussian reference noise, standard deviation 0.5, clipped to ±1.5 | supported |
| timestamp_jitter | Independent CAN/reference timestamp jitter, uniform ±2 ms | partially_supported |
| correlated_distractor | Second encoded field: `max(0, 1.02*target + 0.8*sin(t/3) + 0.3)` | supported |
| unusual_scale_offset | Scale 0.037, offset −12.5 | supported |
| long_constant_regions | 50 seconds of plateaus, 10 seconds of linear changes | supported |
| unsupported_big_endian | Target bytes stored big-endian | supported since Ticket #10 |
| unsupported_signed | Target shifted by −45, crossing zero; signed 16-bit representation | supported since Ticket #10 |
| unsupported_bit_offset | Unsigned 12-bit field at LSB0 bit 19, scale 0.025 | supported since Ticket #11 |

Payload and perturbation RNG streams are separate and seeded; the baseline and
reference-only noise variant have identical CAN logs. Noise can make a near-zero
reference slightly negative. Jitter preserves per-ID/reference ordering but may
give a slightly negative first timestamp. Other payload bits/IDs are random.
The fixture-only encoder lives in `simulator`, not production decoding.

Evaluation uses exact alignment except for timestamp_jitter, which uses nearest
alignment with a 4 ms tolerance derived from the two ±2 ms fixture clocks.
The minimum remains three matches. Metadata is read after engine execution and is never
provided to discovery. Recovery means the top candidate matches the entire
hidden field's ID, start bit, width, endianness, and signedness. A highly
correlated partial field or unsigned interpretation does not count as recovery.
Scale/offset metrics and alternative fits remain available in the JSON output.
Expected support describes capability, not a forced result. These challenges
measure current limitations without adding decoding or ranking improvements.

## Timestamp alignment modes

`canary/alignment.py` provides `AlignmentConfig(mode="exact", tolerance=0.0)`
and `align_series(candidate, reference, config)`. The result contains aligned
`(candidate_timestamp, raw, reference_value)` rows and structured diagnostics.
Both timestamps and reference values remain numeric; reference timestamps must
strictly increase. Candidate samples are stably sorted by time.

Exact mode matches only equal timestamps, regardless of tolerance. Nearest mode
chooses the closest unused reference within the inclusive tolerance; equal-distance
ties choose the earlier reference. Accepted matches advance a reference cursor:
no reference is reused and matching never moves backward. Duplicate candidates
retain input order and may match distinct available references within tolerance.
This greedy rule is deterministic, not a globally optimal assignment. Candidates
outside the reference's first/last timestamps are rejected even within tolerance;
there is no endpoint extrapolation or interpolation. Complexity is
O(C log C + C log R + R), including sorting and reference validation.

```sh
python -m canary.discover datasets/challenges/timestamp_jitter/can_log.csv datasets/challenges/timestamp_jitter/reference.csv --value-column value --alignment nearest --timestamp-tolerance 0.004 --fit --top 5
```

The default remains exact. For backward compatibility, omitting the mode with a
nonzero `tolerance` selects nearest; `--tolerance` remains a CLI alias for
`--timestamp-tolerance`. Explicit `--alignment exact` always requires equality.
Discovery, fitting, reconstruction, reports, and structured tools accept the
`alignment` keyword and use the same matcher. Agent schemas/reasoning are unchanged.

Discovery/fitted results and candidate analysis/fit tools expose
`alignment_diagnostics`: candidate, matched, and unmatched sample counts;
match ratio; mean and maximum absolute timestamp error in seconds. No matches
means null error statistics; an empty candidate series has ratio zero. Search
still omits unrankable candidates, so use candidate analysis to inspect alignment
failures. The CLI prints diagnostics for its top candidate. The challenge JSON
records the mode, tolerance, and diagnostics. Matching may discard endpoint
samples, which is expected under the no-extrapolation rule.

## Integer bit-field encodings

`CandidateSpec(start_bit, width_bits, endian="little", signed=False, can_id=None)`
is the fundamental immutable representation. Widths are 8, 12, or 16; starts
range from zero through `64 - width_bits`. An optional CAN ID binds the field.
The compatibility factory `Candidate(byte_offset, width_bits, ...)` preserves
existing calls; it also accepts `start_bit=` instead of a byte offset.
`byte_offset` is derived when the start is divisible by eight, otherwise null.

Little-endian uses LSB0 numbering: bit 0 is the least-significant bit of byte 0,
and the start identifies the field's least-significant bit. Extraction is
`(int.from_bytes(payload, "little") >> start_bit) & ((1 << width_bits) - 1)`.

Big-endian uses **normalized MSB0 numbering**, not DBC/Motorola sawtooth start
numbers: bit 0 is the most-significant bit of byte 0, bit 7 its least-significant
bit, and bit 8 the most-significant bit of byte 1. The start identifies the
field's most-significant bit. Extraction is
`(int.from_bytes(payload, "big") >> (64 - start_bit - width_bits)) & mask`.
Thus starts at byte boundaries reproduce the previous big-endian byte decoder
exactly. A DBC start number must not be passed directly as this normalized index.

After extraction, signed values use two's complement: subtract `2**width_bits`
when the field's high bit is set. For 12 bits, 0x7FF is 2047, 0x800 is -2048,
and 0xFFF is -1. No other widths are supported.

`candidate_fields()` enumerates every valid start and signedness in both byte
orders. Only byte-aligned eight-bit endian variants are equivalent; these are
canonicalized to little and emitted once. Nonaligned eight-bit endian variants
are distinct. Counts per ID are 212 eight-bit, 212 twelve-bit, and 196 sixteen-bit
configurations: **620 total**, versus 44 previously. Three-ID challenges search
1,860 candidates; the original six-ID capture searches 3,720.
`byte_aligned_candidates()` remains the legacy 44-configuration subset.
Signed and unsigned interpretations remain separate even when observed values
happen to be identical. Ranking criteria remain unchanged; positional ties use
start bit, then width, with stable enumeration resolving further ties.

Discovery aligns frame indices once per CAN ID using the existing matcher,
then parses each matched payload once per byte order. Candidate extraction is
linear in sample count and uses shifts/masks on these cached words. Correlation,
fitting, and alignment formulas are unchanged.

`analyze_candidate` and `fit_candidate` accept keyword `start_bit`, `width_bits`,
`endian`, `signed`, and `reference`, or their legacy byte-offset arguments.
Supply exactly one locator. Tool encoding records omit byte offset for unaligned
fields. CLI and reports always display the actual start bit. Agent schema and
fake/demo forwarding carry the new locator; reasoning and orchestration do not
change. Production modules remain independent of simulator layouts.

Challenge names and fixtures remain unchanged for historical comparison. The
evaluator checks the complete encoding, including start bit, after discovery;
it never provides hidden metadata to the engine. It also retains the full-width
big-endian versus partial-byte comparison. Capability labels do not force a
particular ranking outcome when multiple encodings explain the same samples.

With the default fixtures, the bit-offset target now ranks first. The
`unusual_scale_offset` and `long_constant_regions` captures have identical raw
series for the target's low 12 bits and its full 16 bits. The existing width
tie-break ranks 12 bits first and the true 16-bit layout second; strict layout
recovery remains false for those cases despite identical reconstructed values.

## Run-scoped cache and observational equivalence

`canary.analysis.AnalysisRun` snapshots one capture, reference, and alignment
configuration. Pass it through the optional `run=` argument to reuse decoding,
correlation, and fits across calls. Mismatching or mutated inputs are rejected.
The CLI, `discover_and_fit`, tool demo, and tool dispatcher already share a run
internally. The dispatcher keeps separate caches for requested tolerances; no
model schemas, prompts, or reasoning change. There is no global mutable cache.

```python
from canary.analysis import AnalysisRun
from canary.discovery import discover_signal
from canary.fitting import fit_ranked

run = AnalysisRun(frames, reference)
ranked = discover_signal(frames, reference, run=run)
fitted = fit_ranked(frames, reference, ranked[:5], run=run)
print(run.statistics())
```

The cache stores compact immutable integer series, with full-capture values for
inspection and aligned values for analysis. Unsigned extraction is reused for
signed interpretation. Identical series share storage, scores, and fits; reference
normalization is computed once per aligned reference axis. Pearson arithmetic and
OLS formulas are unchanged. Cache memory grows with distinct series and capture
length; discard the run when finished. It is a local synchronous analysis object,
not a persistent or shared service.

Each discovery/fitted result carries an `equivalence` object:

- `representative`: a complete CandidateSpec.
- `equivalent_candidates`: all other layouts with exactly the same aligned series.
- `equivalence_count`: total layouts, including the representative.
- `evidence`: identical decoded time series on this aligned capture.

Equality includes ordered timestamps and every raw integer; alignment/reference
axes must also agree. Complete byte-key equality verifies matches, so hash
collisions cannot merge different series. Equal correlation or affine-related
raw values alone never establishes equivalence. Equivalence is capture-specific;
unmatched samples may differ. All 620 layouts per ID remain enumerated, and every
rankable layout remains in the original ranked list, including equivalent members
outside the requested top N. Representatives use CAN ID, start bit, width, then
little-before-big and unsigned-before-signed, consistent with the existing stable
tie order. Representatives are display choices, not claims of unique layouts.

Safe pruning skips Pearson work for constant series and reuses scores for exact
equivalents. Constants and insufficient samples remain unrankable as before.
The CLI and self-contained HTML report show equivalent layouts explicitly; tools
expose the same structured evidence. An explicit candidate analysis enumerates
layouts to establish its complete equivalence class, reusing a supplied run.

Performance fields are `candidates_enumerated`, `unique_decoded_series`,
`equivalence_classes`, `equivalent_candidates_grouped`,
`constant_candidates_skipped`, `decoding_seconds`, `correlation_seconds`, and
`total_seconds`. Counts include all aligned series, including constant/empty
classes; grouping saves work without removing layouts. Unique-series and class
counts are equal. Timings are wall-clock measurements, not deterministic results.
Run total time includes its lifetime up to the snapshot; evaluator totals also
include parsing and fitting. Decoding time includes packing/aligned selection;
other overhead is included in total time.

Challenge evaluation now distinguishes:

- `signal_value_recovered`: the true field is in the winning equivalence class.
- `exact_layout_recovered`: the winner matches the true field and has no equivalent
  alternative in the supported space.
- `layout_ambiguous`: the winning class contains multiple layouts.

The legacy `recovered` field remains a first-layout match for compatibility; use
the new fields to interpret outcomes. The two 12/16-bit ties are successful value
recoveries with ambiguous layouts. Positive 16-bit signed/unsigned ties are also
reported honestly. No fixture metadata is passed into production analysis.

## Agent ambiguity and competing hypotheses

Agent conclusions retain the original fields and add `signal_confidence`,
`layout_confidence`, `layout_ambiguous`, `equivalent_layouts`, and
`alternative_candidates`. Confidence values are qualitative high/medium/low,
not probabilities. Signal confidence describes tracking of the supplied reference;
layout confidence describes evidence for the exact encoding. Equivalent layouts
are every other member of the selected field's aligned equivalence class, excluding
the selected field. An ambiguous class cannot receive high layout confidence.

`search_candidates` preserves its flat `results` and adds their one-based `rank`.
It also returns up to `top_n` distinct `hypotheses`, each with the representative,
original flat rank, correlation, equivalence count, equivalent specs, and identity
evidence. Consequently top-N equivalent entries do not hide competing hypotheses.
Ranks still use the unchanged deterministic search order. No new comparison tool
is necessary: repeated `analyze_candidate(include_fit=True)` calls reuse the same
run cache and expose fit metrics, raw ranges, coverage, and equivalence evidence.

The system instruction asks the model to compare non-equivalent hypotheses, keep
signal evidence separate from layout evidence, and acknowledge when the capture
cannot distinguish layouts. It prohibits invented conventions and unsupported
claims about scales. Conclusions must cite search evidence and selected/alternative
analyses. Numeric fields are checked against those analyses; complete equivalent
lists and ambiguity flags are checked against deterministic equivalence evidence.
If search exposed a non-equivalent alternative, at least one must be analyzed and
reported before completion. Alternative records contain `candidate`, `correlation`,
`rmse`, `mae`, `r_squared`, and a concise `reason`; at most five are allowed.
The existing malformed-response correction loop handles invalid conclusions.

The offline fake provider compares the first two distinct hypotheses and, when
visible among the first ten, the strongest additional hypothesis on another ID.
It selects the compared fit with lowest RMSE (then highest R-squared). This is an
explicit fixture policy, not a change to deterministic discovery ranking or a
prediction of live-model behavior. Its demonstration signal confidence is high
for absolute r >= 0.995 and R-squared >= 0.99, medium for absolute r >= 0.9 and
R-squared >= 0.8, otherwise low. Ambiguous layout confidence is low; uniquely
represented fields with comparably fitting rivals receive reduced layout confidence.
These thresholds are test/demo policy, not a calibrated production confidence rule.

All automated runs remain offline. After configuring your existing Gemini key
locally, manually run these commands from the repository root (add `--model` with
your enabled model ID to override the existing CLI default):

```powershell
python -m canary.agent_cli datasets/challenges/baseline_easy/can_log.csv datasets/challenges/baseline_easy/reference.csv --value-column value --provider gemini
python -m canary.agent_cli datasets/challenges/unusual_scale_offset/can_log.csv datasets/challenges/unusual_scale_offset/reference.csv --value-column value --provider gemini
python -m canary.agent_cli datasets/challenges/correlated_distractor/can_log.csv datasets/challenges/correlated_distractor/reference.csv --value-column value --provider gemini
```

For local evidence-only exercises use `--dry-run`. The reasoning regression tests
cover unique layout, width ambiguity, a correlated distractor, noisy reference,
signedness ambiguity, fabricated evidence, and malformed-conclusion correction.

## Real-data blind experiment: comma2k19

The reproducible real-data experiment is documented in
[datasets/real/comma2k19/README.md](datasets/real/comma2k19/README.md).
It uses only the official one-minute example's raw CAN and independent u-blox
speed arrays. NumPy is an optional preparation extra; core analysis is unchanged.
Preparation, blind discovery, and public-definition validation are separate stages.
The result recovers a rear-right wheel-speed proxy but not the exact 15-bit public
DBC layout. Source licenses, pinned hashes, limitations, results, and the manual
Gemini command are documented with the experiment.

## Affine-equivalent raw encodings

`canary.relationships.compare_raw_series(x, y)` measures `y = a*x+b` using the
existing ordinary least-squares API. It returns `relationship_type` (`exact`,
`affine`, or `distinct`), `scale_between_raw`, `offset_between_raw`,
`rmse_between_raw`, `max_abs_residual`, `sample_count`, and a reason.
At least three samples and variation in **both** series are required. Constants
and insufficient observations return `distinct` with undefined coefficients;
non-finite values and unequal lengths raise errors. Exact means equal raw values.
Affine requires a nonzero slope and **every** absolute residual <= `1e-8` raw units.
This fixed absolute tolerance admits arithmetic roundoff in the supported integer
domain, not quantization noise or exceptional samples. High Pearson correlation
alone does not establish affine equivalence. Evidence is capture-specific, not
proof that the layouts remain equivalent on a different drive.

`AnalysisRun` maintains a separate lazy affine index. For each unique nonconstant
integer series, subtract its first value and divide all differences by their GCD,
with the first nonzero difference positive. Equal normalized integer vectors on
identical aligned timestamp/reference axes identify exact affine relationships,
including sign reversals and fractional ratios. OLS verifies and measures each
reported relation. This conservative index does not group approximately similar
integer vectors. It takes linear work per unique series, avoiding an all-pairs
search. Raw-series cache keys, exact classes, correlation, ranking, reference
fitting, alignment, and the 620 supported layouts per CAN ID remain unchanged.

Tools expose `exact_raw_equivalents`, `affine_equivalents` (each other layout plus
raw-to-raw evidence, with `other_raw = a*selected_raw+b`), and
`distinct_alternatives`. Equivalent lists cover the full supported space, not just
top-N. Distinct alternatives are limited to supplied comparison hypotheses; an
empty list in explicit analysis means no distinct comparisons were requested.
Candidates with different aligned axes are marked `uncompared`, never resampled.
Search hypotheses remain representatives of **exact** classes, and their order
does not change. `AnalysisRun.raw_relationship(first, second)` exposes direct
comparison using cached decoding; it rejects different aligned axes.

Conclusions keep `equivalent_layouts` for exact raw equality and additionally
require `affine_equivalent_layouts` and `ambiguity_reason`. Affine alternatives
set `layout_ambiguous=true` and `ambiguity_reason="affine_equivalent_layouts"`;
high layout confidence is rejected. Exact-only ambiguity uses
`exact_raw_equivalent_layouts`; unambiguous evidence uses `none`. Reconstruction
metrics cannot uniquely identify layouts related by an affine transformation.
CLI and HTML output state this explicitly. The fake provider also compares a
visible non-affine hypothesis when its first two hypotheses are affine-related.

Challenge value recovery now includes exact or affine alternatives; exact layout
recovery requires neither ambiguity. The real blind report contains the same
production evidence; public definitions are consulted only in the later isolated
validation stage.

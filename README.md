# CANary

**An evidence-grounded AI agent for discovering hidden automotive CAN signals from raw vehicle-network traffic and external reference measurements.**

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB)
![Core dependencies: standard library](https://img.shields.io/badge/Core-standard_library-2E7D32)
[![Tests: 217 passing](https://img.shields.io/badge/Tests-217_passing-2E7D32)](examples/comma2k19/evidence/tests.txt)

> **Real public vehicle data:** CANary recovered the `0x0AA` wheel-speed signal family from a 2017 Toyota RAV4 capture, fitting an independent GNSS speed reference with **r ≈ 0.9987** and **RMSE ≈ 0.45 km/h**. Discovery used no DBC. The agent preserved layout ambiguity instead of claiming a uniquely identified encoding.

[Real-world result](#real-world-benchmark) · [Quick start](#quick-start) · [Architecture](#architecture) · [Tests](#tests-and-reliability)

## Why this exists

Raw CAN traffic carries many unknown packed signals. A changing payload byte might encode a physical measurement, part of a larger field, or unrelated data. Manually testing layouts, byte orders, signs, timing, and scaling is slow—and a convincing correlation can still point to several indistinguishable encodings.

CANary searches the supported layout space deterministically, measures each candidate against a supplied reference, and gives an agent structured evidence to interpret. The model selects and explains evidence; it does not calculate or transcribe the final measurements.

## Real-world benchmark

The public **comma2k19** example capture comes from a **2017 Toyota RAV4**. CANary analyzed raw CAN observations against independent u-blox GNSS speed. The blind runner reads only the observation and reference CSVs; comparison with a pinned public DBC happens separately, after discovery.

| Measurement | Observed result |
| --- | --- |
| Capture | Approximately 60 seconds; CAN source/bus tag 0 |
| CAN traffic | **53,800 frames across 90 CAN IDs** |
| Reference | **579 GNSS speed samples**, converted to km/h |
| Recovered signal family | **CAN ID 170 / `0x0AA`**, wheel-speed-related values |
| Pearson correlation | **0.998667442** |
| Reconstruction RMSE | **0.447963 km/h** |
| Reconstruction R² | **0.99733666** |
| Live agent | Ollama `gpt-oss:120b-cloud`: **complete in two consecutive public CLI runs, 5 turns each, 0 retries** |
| Layout conclusion | **Ambiguous**, with 11 affine-equivalent alternatives to the selected layout |

**CANary recovered the signal family and value behavior—not a uniquely identified exact DBC layout.** Multiple layouts reconstruct the reference equivalently after scale/offset fitting. The live conclusion reports high signal confidence and low layout confidence, and passes strict validation against collected deterministic evidence.

These are **in-sample reconstruction metrics on one public capture**, not a held-out accuracy estimate or a guarantee across vehicles. Wheel speed is not automatically the same physical quantity as fused vehicle speed.

Evidence: [public CLI run 1](examples/comma2k19/evidence/agent_run_01.json) · [public CLI run 2](examples/comma2k19/evidence/agent_run_02.json) · [blind results](examples/comma2k19/evidence/blind_results.json) · [post-discovery validation](examples/comma2k19/evidence/validation.json) · [demo and checksums](examples/comma2k19/README.md) · [source provenance](datasets/real/comma2k19/provenance.json)

## How it works

```text
Raw CAN + reference signal
  → candidate bitfield search
  → timestamp alignment
  → correlation / ranking
  → scale / offset fitting
  → exact and affine equivalence analysis
  → AI evidence reasoning
  → deterministic conclusion hydration + strict validation
```

The deterministic workflow runs without an LLM. The optional agent uses those same production APIs, chooses which evidence to inspect, and submits a small `AgentDecision` referencing fitted analyses. CANary assembles the full `AgentConclusion` from session evidence and rejects unsupported claims.

## Architecture

| Layer | Responsibilities | Boundary |
| --- | --- | --- |
| **Deterministic core** | Decoding, candidate generation, alignment, statistics, fitting, exact/affine equivalence, evidence validation | Python standard library; no model or ground-truth dependency |
| **AI layer** | Chooses tools, compares evidence, selects candidate references, assigns confidence, writes rationale | Provider-independent interface; no arbitrary filesystem or shell tools |
| **Evidence layer** | Stable session references, fitted-reference allowlists, exact metrics and equivalent-layout lists, deterministic hydration, strict conclusion validator | The model cannot supply replacement numeric evidence |

References progress through `search_candidate`, `analyzed_unfitted`, and `analyzed_fitted`. **Only fitted references are selectable.** A search-only decision keeps the agent in exploration until fitted evidence exists. Finalization exposes no exploration tools and uses a separate bounded repair budget.

Confidence and interpretation remain model judgments. Candidate identities, fit metrics, and equivalence lists come from collected tool results. A completed conclusion must match that evidence, including its ambiguity constraints.

## Supported capabilities

- **Classic CAN CSV inspection:** standard 11-bit IDs, eight-byte payloads, counts, timing, observed frequencies, and changing-byte ranges.
- **Generic bitfields:** widths **8, 12, 15, and 16 bits**, every valid start position, signed two's-complement and unsigned values, little-endian and normalized big-endian extraction. **820 configurations per CAN ID**, without duplicate byte-aligned 8-bit endian variants.
- **Reference alignment:** exact matching or deterministic nearest matching within a tolerance, one-to-one matches, no extrapolation, and alignment diagnostics.
- **Discovery and reconstruction:** Pearson ranking, ordinary least-squares scale/offset fitting, reconstructed values, RMSE, MAE, and R².
- **Ambiguity analysis:** exact decoded-series equivalence and conservative affine-equivalence evidence; cached decoded series and safe constant-series pruning.
- **Structured tools and agents:** capture inspection, search, candidate analysis, fitting, stable evidence references, and validated conclusion assembly.
- **Evidence output:** reconstruction CSV, ranked JSON results, agent/tool diagnostics, and self-contained HTML reports with embedded SVG charts. No web server required.

**Bit numbering:** little-endian bit 0 is the least-significant bit of byte 0. Normalized big-endian bit 0 is the most-significant bit of byte 0; indices advance MSB-to-LSB through consecutive bytes. This is **not DBC/Motorola sawtooth start-bit numbering**. Byte offsets are derived only for aligned starts.

## Quick start

Use **Python 3.12+**. Run commands from the repository root. Multiline examples below use **Windows CMD** (`^` must be the last character on a continued line).

### 1. Create an environment

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
```

The core has no third-party runtime dependencies. Optional extras support real-data preparation and Gemini.

### 2. Run the deterministic synthetic demo

```bat
python -m simulator.generate
python -m canary.inspect datasets\synthetic\can_log.csv
python -m canary.discover ^
  datasets\synthetic\can_log.csv ^
  datasets\synthetic\speed_reference.csv ^
  --value-column speed_kph --top 5 --fit ^
  --output-reconstruction results\speed_reconstructed.csv ^
  --report results\speed_report.html
```

Open `results\speed_report.html` in a browser to compare reference and reconstructed values, inspect the ranked candidates, and see equivalence evidence. The generator creates a reproducible 60-second, 100 Hz drive with speed, pedal, brake, RPM, and unrelated traffic. Generation and report commands overwrite their output files.

For an offline agent walkthrough without credentials or API calls:

```bat
python -m canary.agent_cli datasets\synthetic\can_log.csv datasets\synthetic\speed_reference.csv --value-column speed_kph --dry-run
```

### 3. Reproduce the deterministic real-data workflow

The source arrays and generated real-data CSVs are git-ignored. Download and prepare the pinned public example first:

```bat
python -m pip install -e ".[comma2k19]"
python -m tools.prepare_comma2k19 --download --bus 0
python -m tools.run_comma2k19
```

NumPy is used only for source-array preparation. Downloads are pinned and checksum-verified. The blind runner uses **nearest alignment, 0.02-second tolerance, and 300 minimum aligned samples**. It writes `blind_results.json`, `reconstructed.csv`, and `report.html` under `results\comma2k19`.

Only **after** blind discovery, compare the saved result against isolated public definitions:

```bat
python -m validation.validate_comma2k19
```

The validator does not feed definitions back into discovery. [Dataset provenance and preparation details](datasets/real/comma2k19/README.md) document source selection and limitations; [validation results](examples/comma2k19/evidence/validation.json) distinguish recovered values from exact-layout identification.

### 4. Run the Ollama agent on real data

Install Ollama separately. Start `ollama serve` in another CMD window if the desktop app is not already serving. For a cloud-backed model, authenticate through Ollama:

```bat
ollama signin
ollama pull gpt-oss:120b-cloud
set "OLLAMA_BASE_URL=http://localhost:11434"
python -m canary.agent_cli ^
  datasets\real\comma2k19\real_can_log.csv ^
  datasets\real\comma2k19\real_speed_reference.csv ^
  --value-column speed_kph ^
  --provider ollama --model gpt-oss:120b-cloud ^
  --alignment nearest --timestamp-tolerance 0.02 --min-samples 300 ^
  --max-finalization-attempts 3
```

For local inference, pull a suitable tool-capable model, such as `ollama pull gpt-oss:20b`, and change `--model` accordingly. Local inference needs sufficient hardware. Ollama cloud models use the daemon's signed-in session; CANary does not manage its credentials.

The agent prints JSON containing the conclusion, tool trace, per-attempt diagnostics, active analysis configuration, and retry counts. Alignment settings belong to the session; model tool arguments cannot override them. Defaults remain 12 exploration turns, 30 tool calls, and three finalization repair attempts. Ollama output limits are omitted by default; `--ollama-max-tokens` is optional.

## Providers

All adapters implement the same message/tool interface and use the same analysis tools, evidence registry, and conclusion validator. There is no automatic provider fallback.

| Provider | Setup | Selection |
| --- | --- | --- |
| **Gemini** | `python -m pip install -e ".[gemini]"`; set `GEMINI_API_KEY` | `--provider gemini --model YOUR_MODEL_ID` |
| **OpenRouter** | Set `OPENROUTER_API_KEY`; standard-library adapter | `--provider openrouter --model YOUR_MODEL_ID` |
| **Ollama** | Running local daemon; sign in through Ollama for cloud models | `--provider ollama --model YOUR_MODEL_NAME` |

Windows CMD credential syntax is `set "GEMINI_API_KEY=YOUR_KEY"` or `set "OPENROUTER_API_KEY=YOUR_KEY"`. Keep credentials out of files and commits. Remote providers receive the reference label and structured tool evidence. Local Ollama requires no API key.

## Tests and reliability

**217 tests passed** in the [recorded full-suite run](examples/comma2k19/evidence/tests.txt). This is a recorded result, not a live CI badge. The full count includes optional NumPy preparation tests.

```bat
python -m pip install -e ".[comma2k19]"
python -m unittest discover -s tests -v
python -m simulator.evaluate_challenges --regenerate
```

The synthetic challenge suite covers noisy references, timestamp jitter, correlated distractors, unusual scale/offset, constant regions, endian/sign variants, and non-byte-aligned fields. Evaluation distinguishes signal recovery, exact-layout recovery, and ambiguity.

Provider tests use mocks and stubs: **no API calls in tests**. Regression coverage includes retry state preservation, sanitized errors, schema repair, fitted-reference promotion, exact evidence hydration, ambiguity constraints, and production isolation from truth sources. Live provider success is recorded separately from offline tests.

## Repository structure

```text
canary/                  Production analysis and agent package
  observation.py         CAN parsing and generic extraction
  analysis.py            Per-run cache, alignment, and equivalence evidence
  discovery.py           Deterministic candidate ranking
  fitting.py             Scale/offset fitting and reconstruction
  relationships.py       Affine-equivalence analysis
  tools.py               Structured engineering tool interface
  agent.py               Bounded orchestration and strict conclusion validation
  agent_evidence.py      Stable references, eligibility, and hydration
  llm/                   Gemini, OpenRouter, Ollama, fake provider, retries
simulator/               Synthetic generation and challenge evaluation
tools/                   Public comma2k19 preparation and blind runner
validation/              Isolated post-discovery public-definition checks
tests/                   Deterministic, agent, and provider regressions
datasets/                Synthetic fixtures and real-data provenance
examples/comma2k19/      Curated public demo and immutable evidence copies
docs/                    Architecture, reproduction, and asset placeholders
results/                 Ignored generated working output
```

## Design principles

- **Deterministic math, probabilistic reasoning.** Models interpret tool evidence; production APIs compute the numbers.
- **No DBC leakage during blind discovery.** Public definitions belong to post-discovery validation, and synthetic truth stays outside production analysis.
- **Ambiguity is a valid result.** Exact and affine-equivalent encodings can remain indistinguishable on a capture.
- **Evidence before confidence.** Select fitted references, hydrate exact measurements, then validate the assembled conclusion.
- **Model-provider independence.** Switching providers does not change analysis algorithms or evidence rules.

## Limitations

- Discovery requires an external reference signal; this is supervised candidate search, not arbitrary semantic decoding from CAN alone.
- Observational ambiguity can prevent exact-layout identification even with excellent reconstruction. Confidence is qualitative, not calibrated probability.
- Search cost grows with IDs, samples, and layout space. Supported widths are currently 8/12/15/16 bits; arbitrary widths are not implemented.
- Live agent behavior depends on provider/model quality, latency, quota, and tool-calling reliability. A successful recorded run does not guarantee every run completes.
- Current input is classic CAN CSV with eight stored payload bytes. The comma2k19 source arrays omit original DLC, so source padding cannot be distinguished from genuine trailing zeros.
- No live capture, BLF/ASC ingestion, DBC export, or general DBC import is implemented. The isolated validation reader is not a production decoder.

## Roadmap

Possible next steps, **not current capabilities**:

- Lightweight UI for reviewing evidence and ambiguity.
- Multi-signal discovery workflows.
- DBC export from validated hypotheses.
- Live vehicle capture support.

See [architecture](docs/architecture.md) and [reproducibility](docs/reproducibility.md) for boundaries and complete reproduction steps. `results/` is ignored working output; the curated public evidence lives in `examples/comma2k19/evidence/`.

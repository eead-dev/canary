# Architecture

```text
Raw CAN + reference → candidate generation → alignment → correlation/ranking
  → fitting → equivalence/ambiguity analysis → evidence registry
  → AgentDecision → deterministic hydration → strict validation
```

## Deterministic core

`canary/observation.py` parses classic CAN observations and extracts supported
8/12/15/16-bit fields. Little-endian starts count from byte 0's least-significant
bit; normalized big-endian starts count from byte 0's most-significant bit,
continuing through successive bytes. This is not DBC sawtooth numbering.

`analysis.py` owns per-run decoded-series caching, alignment and equivalence
evidence. `discovery.py`, `fitting.py`, and `relationships.py` perform ranking,
physical reconstruction and affine analysis. `tools.py` exposes these APIs as
structured tools. The deterministic CLI can run without an LLM.

Exact equivalence shares decoded values; affine equivalence preserves distinct raw
encodings related by scale and offset. Neither a high correlation nor excellent
reconstruction uniquely establishes a layout. Production discovery does not read
simulator ground truth or validation DBCs.

## Evidence layer

`agent_evidence.py` assigns stable references and promotes their state from search
evidence to unfitted or fitted analysis. Only fitted references are selectable.
An `AgentDecision` selects references and supplies confidence and rationale;
deterministic hydration supplies identities, metrics and equivalence lists.
The strict validator rejects conclusions inconsistent with collected evidence.
Ambiguity remains a valid successful conclusion.

## LLM/provider layer

`agent.py` orchestrates bounded exploration and tool-free finalization. Session
alignment settings apply consistently to relevant tools. Providers choose tools
and interpret evidence; they do not replace measured numeric evidence.

The `canary/llm/` Gemini, OpenRouter and Ollama adapters implement the same provider
interface. Retry handling and sanitized diagnostics are separate from CAN math.
There is no automatic provider fallback.

## Repository boundaries

- `simulator/`: synthetic generation and challenge evaluation; truth is separate.
- `tools/`: public-data preparation and blind experiment entry points.
- `validation/`: isolated post-discovery comparison with pinned public definitions.
- `tests/`: deterministic, evidence and mocked-provider regression coverage.
- `examples/comma2k19/`: curated evidence; `results/`: ignored working output.
- `docs/assets/`: placeholders for future screenshots and diagrams; no frontend yet.

See [reproduction steps](reproducibility.md) and the [public demo](../examples/comma2k19/README.md).

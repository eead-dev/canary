# Ticket #15 implementation report

Implemented deterministic exact/affine/distinct raw-series evidence, a separate
run-scoped affine index, structured tool evidence, CLI/HTML ambiguity reporting,
and agent conclusion checks. Raw-series cache keys remain unchanged.

## Criterion

Fit `other_raw = a*selected_raw+b` with existing OLS. Require at least three
samples, variation in both series, nonzero slope, and maximum absolute residual
at most **1e-8 raw units across every sample**. Exact raw equality is reported
separately. Constants and insufficient series do not establish affine equivalence.
Non-finite values are rejected. Pearson correlation is not used for classification.
Integer normalized-difference signatures identify exact affine groups efficiently;
OLS measures and verifies relationships. Comparisons require identical aligned axes.

## Verification

- Full suite: **154 tests passed**, 224.578 seconds.
- Final focused regression run: **44 tests passed**, 2.155 seconds.
- Synthetic challenge evaluation: all nine signal-value recoveries preserved,
  147.823 seconds. Top-five fitted results, recovery flags, and ambiguity flags
  match the saved pre-ticket results exactly for every scenario.
- Blind real-data experiment completed; its top-ten fitted results match the
  pre-ticket results exactly. 55,800 layouts enumerated, 7,856 ranked, unchanged.
- Isolated pinned-definition validation rerun after the final blind artifact.
- No changes to decoding widths, correlation, ranking, fitting, or alignment
  formulas. Still 620 candidates per CAN ID. No dependencies added or model calls.

| Synthetic scenario | Value recovered | Exact layout recovered | Ambiguous |
| --- | --- | --- | --- |
| baseline_easy | true | false | true |
| noisy_reference | true | false | true |
| timestamp_jitter | true | false | true |
| correlated_distractor | true | false | true |
| unusual_scale_offset | true | false | true |
| long_constant_regions | true | false | true |
| unsupported_big_endian | true | false | true |
| unsupported_signed | true | true | false |
| unsupported_bit_offset | true | true | false |

## Real-data affine group

The five leading exact-raw hypotheses are **one affine group containing seven
layouts**. Let A be the unchanged winner: CAN ID 0x0AA, normalized big-endian start
34, signed 16-bit. All layouts below are 16-bit big-endian on the same ID.

| Start | Signedness | Raw relationship |
| ---: | --- | --- |
| 32 | unsigned and signed | `other_raw = 0.25*A + 16384` |
| 33 | unsigned and signed | `other_raw = 0.5*A + 32768` |
| 34 | unsigned | `other_raw = A + 65536` |
| 35 | unsigned | `other_raw = 2*A + 65537` |

All six other-layout comparisons have **RMSE 0 and maximum residual 0 over 579
aligned samples**. In particular, for supported start-32 unsigned B,
`A = 4*B - 65536`. These results use no public definition during discovery.

The winner remains correlation 0.9986674420646726, physical scale
0.002550022654370228, offset 97.4535935402154, RMSE 0.4479629504317512,
MAE 0.3288052695648548, R-squared 0.9973366598399963. It now explicitly has
`layout_ambiguous=true`, `ambiguity_reason="affine_equivalent_layouts"`.

The external reference cannot distinguish these reconstructions after scale/offset
fitting. This is capture-specific evidence, not unique layout identification.
Public-definition validation remains separate and confirms the existing affine
proxy relationship over all 4,974 selected-ID frames; it does not expand widths.

## Files added or modified

Added production API and regression tests:

- [relationships.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/relationships.py)
- [test_relationships.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_relationships.py)

Updated production integration:

- [analysis.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/analysis.py)
- [tools.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/tools.py)
- [agent.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/agent.py)
- [fake.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/llm/fake.py)
- [discover.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/discover.py)
- [reporting.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/reporting.py)

Updated evaluation, validation, tests and documentation:

- [evaluate_challenges.py](C:/Users/eeada/OneDrive/Desktop/canary/simulator/evaluate_challenges.py)
- [run_comma2k19.py](C:/Users/eeada/OneDrive/Desktop/canary/tools/run_comma2k19.py)
- [validate_comma2k19.py](C:/Users/eeada/OneDrive/Desktop/canary/validation/validate_comma2k19.py)
- [test_bit_fields.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_bit_fields.py)
- [test_challenges.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_challenges.py)
- [README.md](C:/Users/eeada/OneDrive/Desktop/canary/README.md)
- [real-data README](C:/Users/eeada/OneDrive/Desktop/canary/datasets/real/comma2k19/README.md)

Updated generated artifacts:

- [challenge evaluation](C:/Users/eeada/OneDrive/Desktop/canary/datasets/challenges/evaluation.json)
- [blind results](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/blind_results.json)
- [HTML report](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/report.html) (27,707 bytes, self-contained)
- [isolated validation](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/validation.json)

Added evidence logs and before-state snapshots:

- [full tests](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket15_tests.txt)
- [challenge console](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket15_challenges.txt)
- [prior challenges](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket15_challenges_before.json)
- [prior blind results](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/blind_results_before_ticket15.json)
- [blind console](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/ticket15_blind_console.json)
- [validation console](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/ticket15_validation_console.json)
- This implementation report.

Reconstruction CSV was regenerated with identical content. Input captures,
references, challenge fixtures and the pinned public definition were unchanged.

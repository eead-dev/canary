# Ticket #16 implementation report

Generic 15-bit support only. Supported widths are 8, 12, 15, 16. The generic decoder and all correlation, ranking, fitting, alignment, affine criteria and agent reasoning are unchanged. Agent schema only adds width 15. No dependencies or providers added.

## Counts

| Dataset | Before | After |
| --- | ---: | ---: |
| Per CAN ID | 620 | 820 |
| Original six IDs | 3720 | 4920 |
| Real 90 IDs | 55800 | 73800 |

Increase: 200 per ID (32.26%). Fifteen-bit starts 0â€“49, both endians and signedness choices. Signed values with bit 14 set subtract 32768. Tests cover all starts, cross-byte extraction, boundary values and independent bit-oracle uniqueness.

## Public layout after blind discovery

0x0AA, normalized MSB0 start 33, 15-bit big-endian unsigned, rank **6**. Production discovery used only CAN/reference CSVs and saved complete ranking before pinned-definition validation.

- correlation: 0.9986674420646725
- scale: 0.010200090617480912
- offset: -69.66469113659188
- rmse: 0.44796295043175166
- mae: 0.32880526956485495
- r_squared: 0.9973366598399963
- aligned_samples: 579

Validation semantics:

- signal_value_recovered: True
- true_layout_present: True
- exact_layout_rank: 6
- exact_layout_uniquely_identified: False
- layout_ambiguous: True

## Leading real candidates

All are big-endian on 0x0AA. T denotes the public 15-bit raw series. Every listed relationship has zero residual over all 579 aligned samples.

| Rank | Start | Width | Signed | Raw relationship to T |
| ---: | ---: | ---: | --- | --- |
| 1 | 34 | 15 | True | 2*T - 32768 |
| 2 | 34 | 16 | True | 4*T - 65536 |
| 3 | 35 | 16 | False | 8*T - 65535 |
| 4 | 32 | 16 | False | T |
| 5 | 32 | 16 | True | T |
| 6 | 33 | 15 | False | T |
| 7 | 33 | 15 | True | T |
| 8 | 33 | 16 | False | 2*T |
| 9 | 33 | 16 | True | 2*T |
| 10 | 34 | 15 | False | 2*T |
| 11 | 34 | 16 | False | 4*T |
| 12 | 35 | 15 | False | 4*T - 32768 |

One affine group contains 12 layouts across seven exact-raw classes. The public layout is in an exact class of four. The prior 16-bit winner is now #2; #1 is signed 15-bit start 34. Excellent reconstruction does not uniquely identify the public layout. The top three correlations are 0.9986674420646726; the others are 0.9986674420646725. These existing floating-point differences and tie-breaks were not changed. Leading reconstructed RMSE/R-squared remain approximately 0.447962950432 / 0.997336659840.

## Synthetic challenges

| Scenario | Signal recovered | Exact layout recovered | Ambiguous | True layout rank |
| --- | --- | --- | --- | ---: |
| baseline_easy | True | False | True | 3 |
| noisy_reference | True | False | True | 3 |
| timestamp_jitter | True | False | True | 3 |
| correlated_distractor | True | False | True | 3 |
| unusual_scale_offset | True | False | True | 4 |
| long_constant_regions | True | False | True | 4 |
| unsupported_big_endian | True | False | True | 1 |
| unsupported_signed | True | False | True | 2 |
| unsupported_bit_offset | True | True | False | 1 |

All nine signal recoveries preserved. The signed scenario now contains an exact 15/16-bit tie, so its layout is ambiguous. The bit-offset scenario remains uniquely recovered. No fixtures were changed.

## Runtime

Blind analysis: 12.588265 s before; 16.831308 s after.
Synthetic evaluation: 147.823 s before; 167.247 s after. Wall-clock comparisons are subject to machine load and are not controlled benchmarks.

Full suite: **157 tests passed in 313.109 seconds**, versus 154 tests in 224.578 seconds before this ticket. The final clean log is ticket16_tests_final.txt. Earlier failed logs document outdated width/count assertions corrected before this passing run.

## Files changed

- [README.md](C:/Users/eeada/OneDrive/Desktop/canary/README.md)
- [canary/agent.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/agent.py)
- [canary/observation.py](C:/Users/eeada/OneDrive/Desktop/canary/canary/observation.py)
- [datasets/challenges/evaluation.json](C:/Users/eeada/OneDrive/Desktop/canary/datasets/challenges/evaluation.json)
- [datasets/real/comma2k19/README.md](C:/Users/eeada/OneDrive/Desktop/canary/datasets/real/comma2k19/README.md)
- [results/comma2k19/before_ticket16.json](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/before_ticket16.json)
- [results/comma2k19/blind_results.json](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/blind_results.json)
- [results/comma2k19/reconstructed.csv](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/reconstructed.csv)
- [results/comma2k19/report.html](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/report.html)
- [results/comma2k19/ticket16_console.json](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/ticket16_console.json)
- [results/comma2k19/ticket16_validation.json](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/ticket16_validation.json)
- [results/comma2k19/validation.json](C:/Users/eeada/OneDrive/Desktop/canary/results/comma2k19/validation.json)
- [results/ticket16_challenges.txt](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket16_challenges.txt)
- [results/ticket16_challenges_before.json](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket16_challenges_before.json)
- [results/ticket16_tests.txt](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket16_tests.txt)
- [results/ticket16_tests_final.txt](C:/Users/eeada/OneDrive/Desktop/canary/results/ticket16_tests_final.txt)
- [simulator/evaluate_challenges.py](C:/Users/eeada/OneDrive/Desktop/canary/simulator/evaluate_challenges.py)
- [tests/test_alignment.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_alignment.py)
- [tests/test_analysis.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_analysis.py)
- [tests/test_bit_fields.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_bit_fields.py)
- [tests/test_challenges.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_challenges.py)
- [tests/test_comma2k19.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_comma2k19.py)
- [tests/test_discovery.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_discovery.py)
- [tests/test_fifteen_bits.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_fifteen_bits.py)
- [tests/test_fitting.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_fitting.py)
- [tests/test_real_validation.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_real_validation.py)
- [tests/test_reporting.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_reporting.py)
- [tests/test_tools.py](C:/Users/eeada/OneDrive/Desktop/canary/tests/test_tools.py)
- [tools/run_comma2k19.py](C:/Users/eeada/OneDrive/Desktop/canary/tools/run_comma2k19.py)
- [validation/validate_comma2k19.py](C:/Users/eeada/OneDrive/Desktop/canary/validation/validate_comma2k19.py)

# Public comma2k19 demo

CANary blindly analyzed the public 2017 Toyota RAV4 example using raw CAN and
independent GNSS speed: **53,800 frames, 90 CAN IDs, 579 reference samples**.
It recovered the **0x0AA signal family**, with **r ≈ 0.998667**, **RMSE ≈ 0.448 km/h**
and **R² ≈ 0.997337**. These are in-sample reconstruction metrics on one capture.

The exact layout is observationally ambiguous. Multiple raw layouts are affine
transforms of one another and reconstruct the reference equivalently after fitting.
The public 15-bit definition appears at rank 6; this is not unique reverse engineering
of an exact DBC layout. The agent preserves high signal and low layout confidence.

## Evidence bundle

| Artifact | Purpose |
| --- | --- |
| [Manifest](evidence/manifest.json) | Source snapshot commit, configuration, source paths and SHA-256 hashes |
| [Blind results](evidence/blind_results.json) | Deterministic ranking without DBC access |
| [Validation](evidence/validation.json) | Subsequent comparison against pinned public definitions |
| [Reconstruction](evidence/reconstructed.csv) | Reference, reconstructed values and raw samples |
| [HTML report](evidence/report.html) | Self-contained fitted-candidate evidence and SVG chart |
| [Agent run 1](evidence/agent_run_01.json) | Successful normal public Ollama CLI output and traces |
| [Agent run 2](evidence/agent_run_02.json) | Consecutive successful normal public CLI output and traces |
| [Tests](evidence/tests.txt) | Verified historical full-suite record: 217 passing |

Both live runs used `gpt-oss:120b-cloud`, completed in five turns with zero retries,
and passed evidence validation. These are normal public CLI runs, not debug-wrapper
runs. The bundle preserves original bytes; future generated output belongs in
ignored `results/` rather than overwriting this historical evidence.

## Reproduce and interpret

Follow [complete Windows CMD instructions](../../docs/reproducibility.md).
`python -m tools.run_comma2k19` reads only prepared observations, with nearest
alignment, 0.02-second tolerance and minimum 300 samples. Run
`python -m validation.validate_comma2k19` only after saving the blind result.
Post-discovery validation identifies the public wheel-speed definition; it does not
provide hints to discovery or establish VIN-specific/OEM-authenticated truth.

Source: [dataset provenance](../../datasets/real/comma2k19/provenance.json),
[dataset license](../../datasets/real/comma2k19/SOURCE_LICENSE),
[validation sources](../../validation/comma2k19/README.md) and
[validation license](../../validation/comma2k19/SOURCE_LICENSE).
The source omits original CAN DLC; stored padding cannot be distinguished from
actual trailing zeros. See the [dataset notes](../../datasets/real/comma2k19/README.md).

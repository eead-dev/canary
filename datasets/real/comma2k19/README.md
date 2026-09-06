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
observation CSVs are git-ignored; the scripts, license, provenance, and curated demo
evidence are retained. Local source filenames avoid Windows' forbidden pipe character.

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

## Current capability and evidence

CANary enumerates arbitrary-start 8-, 12-, 15-, and 16-bit signed/unsigned fields
using little-endian and normalized big-endian numbering: 820 candidates per CAN ID.
Blind analysis uses nearest alignment, 0.02-second tolerance, and at least 300 samples.
The recovered 0x0AA signal family has r approximately 0.998667, RMSE 0.448 km/h,
and R² 0.997337. Multiple raw layouts remain affine-equivalent on this capture.
The true public 15-bit layout is present; it is not uniquely identified.

See the [curated demo](../../../examples/comma2k19/README.md),
[reproduction commands](../../../docs/reproducibility.md),
[provenance](provenance.json), and [source license](SOURCE_LICENSE).
Generated CSVs and downloaded arrays remain ignored. Generated analysis output goes
to ignored `results/`; selected historical evidence is preserved under `examples/`.

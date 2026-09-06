# Post-discovery truth sources

These files were retrieved only after the blind result was saved. They are never
imported or accessed by CANary discovery or by `tools.run_comma2k19`.

Pinned opendbc commit: `3e92d112129507debe45364891954db70238997a`.
Exact URLs, hashes, and sizes are in `sources.json`. The MIT license is retained
in `SOURCE_LICENSE`.

- `toyota_2017.dbc`: public shared Toyota definitions; the validator verifies its
  pinned SHA-256 before interpreting the requested signal.
- `vehicle_definitions.txt`: public platform configuration; lines 249-255 associate
  RAV4 2017-18 with `toyota_new_mc_pt_generated`.
- `dbc_composition.txt`: the generated platform DBC imports `_toyota_2017.dbc`.

The dataset's dongle-to-RAV4 mapping and its paper's section IV-A identify the
2017 Toyota RAV4 Platinum. This is sufficient for a public-definition comparison;
no OEM-authenticated or VIN-specific claim is made.

The current definition separates a fault bit from a 15-bit wheel-speed value.
CANary does not enumerate that width. The post-discovery reader is a deliberately
limited, isolated parser for simple SG_ declarations, not a core DBC importer.

`python -m validation.validate_comma2k19` verifies the saved blind CAN input hash,
reads the definition, and checks a full-capture affine raw-value relationship.
It does not rerank candidates or write observation files. The result distinguishes
a wheel-speed proxy from an exact layout match.

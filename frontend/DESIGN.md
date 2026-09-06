# CANary visualization contract — Ticket 20

Written before implementation. Scope: one static-evidence workspace; no backend,
upload, live execution, provider calls or analytical algorithms. The user supplied
the visual direction and authorized implementation; this is an implementation
contract, not a separate generated-image concept exercise.

## Analytical jobs and reading order

Primary job: identify the recovered signal and distinguish signal confidence from
layout confidence. Then compare physical time series, inspect ranked layouts,
understand affine ambiguity, and inspect the agent's evidence use.

Reading path: purpose → real capture → 0x0AA result → reconstruction quality →
layout uncertainty → deterministic evidence versus model judgment. Visible headline:
“Signal recovered. Layout unresolved.” No unique DBC recovery claim.

## Composition

- Desktop (1440 × 1100): compact identity header; 240 px input/context rail;
  dominant result band and reconstruction viewport; bit-layout inspector beside
  ambiguity matrix below; ranking and agent evidence as deeper disclosures.
- Tablet (768 px): rail becomes a settings disclosure; evidence fills the width.
- Mobile portrait (390 × 844, also 360 px): result and metrics first, chart second,
  ambiguity third. Read-only configuration in a native dialog. Bit inspection and
  ranking below; ranking becomes stacked items, not a squeezed table. No horizontal
  page scrolling. Native scroll/pinch, no gesture capture or motion.
- Mobile landscape: same single-column evidence flow, wider chart ticks; no forced
  rotation. Controls never gate the already loaded demo.

## Component and interaction map

App → Header / DemoControls / ResultSummary / ReconstructionChart / AmbiguityView /
BitfieldView / CandidateTable / EvidenceTimeline / AgentInterpretation / Sources.
React owns state and DOM. D3 scale/shape modules own plot geometry. CSS grid owns
byte and matrix geometry; no decoding happens in JavaScript.

Default: curated demo loaded. “Run Toyota RAV4 Demo” reloads static evidence and
resets the inspected candidate. All input fields are visibly read-only. Candidate
buttons update the bitfield inspector and URL `?candidate=<layout-key>`; they do
not rerank evidence or change the saved agent conclusion. Browser back/forward
restores inspection; invalid selection falls back visibly. No other persistence.
Chart pointer inspection and an accessible sample slider expose the same readings.
Keyboard arrows/Home/End on the slider; data available as downloadable CSV.
Expand all equivalent rows, inspect layouts, expand ranking, inspect recorded
provider turns, and open raw source artifacts. Tools remain unavailable in this UI.

## Evidence inventory and local specialist passes

| Layer / job | Data / encoding | Owner and QA |
| --- | --- | --- |
| Reconstruction: does it track GNSS? | 579 saved timestamp/reference/reconstructed/raw rows; linear elapsed seconds and km/h; two SVG paths, solid green reconstruction and dashed neutral reference; direct labels | D3/SVG local pass; no downsampling, four mobile ticks, bounds and focus tests |
| Bitfield: where is this field? | 64 schematic cells, eight labeled byte groups; selected physical bits only, no invented payload values; normalized endian numbering labeled | D3/SVG principles, CSS grid geometry local pass; 15 highlighted cells and cross-byte/endian tests |
| Affine ambiguity: behavior ≠ layout | Selected layout + 11 recorded affine layouts; aligned mini bit strips and saved raw-to-raw relationships/residuals | SVG/DOM local pass; no force graph; selected/expanded/long mobile screenshots |
| Ranking: evidence lookup | Saved order, correlation; join fitted metrics by exact candidate identity, never array position; missing metrics “Not exported” | Semantic HTML table / mobile stacked rows; preserve source ranks, test missing values |
| Agent evidence: who did what? | Actual four tool calls and fifth finalization turn from agent_run_01; decision in turn_trace; fit/equivalence within analyze call | React/semantic ordered list; distinguish real sequence from conceptual workflow; no fabricated fit/compare turns |

Primary route: bespoke SVG + React/DOM. A simple text/CSV path is the fallback;
Canvas/WebGL and a large chart library are unnecessary. One 579-point plot and
at most twelve small 64-bit strips; no continuous animation or repeated decoding.

## Color-role ledger and typography

Background #111716; raised surface #18201e; borders #34413c; main text #edf2ed;
secondary text #bac6be. Selected evidence/reconstructed line #b5dc79 (sage-lime),
neutral dashed reference #c1d0d8, ambiguity #e2b778 (amber). Selection also has
a border/marker and text; ambiguity always includes words. No neon/glows/gradients.
System sans-serif UI, system monospace for exact numbers/IDs/bit positions.
Large result typography, restrained dividers, compact subordinate sections.

## Data boundary and caveats

Source of truth: examples/comma2k19/evidence. Build/dev copies those artifacts with
SHA-256 checks into ignored frontend/public/evidence; no second maintained fixture.
Frontend validates required structural fields, finite numbers, ordered CSV samples
and identities. It formats and plots stored values only. Saved reconstructed.csv
belongs to blind top rank 1, which matches the recorded agent selection; selecting
another layout changes inspection only. Only ten leaders have full exported fits;
10,536 ranked records exist. Show a bounded portion with explicit scope/count.

Use manifest provider/model because provider diagnostics redact part of the model
string. AgentDecision exists in the final successful turn, not a top-level field.
Rationale is stored interpretation, never hidden reasoning. Pinned validation is
post-discovery context only. Missing optional trace/rationale/affine evidence gets
an explicit absent state; missing essential data gets an actionable load error.

## Accessibility and QA

Semantic headings/landmarks/table; skip link; clear keyboard focus; native dialog
with Escape/close and focus return; 44 px controls; color-independent line patterns
and selection labels. SVG title/description and always-visible units/summary.
No required hover, animation, external fonts or external runtime resources.

Tests: parsing/formatting/identity/bit geometry; selected and ambiguous component
rendering; real Playwright demo load, selection/deep link/back, sample inspection,
dialog, empty/missing optional and malformed data. Canonical desktop/mobile,
ambiguity selection/expanded content and absent optional screenshot baselines.
Check overflow at 360/390/768/1440, console errors, contrast, clipping, keyboard
and actual screenshots. Fixed locale/timezone, reduced motion, real curated fixtures.
Check build, backend/evidence hashes, git whitespace and README links. Capture real
desktop/mobile PNGs only after the UI works; update README last.

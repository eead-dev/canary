# Frontend verification and evidence boundaries

## Reproduce

Node.js 22.12+ and npm, from this directory:

```bat
npm ci
npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

`npm run dev` serves the workspace on localhost:5173. `npm run preview` serves
the built static site on localhost:4173. No Python/provider service is required.
Both dev and build package the original curated artifacts after SHA-256 verification.
Do not edit `public/evidence/`; it is ignored generated output.

## Coverage

- 17 unit/component tests use the real curated files: finite/ordered CSV parsing,
  field validation, candidate identity, source ranking, identity-based metric joins,
  decision extraction, affine evidence, missing optional data, escaping, confidence
  rendering, verbatim rationale formatting, and physical bit-diagram orientation.
- Six Playwright scenarios cover load/reload, sample keyboard inspection,
  candidate selection/URL reload/back, settings/Escape/focus return, missing optional
  evidence, and missing essential data with retry.
- Five visual baselines cover desktop, mobile portrait, a selected alternative,
  expanded affine content and absent optional evidence. These are image comparisons,
  not DOM snapshots. Windows Chromium/system-font baselines are checked in.
- Axe scans cover the desktop workspace and open mobile settings dialog. Additional
  checks cover no page overflow at 360/390/768/1440 px and no browser console errors.
- Real [desktop](../docs/assets/screenshots/desktop-workspace.png) and
  [mobile](../docs/assets/screenshots/mobile-workspace.png) screenshots were reviewed
  for chart labels, hierarchy, bit positions, contrast and mobile ordering.

Reduced motion, fixed viewport, locale and timezone make captures repeatable.
Font rasterization differs across operating systems. When introducing another OS,
review its screenshots and use `npm run test:visual:update` to create that platform's
baselines. Do not blindly accept changed screenshots.

## What is displayed

| Source | Consumed evidence |
| --- | --- |
| `blind_results.json` | Frame/ID/sample counts, searched/ranked counts, original ranks and correlations, ten exported fits, selected hypothesis's affine relationships |
| `agent_run_01.json` | Selected layout, exact metrics, confidence, ambiguity, rationale, four actual tool events, five provider turns, decision and validation outcome |
| `reconstructed.csv` | All 579 timestamp/reference/reconstructed/raw samples; elapsed seconds are a display coordinate only |
| `manifest.json` | Provider/model and configuration provenance; SHA-256 checks during packaging |
| `validation.json` | Downloadable post-discovery context, never used to choose/rank the displayed candidate |
| `report.html`, `agent_run_02.json`, `tests.txt` | Preserved source artifacts; report linked from the workspace |

The app never decodes CAN values, correlates, fits, ranks, hydrates a conclusion,
or calculates affine equivalence. Bit mapping is schematic display geometry.
React escapes source text; no model-supplied HTML is injected. Only explicit safe
fields from the recorded tool/provider trace are shown, not hidden reasoning.

## Missing evidence and limitations

- The reconstruction belongs to blind rank #1, matching this recorded agent
  selection. Other candidate time series were not exported. Changing inspection
  never changes the saved reconstruction or conclusion.
- Only ten ranked candidates have exported full fits. Later rows say “Not exported”
  for missing RMSE. Relationship evidence is only labeled where actually recorded;
  other rows say “Not compared.” The table offers the first 10 or 25 original ranks.
- The trace records fitting/comparison within `analyze_candidate`, not separate
  fit/compare turns. Hydration/validation are finalization stages, not fabricated
  additional tool calls. There are no per-step duration measurements to visualize.
- The stored provider trace redacts part of the model string. The model label comes
  from the curated manifest; the UI does not reverse or undo redaction.
- No raw CAN frame payload samples are bundled for this view. The 64-cell diagram
  shows field positions, never invented binary values.
- Confidence is qualitative. High correlation and good reconstruction do not prove
  a unique layout, cross-vehicle accuracy or out-of-sample performance.
- This is a static demo. Read-only controls do not upload files or execute models.

## Implementation references

The design follows the Build Web Data Visualization local router and its SVG,
React, testing, accessibility and mobile-workspace specialist guidance. Stack
integration follows the official [Vite guide](https://vite.dev/guide/),
[Tailwind Vite integration](https://tailwindcss.com/docs/installation/using-vite),
and [Playwright visual comparison documentation](https://playwright.dev/docs/test-snapshots).

"""Self-contained presentation of existing fitted candidate results."""

from html import escape
from pathlib import Path

from .discovery import align_observations
from .fitting import FittedResult, reconstruct
from .observation import CandidateSpec, Frame, candidate_fields, extract_candidate, timestamp_bounds, unique_ids
from .reference import Series
from .analysis import analysis_run
from .relationships import AFFINE_EXPLANATION


def number(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.12g}"


def equation(result: FittedResult) -> str:
    return f"physical = raw * {number(result.scale)} + ({number(result.offset)})"


def layout_text(candidate):
    return (f"0x{candidate.can_id:03X}, start bit {candidate.start_bit}, {candidate.width_bits} bits, "
            f"{candidate.endian}, {'signed' if candidate.signed else 'unsigned'}")


def equivalence_html(results):
    seen, sections = set(), []
    for result in results:
        group = result.equivalence
        if group is None or group.representative in seen:
            continue
        seen.add(group.representative)
        items = ''.join(f'<li>{escape(layout_text(c))}</li>' for c in group.equivalent_candidates)
        sections.append(f'<h3>Representative: {escape(layout_text(group.representative))}</h3>'
                        f'<p>Equivalence count: {group.equivalence_count}. {escape(group.evidence)}.</p>'
                        + (f'<ul>{items}</ul><p>Layout is ambiguous on this capture.</p>' if items
                           else '<p>No exact raw equivalent alternative found in the supported candidate space.</p>'))
    return ''.join(sections)


def affine_html(results, run):
    sections = []
    seen = set()
    for result in results:
        candidate = CandidateSpec(result.start_bit, result.width_bits, result.endian, result.signed, result.can_id)
        if candidate in seen:
            continue
        evidence = run.ambiguity(candidate)
        seen.update([candidate, *(CandidateSpec(**c) for c in evidence['exact_raw_equivalents']),
                     *(CandidateSpec(**e['candidate']) for e in evidence['affine_equivalents'])])
        if not evidence['affine_equivalents']:
            continue
        items = []
        for item in evidence['affine_equivalents']:
            other = CandidateSpec(**item['candidate'])
            items.append(f'<li>{escape(layout_text(other))}: other_raw = '
                         f'{number(item["scale_between_raw"])} * selected_raw + ({number(item["offset_between_raw"])})'
                         f'; RMSE {number(item["rmse_between_raw"])}; max residual {number(item["max_abs_residual"])}'
                         f'; samples {item["sample_count"]}</li>')
        sections.append(f'<h3>Compared from: {escape(layout_text(candidate))}</h3><ul>{"".join(items)}</ul>')
    return (f'<p>{escape(AFFINE_EXPLANATION)}</p>' + ''.join(sections) if sections else
            '<p>No affine-equivalent alternatives for the displayed candidates on identical aligned axes.</p>')


def candidate_details(result: FittedResult) -> list[tuple[str, str]]:
    return [("CAN ID", f"0x{result.can_id:03X}")] + (
            [("Byte offset", str(result.byte_offset))] if result.byte_offset is not None else []) + [
            ("Start bit", str(result.start_bit)), ("Length", f"{result.width_bits} bits"),
            ("Endian", result.endian), ("Signed", "yes" if result.signed else "no (unsigned)"),
            ("Pearson correlation", number(result.correlation)), ("Scale", number(result.scale)),
            ("Offset", number(result.offset)), ("RMSE", number(result.rmse)),
            ("MAE", number(result.mae)), ("R-squared", number(result.r_squared)),
            ("Aligned samples", f"{result.aligned_samples:,}")]


def _chart(rows: list[tuple[float, float, float]], predictions: list[float], name: str) -> str:
    if not rows:
        return '<p>No aligned samples available for chart.</p>'
    times = [t for t, _, _ in rows]
    reference = [y for _, _, y in rows]
    t0, t1 = min(times), max(times)
    lo, hi = min(reference + predictions), max(reference + predictions)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    span_t = t1 - t0 or 1
    span_y = hi - lo

    def points(values: list[float]) -> str:
        return " ".join(f"{75 + (t-t0)/span_t*870:.2f},{330-(v-lo)/span_y*275:.2f}"
                        for t, v in zip(times, values))

    grid = []
    for i in range(6):
        y = 330 - i * 55
        x = 75 + i * 174
        grid.append(f'<path d="M75 {y}H945" stroke="#dce4eb"/>'
                    f'<text x="65" y="{y+4}" text-anchor="end">{lo+i*span_y/5:.4g}</text>'
                    f'<text x="{x}" y="353" text-anchor="middle">{t0+i*(t1-t0)/5:.4g}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 405" role="img"
 aria-labelledby="chart-title chart-description">
<title id="chart-title">Reference and reconstructed physical values</title>
<desc id="chart-description">{len(rows):,} aligned samples for {escape(name)}; candidate timestamps in seconds.</desc>
<g font-family="system-ui, sans-serif" font-size="12" fill="#42576b">{''.join(grid)}
<text x="75" y="25">Physical value: {escape(name)}</text>
<text x="510" y="385" text-anchor="middle">Time (seconds)</text></g>
<polyline id="reference-line" points="{points(reference)}" fill="none" stroke="#1664b0" stroke-width="2.8"/>
<polyline id="reconstructed-line" points="{points(predictions)}" fill="none" stroke="#c95320" stroke-width="1.7" stroke-dasharray="7 4"/>
</svg>'''


def write_report(path: str | Path, frames: list[Frame], reference: Series,
                 results: list[FittedResult], reference_name: str, *, tolerance: float = 0.0, alignment: str | None = None, run=None) -> None:
    """Write static HTML for fitted results in their existing ranked order."""
    if not results:
        raise ValueError("no fitted candidate available for report")
    best = results[0]
    run = analysis_run(frames, reference, tolerance, alignment, run)
    rows = run.rows(CandidateSpec(best.start_bit, best.width_bits, best.endian, best.signed, best.can_id))
    predictions = reconstruct([x for _, x, _ in rows], best.scale, best.offset)
    bounds = timestamp_bounds(frames)
    duration = number(bounds[1] - bounds[0]) if bounds else "N/A"
    ids = unique_ids(frames)
    details = ''.join(f'<div><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
                      for label, value in candidate_details(best))
    table = []
    for rank, result in enumerate(results, 1):
        values = [str(rank), f"0x{result.can_id:03X}", str(result.byte_offset) if result.byte_offset is not None else "—",
                  str(result.start_bit), str(result.width_bits), result.endian,
                  "yes" if result.signed else "no", number(result.correlation),
                  number(result.scale), number(result.offset), number(result.rmse),
                  number(result.mae), number(result.r_squared), str(result.aligned_samples),
                  str(result.equivalence.equivalence_count) if result.equivalence else "N/A"]
        table.append('<tr>' + ''.join(f'<td>{escape(v)}</td>' for v in values) + '</tr>')
    headers = ("Rank", "CAN ID", "Byte", "Start bit", "Bits", "Endian", "Signed", "Pearson r",
               "Scale", "Offset", "RMSE", "MAE", "R-squared", "Samples", "Equivalent layouts")
    performance = ''.join(f'<li>{escape(k)}: {escape(str(v))}</li>' for k, v in run.statistics().items())
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CANary Signal Discovery Report</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#edf2f6;color:#182b3b;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1280px;margin:40px auto;padding:0 24px}}header{{border-top:5px solid #1664b0;padding:24px 0}}
h1{{font-size:34px;line-height:1.2;margin:10px 0}}h2{{font-size:22px;margin-top:0}}.eyebrow{{letter-spacing:2px;font-size:12px;font-weight:700}}
section{{background:white;padding:28px;margin:20px 0;border:1px solid #dce4eb;border-radius:12px}}
.summary,dl{{display:flex;flex-wrap:wrap;gap:20px 36px}}dl div{{min-width:145px}}dt{{font-size:13px;color:#52687b}}dd{{margin:0;font-weight:650;overflow-wrap:anywhere}}
code{{display:block;background:#edf4fa;padding:16px;border-radius:6px;overflow-wrap:anywhere}}svg{{width:100%;height:auto}}
.legend{{display:flex;gap:24px;flex-wrap:wrap}}.ref{{color:#1664b0}}.rec{{color:#c95320}}.muted{{color:#52687b;font-size:14px}}
.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;font-size:13px;white-space:nowrap;width:100%}}th,td{{padding:10px;text-align:right;border-bottom:1px solid #dce4eb}}th{{background:#edf4fa}}tbody tr:first-child{{background:#f0f7ff}}
@media print{{body{{background:white}}main{{margin:0}}section{{break-inside:avoid}}}}
</style></head><body><main>
<header><div class="eyebrow">CANary / DETERMINISTIC ANALYSIS</div><h1>CANary Signal Discovery Report</h1>
<p>Reference: <strong>{escape(reference_name)}</strong></p></header>
<section><h2>Capture summary</h2><div class="summary">
<span>CAN frames: <strong>{len(frames):,}</strong></span><span>Unique CAN IDs: <strong>{len(ids)}</strong></span>
<span>Candidates searched: <strong>{len(ids)*len(candidate_fields())}</strong></span>
<span>Capture duration: <strong>{duration} s</strong></span>
<span>Aligned samples (best): <strong>{best.aligned_samples:,}</strong></span></div>
<p class="muted">Timestamp tolerance: {number(tolerance)} s. Showing {len(results)} fitted candidates in absolute-correlation order.</p></section>
<section><h2>Best candidate</h2><dl>{details}</dl><h3>Fitted equation</h3><code>{escape(equation(best))}</code>
<p class="muted">Start bit: normalized LSB0 for little-endian, MSB0 for big-endian (not DBC sawtooth).
Byte offset is shown only for byte-aligned starts. Endianness is immaterial only for byte-aligned 8-bit fields.</p></section>
<section><h2>Reference vs reconstruction</h2><div class="legend"><span class="ref">━ Reference</span>
<span class="rec">┄ Reconstructed</span></div>{_chart(rows, predictions, reference_name)}
<p class="muted">All {len(rows):,} aligned samples are plotted at candidate timestamps. Nearly identical curves may overlap.
Metrics describe the same samples used for fitting; correlation does not establish signal identity.</p></section>
<section><h2>Top candidates</h2><div class="table-wrap"><table><thead><tr>
{''.join(f'<th scope="col">{h}</th>' for h in headers)}</tr></thead><tbody>{''.join(table)}</tbody></table></div></section>
<section><h2>Equivalent layouts</h2>{equivalence_html(results)}</section>
<section><h2>Affine-equivalent reconstructions</h2>{affine_html(results, run)}
<p>Criterion: at least three nonconstant samples; every raw-to-raw residual at most 1e-8 raw units.
Comparisons require identical aligned timestamp axes. Evidence applies only to this capture.</p></section>
<section><h2>Search performance</h2><ul>{performance}</ul></section>
</main></body></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")

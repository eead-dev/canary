import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import {
  parseEvidence,
  parseSeries,
  candidate,
  candidateKey,
  canId,
  layoutLabel,
  metric,
  displayBits,
} from "./evidence";
import {
  ResultSummary,
  AmbiguityView,
  BitfieldView,
  EvidenceTimeline,
} from "./components";
const root = new URL("../../examples/comma2k19/evidence/", import.meta.url);
const read = (name: string) => readFileSync(new URL(name, root), "utf8");
const blind = JSON.parse(read("blind_results.json")),
  agent = JSON.parse(read("agent_run_01.json")),
  manifest = JSON.parse(read("manifest.json"));
const csv = read("reconstructed.csv");
const data = parseEvidence(blind, agent, manifest, csv);
describe("Evidence boundary", () => {
  it("consumes the actual selected candidate and metrics", () => {
    expect(data.selected).toEqual({
      can_id: 170,
      start_bit: 34,
      width_bits: 15,
      endian: "big",
      signed: true,
    });
    expect(data.metrics.rmse).toBe(agent.conclusion.rmse);
    expect(data.samples).toHaveLength(579);
    expect(data.ranked).toHaveLength(10536);
  });
  it("preserves original ranking and joins fits by identity", () => {
    expect(data.ranked.map((c) => c.rank)).toEqual(
      blind.ranked_candidates.map((c: { rank: number }) => c.rank),
    );
    expect(data.ranked[5].fit?.offset).toBe(blind.top_fitted[5].offset);
    expect(data.ranked[24].fit).toBeUndefined();
  });
  it("extracts the actual decision and tool sequence", () => {
    expect(data.decision?.candidate_ref).toBe("cand_0001");
    expect(data.tools.map((t) => t.name)).toEqual([
      "summarize_capture",
      "list_can_ids",
      "search_candidates",
      "analyze_candidate",
    ]);
    expect(data.turns[4].validation).toBe("passed");
    expect(data.model).toBe(manifest.agent.model);
  });
  it("preserves affine relationships rather than calculating them", () => {
    expect(data.affine).toHaveLength(11);
    expect(data.affine[0].scale_between_raw).toBe(0.5);
    expect(data.affine[0].max_abs_residual).toBe(0);
  });
  it("rejects non-finite, unordered and malformed CSV values", () => {
    for (const value of [
      "timestamp,reference,reconstructed,raw\n1,NaN,2,3\n2,1,2,3",
      "timestamp,reference,reconstructed,raw\n2,1,2,3\n1,1,2,3",
      "bad,header\n1,2",
      "timestamp,reference,reconstructed,raw\n1,,2,3\n2,1,2,3",
    ])
      expect(() => parseSeries(value)).toThrow();
  });
  it("rejects an incomplete/failed essential record", () => {
    expect(() => parseEvidence({}, agent, manifest, csv)).toThrow();
    expect(() =>
      parseEvidence(blind, { ...agent, status: "max_turns" }, manifest, csv),
    ).toThrow();
  });
  it("handles missing optional evidence explicitly", () => {
    const partial = parseEvidence(
      { ...blind, distinct_hypotheses: [] },
      {
        ...agent,
        trace: [],
        turn_trace: [],
        conclusion: { ...agent.conclusion, rationale: undefined },
      },
      manifest,
      csv,
    );
    expect(partial.rationale).toBeUndefined();
    expect(partial.affine).toEqual([]);
    expect(partial.decision).toBeUndefined();
    expect(renderToStaticMarkup(<EvidenceTimeline data={partial} />)).toContain(
      "Tool trace not included",
    );
  });
});
describe("Presentation and bit geometry", () => {
  it("formats metrics without inventing absent values", () => {
    expect(metric(0.44796295043)).toBe("0.448");
    expect(metric(undefined)).toBe("Not exported");
    expect(metric(NaN)).toBe("Not exported");
    expect(canId(170)).toBe("0x0AA");
  });
  it("formats and identifies candidates including signedness", () => {
    expect(layoutLabel(data.selected)).toBe(
      "start 34 · 15-bit · big-endian · signed",
    );
    expect(candidateKey(data.selected)).not.toBe(
      candidateKey({ ...data.selected, signed: false }),
    );
  });
  it("maps normalized BE positions without inventing bit values", () => {
    expect(displayBits(data.selected)).toEqual(
      Array.from({ length: 15 }, (_, i) => i + 34),
    );
  });
  it("maps LE byte orientation for the physical diagram", () => {
    expect(
      displayBits({
        ...data.selected,
        start_bit: 5,
        width_bits: 8,
        endian: "little",
      }),
    ).toEqual([2, 1, 0, 15, 14, 13, 12, 11]);
  });
  it("rejects invalid candidate geometry", () => {
    expect(() => candidate({ ...data.selected, start_bit: 60 })).toThrow();
    expect(() => candidate({ ...data.selected, signed: "false" })).toThrow();
  });
  it("renders the selected signal and confidence separately", () => {
    const html = renderToStaticMarkup(<ResultSummary data={data} />);
    expect(html).toContain("0x0AA");
    expect(html).toContain("HIGH");
    expect(html).toContain("LOW");
    expect(html).toContain("LAYOUT AMBIGUOUS");
    expect(html).toContain("0.448");
  });
  it("renders ambiguity and the recorded count", () => {
    const html = renderToStaticMarkup(
      <AmbiguityView
        data={data}
        inspected={data.selected}
        onSelect={() => {}}
      />,
    );
    expect(html).toContain("11");
    expect(html).toContain(
      "Ambiguity is a valid analytical result, not an error.",
    );
    expect(html).toContain("Explore all 12 layouts");
  });
  it("highlights exactly the selected field width", () => {
    const html = renderToStaticMarkup(
      <BitfieldView data={data} value={data.selected} />,
    );
    expect(html.match(/data-selected="true"/g)).toHaveLength(15);
    expect(html).toContain("not DBC sawtooth");
  });
  it("structures the stored rationale without changing its wording", () => {
    const html = renderToStaticMarkup(<EvidenceTimeline data={data} />);
    const points = [...html.matchAll(/class="interpretation-point-text">(.*?)<\/p>/g)]
      .map(match => match[1]);
    expect(points).toHaveLength(2);
    expect(points.join(" ")).toBe(data.rationale);
    expect(points[0]).toContain("0.9987");
  });
  it("escapes model rationale as text", () => {
    const html = renderToStaticMarkup(
      <EvidenceTimeline
        data={{ ...data, rationale: '<script>alert("x")</script>' }}
      />,
    );
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

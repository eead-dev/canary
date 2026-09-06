export interface Candidate {
  can_id: number;
  start_bit: number;
  width_bits: number;
  endian: "big" | "little";
  signed: boolean;
}
export interface Metrics {
  correlation: number;
  scale: number;
  offset: number;
  rmse: number;
  mae: number;
  r_squared: number;
}
export interface Ranked extends Candidate {
  rank: number;
  correlation: number;
  fit?: Metrics;
}
export interface Affine {
  candidate: Candidate;
  relationship_type: string;
  scale_between_raw: number;
  offset_between_raw: number;
  rmse_between_raw: number;
  max_abs_residual: number;
  sample_count: number;
}
export interface Sample {
  timestamp: number;
  reference: number;
  reconstructed: number;
  raw: number;
}
export interface Decision {
  candidate_ref: string;
  alternative_refs: string[];
  signal_confidence: string;
  layout_confidence: string;
  layout_ambiguous: boolean;
}
export interface Turn {
  turn: number;
  phase: string;
  response_kind: string;
  tool_call_count: number;
  validation: string;
  decision?: Decision;
}
export interface ToolEvent {
  name: string;
  id: string;
  ok: boolean;
}
export interface Evidence {
  selected: Candidate;
  metrics: Metrics;
  chartCandidate: Candidate;
  samples: Sample[];
  ranked: Ranked[];
  affine: Affine[];
  exact: Candidate[];
  rationale?: string;
  signalConfidence: string;
  layoutConfidence: string;
  ambiguous: boolean;
  frames: number;
  ids: number;
  referenceSamples: number;
  duration: number;
  searched: number;
  turns: Turn[];
  tools: ToolEvent[];
  attempts: number;
  retries: number;
  status: string;
  config: {
    alignment: string;
    timestamp_tolerance: number;
    min_samples: number;
  };
  provider: string;
  model: string;
  decision?: Decision;
  sourceCommit: string;
}
type ObjectValue = Record<string, unknown>;
function object(v: unknown, field: string): ObjectValue {
  if (!v || typeof v !== "object" || Array.isArray(v))
    throw new Error(`Missing or invalid ${field}`);
  return v as ObjectValue;
}
function number(v: unknown, field: string): number {
  if (typeof v !== "number" || !Number.isFinite(v))
    throw new Error(`Invalid numeric ${field}`);
  return v;
}
function string(v: unknown, field: string): string {
  if (typeof v !== "string") throw new Error(`Invalid ${field}`);
  return v;
}
function array(v: unknown, field: string): unknown[] {
  if (!Array.isArray(v)) throw new Error(`Missing ${field}`);
  return v;
}
export function candidate(value: unknown): Candidate {
  const c = object(value, "candidate");
  const can_id = number(c.can_id, "CAN ID"),
    start_bit = number(c.start_bit, "start bit"),
    width_bits = number(c.width_bits, "width");
  if (
    !Number.isInteger(can_id) ||
    can_id < 0 ||
    can_id > 2047 ||
    !Number.isInteger(start_bit) ||
    start_bit < 0 ||
    ![8, 12, 15, 16].includes(width_bits) ||
    start_bit + width_bits > 64 ||
    !["big", "little"].includes(String(c.endian)) ||
    typeof c.signed !== "boolean"
  )
    throw new Error("Invalid candidate layout");
  return {
    can_id,
    start_bit,
    width_bits,
    endian: c.endian as Candidate["endian"],
    signed: c.signed,
  };
}
function metrics(value: unknown): Metrics {
  const v = object(value, "fit");
  return Object.fromEntries(
    ["correlation", "scale", "offset", "rmse", "mae", "r_squared"].map((k) => [
      k,
      number(v[k], k),
    ]),
  ) as unknown as Metrics;
}
export const candidateKey = (c: Candidate) =>
  `${c.can_id}-${c.start_bit}-${c.width_bits}-${c.endian}-${c.signed ? "s" : "u"}`;
export const canId = (id: number) =>
  `0x${id.toString(16).toUpperCase().padStart(3, "0")}`;
export const layoutLabel = (c: Candidate) =>
  `start ${c.start_bit} · ${c.width_bits}-bit · ${c.endian}-endian · ${c.signed ? "signed" : "unsigned"}`;
export const metric = (v: number | undefined, digits = 3) =>
  v === undefined || !Number.isFinite(v) ? "Not exported" : v.toFixed(digits);
// Geometry only. Cell columns are physical MSB → LSB within each byte.
// The normalized BE index is already in that display order; LE reverses each byte.
export const displayBits = (c: Candidate) =>
  Array.from({ length: c.width_bits }, (_, i) => {
    const bit = c.start_bit + i;
    return c.endian === "big" ? bit : Math.floor(bit / 8) * 8 + 7 - (bit % 8);
  });
export function parseSeries(csv: string): Sample[] {
  const lines = csv.trim().split(/\r?\n/);
  if (lines.shift() !== "timestamp,reference,reconstructed,raw")
    throw new Error("Unexpected reconstruction CSV columns");
  const samples = lines.map((row, i) => {
    const cells = row.split(",");
    if (
      cells.length !== 4 ||
      cells.some((v) => !v.trim() || !Number.isFinite(Number(v)))
    )
      throw new Error(`Invalid reconstruction row ${i + 2}`);
    const [timestamp, reference, reconstructed, raw] = cells.map(Number);
    return { timestamp, reference, reconstructed, raw };
  });
  if (
    samples.length < 2 ||
    samples.some((s, i) => i > 0 && s.timestamp <= samples[i - 1].timestamp)
  )
    throw new Error("Reconstruction requires ordered samples");
  return samples;
}
export function parseEvidence(
  blindValue: unknown,
  agentValue: unknown,
  manifestValue: unknown,
  csv: string,
): Evidence {
  const blind = object(blindValue, "blind results"),
    agent = object(agentValue, "agent run"),
    manifest = object(manifestValue, "manifest");
  const conclusion = object(agent.conclusion, "validated conclusion");
  if (agent.status !== "complete")
    throw new Error("The recorded agent run did not complete");
  const selected = candidate(conclusion.selected_candidate);
  const fits = array(blind.top_fitted, "fitted leaders").map((v) => ({
    ...candidate(v),
    ...metrics(v),
  }));
  if (!fits.length) throw new Error("No exported fitted candidates");
  const fitMap = new Map(fits.map((f) => [candidateKey(f), f]));
  const ranked = array(blind.ranked_candidates, "ranked candidates").map(
    (v) => {
      const r = object(v, "ranked candidate"),
        c = candidate(r);
      return {
        ...c,
        rank: number(r.rank, "rank"),
        correlation: number(r.correlation, "correlation"),
        fit: fitMap.get(candidateKey(c)),
      };
    },
  );
  if (!ranked.some((c) => candidateKey(c) === candidateKey(selected)))
    throw new Error("Selected candidate absent from ranking");
  const hypothesis = (
    Array.isArray(blind.distinct_hypotheses) ? blind.distinct_hypotheses : []
  )
    .map((v) => object(v, "hypothesis"))
    .find((h) => candidateKey(candidate(h)) === candidateKey(selected));
  const affine = (
    Array.isArray(hypothesis?.affine_equivalents)
      ? hypothesis.affine_equivalents
      : []
  ).map((v) => {
    const a = object(v, "affine evidence");
    return {
      candidate: candidate(a.candidate),
      relationship_type: string(a.relationship_type, "relationship"),
      ...Object.fromEntries(
        [
          "scale_between_raw",
          "offset_between_raw",
          "rmse_between_raw",
          "max_abs_residual",
          "sample_count",
        ].map((k) => [k, number(a[k], k)]),
      ),
    } as Affine;
  });
  const turns = (Array.isArray(agent.turn_trace) ? agent.turn_trace : []).map(
    (v) => {
      const t = object(v, "turn");
      let decision: Decision | undefined;
      if (t.decision) {
        const d = object(t.decision, "decision");
        decision = {
          candidate_ref: string(d.candidate_ref, "candidate ref"),
          alternative_refs: array(d.alternative_refs, "alternative refs").map(
            (v) => string(v, "ref"),
          ),
          signal_confidence: string(d.signal_confidence, "signal confidence"),
          layout_confidence: string(d.layout_confidence, "layout confidence"),
          layout_ambiguous: d.layout_ambiguous === true,
        };
      }
      return {
        turn: number(t.turn, "turn"),
        phase: string(t.phase, "phase"),
        response_kind: string(t.response_kind, "response kind"),
        tool_call_count: number(t.tool_call_count, "tool calls"),
        validation: string(t.validation, "validation"),
        decision,
      };
    },
  );
  const tools = (Array.isArray(agent.trace) ? agent.trace : []).map((v) => {
    const t = object(v, "tool event");
    return {
      name: string(t.name, "tool name"),
      id: string(t.id, "tool ID"),
      ok: object(t.output, "tool output").ok === true,
    };
  });
  const config = object(agent.analysis_config, "analysis config"),
    provider = object(manifest.agent, "provider metadata");
  return {
    selected,
    metrics: metrics(conclusion),
    chartCandidate: candidate(fits[0]),
    samples: parseSeries(csv),
    ranked,
    affine,
    exact: (Array.isArray(conclusion.equivalent_layouts)
      ? conclusion.equivalent_layouts
      : []
    ).map(candidate),
    rationale:
      typeof conclusion.rationale === "string"
        ? conclusion.rationale
        : undefined,
    signalConfidence: string(conclusion.signal_confidence, "signal confidence"),
    layoutConfidence: string(conclusion.layout_confidence, "layout confidence"),
    ambiguous: conclusion.layout_ambiguous === true,
    frames: number(blind.frame_count, "frame count"),
    ids: array(blind.unique_can_ids, "CAN IDs").length,
    referenceSamples: number(blind.reference_samples, "reference samples"),
    duration: number(blind.capture_duration_seconds, "duration"),
    searched: number(
      object(blind.performance, "performance").candidates_enumerated,
      "searched candidates",
    ),
    turns,
    tools,
    decision: turns.findLast((t) => t.decision)?.decision,
    attempts: number(agent.provider_attempts, "attempts"),
    retries: number(agent.retry_count, "retries"),
    status: string(agent.status, "status"),
    config: {
      alignment: string(config.alignment, "alignment"),
      timestamp_tolerance: number(config.timestamp_tolerance, "tolerance"),
      min_samples: number(config.min_samples, "minimum samples"),
    },
    provider: string(provider.provider, "provider"),
    model: string(provider.model, "model"),
    sourceCommit: string(manifest.source_snapshot_commit, "source commit"),
  };
}
export const evidenceUrl = (name: string) =>
  `${import.meta.env.BASE_URL}evidence/${name}`;
export async function loadEvidence(): Promise<Evidence> {
  const names = [
    "blind_results.json",
    "agent_run_01.json",
    "manifest.json",
    "reconstructed.csv",
  ];
  const data = await Promise.all(
    names.map(async (name) => {
      const response = await fetch(evidenceUrl(name));
      if (!response.ok)
        throw new Error(`Cannot load ${name} (${response.status})`);
      return response.text();
    }),
  );
  return parseEvidence(
    JSON.parse(data[0]),
    JSON.parse(data[1]),
    JSON.parse(data[2]),
    data[3],
  );
}

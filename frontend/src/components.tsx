import { useState } from "react";
import {
  canId,
  candidateKey,
  displayBits,
  evidenceUrl,
  layoutLabel,
  metric,
  type Candidate,
  type Evidence,
} from "./evidence";

export function ResultSummary({ data }: { data: Evidence }) {
  return (
    <section className="result" aria-labelledby="result-heading">
      <div className="result-top">
        <p className="eyebrow">
          Discovery result <span>/ verified evidence</span>
        </p>
        <span className="status">
          <span aria-hidden="true">✓</span> Validated conclusion
        </span>
      </div>
      <div className="result-body">
        <div className="signal-identity">
          <span className="overline">Recovered CAN message</span>
          <h1 id="result-heading">{canId(data.selected.can_id)}</h1>
          <p className="encoding">{layoutLabel(data.selected)}</p>
        </div>
        <div className="result-meaning">
          <h2>
            Signal recovered.
            <br />
            <span>Layout unresolved.</span>
          </h2>
          <p>
            CANary recovered the wheel-speed signal family while preserving
            uncertainty in the exact bit layout.
          </p>
          <div className="confidence">
            <span>
              Signal <strong>{data.signalConfidence.toUpperCase()}</strong>
            </span>
            <span>
              Layout{" "}
              <strong className="amber-text">
                {data.layoutConfidence.toUpperCase()}
              </strong>
            </span>
            <span className="ambiguity-badge">
              {data.ambiguous ? "LAYOUT AMBIGUOUS" : "LAYOUT RESOLVED"}
            </span>
          </div>
        </div>
      </div>
      <div className="metrics-strip">
        <div className="primary-metric">
          <span>
            Correlation <i>r</i>
          </span>
          <strong>{metric(data.metrics.correlation, 4)}</strong>
        </div>
        <div>
          <span>
            Reconstruction error <i>RMSE</i>
          </span>
          <strong>
            {metric(data.metrics.rmse)} <small>km/h</small>
          </strong>
        </div>
        <div>
          <span>
            Explained variance <i>R²</i>
          </span>
          <strong>{metric(data.metrics.r_squared, 4)}</strong>
        </div>
        <p>
          Independent GNSS reference.
          <br />
          Deterministic measurements.
        </p>
      </div>
    </section>
  );
}

export function MiniBits({ value }: { value: Candidate }) {
  const selected = new Set(displayBits(value));
  return (
    <span className="mini-bits" aria-hidden="true">
      {Array.from({ length: 64 }, (_, i) => (
        <span
          key={i}
          className={`${selected.has(i) ? "filled" : ""} ${i % 8 === 0 ? "byte-start" : ""}`}
        />
      ))}
    </span>
  );
}

export function BitfieldView({
  value,
  data,
}: {
  value: Candidate;
  data: Evidence;
}) {
  const bits = new Set(displayBits(value)),
    selected = candidateKey(value) === candidateKey(data.selected);
  const ranked = data.ranked.find(
    (c) => candidateKey(c) === candidateKey(value),
  );
  return (
    <section
      className="bitfield-section"
      id="layout"
      aria-labelledby="layout-heading"
    >
      <div className="section-top">
        <div>
          <p className="eyebrow">03 / Encoding inspector</p>
          <h2 id="layout-heading">Inside the CAN frame</h2>
        </div>
        <span className="tag">
          {selected
            ? "Agent selection"
            : `Inspecting rank #${ranked?.rank ?? "—"}`}
        </span>
      </div>
      <div className="inspected-layout">
        <strong className="mono">{canId(value.can_id)}</strong>
        <span>{layoutLabel(value)}</span>
      </div>
      <div
        className="bit-grid"
        role="img"
        aria-label={`${canId(value.can_id)}: ${value.width_bits} bits highlighted from normalized start ${value.start_bit}, ${value.endian}-endian, ${value.signed ? "signed" : "unsigned"}. Eight bytes shown with physical MSB at left.`}
      >
        {Array.from({ length: 8 }, (_, byte) => (
          <div className="byte-group" key={byte}>
            <div className="byte-label">
              BYTE {byte.toString().padStart(2, "0")}
            </div>
            <div className="byte-cells">
              {Array.from({ length: 8 }, (_, i) => {
                const bit = byte * 8 + i;
                const normalized =
                  value.endian === "big" ? bit : byte * 8 + 7 - i;
                return (
                  <span
                    data-selected={bits.has(bit)}
                    className={`bit ${bits.has(bit) ? "selected-bit" : ""} ${normalized === value.start_bit ? "start-bit" : ""}`}
                    key={bit}
                  >
                    {normalized === value.start_bit ? (
                      <span className="start-marker">{normalized}</span>
                    ) : (
                      normalized
                    )}
                  </span>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="bit-caption">
        <span className="accent-text">■ Selected {value.width_bits} bits</span>{" "}
        · Start {value.start_bit} · End {value.start_bit + value.width_bits - 1}
      </p>
      <p className="muted small">
        Physical byte order: MSB → LSB.{" "}
        {value.endian === "big"
          ? "Normalized big-endian indices increase left to right; not DBC sawtooth numbering."
          : "Little-endian indices increase LSB to MSB within each byte."}{" "}
        Schematic field positions, not payload values.
      </p>
      <div className="fit-equation">
        <span className="overline">
          {selected
            ? "Selected fitted relationship"
            : "Exported fitted relationship"}
        </span>
        {ranked?.fit ? (
          <>
            <code>
              physical = raw × {metric(ranked.fit.scale, 8)}
              <br />
              {ranked.fit.offset < 0 ? "−" : "+"}{" "}
              {metric(Math.abs(ranked.fit.offset), 6)}
            </code>
            <div className="fit-stats">
              <span>
                RMSE <b>{metric(ranked.fit.rmse)}</b>
              </span>
              <span>
                MAE <b>{metric(ranked.fit.mae)}</b>
              </span>
              <span>
                R² <b>{metric(ranked.fit.r_squared, 4)}</b>
              </span>
            </div>
          </>
        ) : (
          <p>Fit metrics were not exported for this candidate.</p>
        )}
      </div>
      {!selected && (
        <p className="small amber-text">
          Inspection only. The agent conclusion and saved reconstruction remain
          unchanged.
        </p>
      )}
    </section>
  );
}

export function AmbiguityView({
  data,
  inspected,
  onSelect,
}: {
  data: Evidence;
  inspected: Candidate;
  onSelect: (c: Candidate) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const rows = [
    { candidate: data.selected, primary: true },
    ...data.affine.map((a) => ({ ...a, primary: false })),
  ];
  return (
    <section
      className="ambiguity-section"
      id="ambiguity"
      aria-labelledby="ambiguity-heading"
    >
      <div className="section-top">
        <div>
          <p className="eyebrow">02 / What remains uncertain</p>
          <h2 id="ambiguity-heading">Same behavior. Different bits.</h2>
        </div>
        <span className="ambiguity-count">
          {data.affine.length ? data.affine.length + 1 : "—"}
          <small>layouts</small>
        </span>
      </div>
      <p className="ambiguity-intro">
        {data.ambiguous
          ? "The signal is strongly identified. Its exact encoding is not."
          : "No layout ambiguity recorded."}{" "}
        {data.affine.length > 0 && (
          <>
            The selected layout and{" "}
            <strong>{data.affine.length} affine alternatives</strong> carry the
            same information on this capture.
          </>
        )}
      </p>
      <div className="matrix-axis">
        <span>Normalized layout</span>
        <span>
          0 <i>32</i> 63
        </span>
      </div>
      <div className="layout-matrix">
        {(expanded ? rows : rows.slice(0, 5)).map((row) => (
          <button
            key={candidateKey(row.candidate)}
            className={`layout-row ${candidateKey(inspected) === candidateKey(row.candidate) ? "is-inspected" : ""}`}
            aria-pressed={
              candidateKey(inspected) === candidateKey(row.candidate)
            }
            onClick={() => onSelect(row.candidate)}
            aria-label={`Inspect ${layoutLabel(row.candidate)}`}
          >
            <span className="matrix-label">
              <b>
                {row.candidate.start_bit}
                <span> / </span>
                {row.candidate.width_bits}
              </b>
              <small>
                {row.candidate.endian.toUpperCase()} ·{" "}
                {row.candidate.signed ? "signed" : "unsigned"}
                {row.primary ? " · selected" : ""}
              </small>
            </span>
            <MiniBits value={row.candidate} />
            <span className="row-arrow" aria-hidden="true">
              ↗
            </span>
          </button>
        ))}
      </div>
      {rows.length > 5 && (
        <button
          className="text-button expand-layouts"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          {expanded
            ? "Show fewer layouts"
            : `Explore all ${rows.length} layouts`}{" "}
          <span aria-hidden="true">{expanded ? "−" : "+"}</span>
        </button>
      )}
      {!data.affine.length && (
        <p className="muted">
          Affine comparison evidence was not exported. Absence of evidence does
          not establish a unique layout.
        </p>
      )}
      {data.affine.length > 0 && (
        <details className="raw-relations">
          <summary>Inspect recorded raw-to-raw relationships</summary>
          <p className="small muted">
            Direction: alternative raw = a × selected raw + b. Values below come
            from deterministic evidence, not a frontend fit.
          </p>
          {data.affine.map((a) => (
            <div className="raw-relation" key={candidateKey(a.candidate)}>
              <span>{layoutLabel(a.candidate)}</span>
              <code>
                raw = {a.scale_between_raw} × selected{" "}
                {a.offset_between_raw < 0 ? "−" : "+"}{" "}
                {Math.abs(a.offset_between_raw)}
              </code>
              <small>
                RMSE {a.rmse_between_raw} · max residual {a.max_abs_residual} ·{" "}
                {a.sample_count} samples
              </small>
            </div>
          ))}
        </details>
      )}
      <div className="ambiguity-note">
        <span aria-hidden="true">≈</span>
        <p>
          Different raw values; equivalent physical reconstruction after
          fitting.
          <strong>Ambiguity is a valid analytical result, not an error.</strong>
        </p>
      </div>
    </section>
  );
}

export function CandidateTable({
  data,
  inspected,
  onSelect,
}: {
  data: Evidence;
  inspected: Candidate;
  onSelect: (c: Candidate) => void;
}) {
  const [more, setMore] = useState(false);
  const affine = new Set(data.affine.map((a) => candidateKey(a.candidate))),
    exact = new Set(data.exact.map(candidateKey));
  const relation = (c: Candidate) =>
    candidateKey(c) === candidateKey(data.selected)
      ? "Agent selection"
      : affine.has(candidateKey(c))
        ? "Affine equivalent"
        : exact.has(candidateKey(c))
          ? "Exact equivalent"
          : "Not compared";
  return (
    <section className="ranking-section" id="candidates">
      <div className="section-top">
        <div>
          <p className="eyebrow">04 / Candidate evidence</p>
          <h2>Ranked, not guessed.</h2>
        </div>
        <span className="tag">
          {data.searched.toLocaleString("en-US")} searched
        </span>
      </div>
      <p className="muted small">
        Original deterministic order · showing {more ? 25 : 10} of{" "}
        {data.ranked.length.toLocaleString("en-US")} ranked layouts. Only
        exported fits are shown; no metrics are inferred.
      </p>
      <table className="candidate-table">
        <caption className="sr-only">
          Ranked candidate evidence. Select a candidate to inspect its bits.
          Correlation order is unchanged.
        </caption>
        <thead>
          <tr>
            {[
              "Rank",
              "CAN ID",
              "Start",
              "Width",
              "Endian",
              "Signed",
              "Correlation",
              "RMSE",
              "Relationship",
            ].map((h) => (
              <th scope="col" key={h}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.ranked.slice(0, more ? 25 : 10).map((c) => (
            <tr
              key={candidateKey(c)}
              className={
                candidateKey(c) === candidateKey(inspected) ? "active-row" : ""
              }
            >
              <td data-label="Rank">
                <button
                  onClick={() => onSelect(c)}
                  aria-label={`Inspect rank ${c.rank}`}
                  aria-pressed={candidateKey(c) === candidateKey(inspected)}
                >
                  #{c.rank} <span aria-hidden="true">↗</span>
                </button>
              </td>
              <td data-label="CAN ID">{canId(c.can_id)}</td>
              <td data-label="Start">{c.start_bit}</td>
              <td data-label="Width">{c.width_bits} bit</td>
              <td data-label="Endian">{c.endian}</td>
              <td data-label="Signed">{c.signed ? "yes" : "no"}</td>
              <td data-label="Correlation">{metric(c.correlation, 7)}</td>
              <td data-label="RMSE">{metric(c.fit?.rmse)}</td>
              <td data-label="Relationship" className="relationship-cell">
                {relation(c)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        className="text-button"
        onClick={() => setMore(!more)}
        aria-expanded={more}
      >
        {more ? "Show top 10" : "Show top 25"}{" "}
        <span aria-hidden="true">{more ? "−" : "+"}</span>
      </button>
      <p className="small muted">
        Layout ties remain visible. Inspecting a row does not change the
        recorded agent decision.
      </p>
    </section>
  );
}

const toolNames: Record<string, { title: string; detail: string }> = {
  summarize_capture: {
    title: "Read the capture",
    detail: "Frame count, IDs and timing from deterministic inspection.",
  },
  list_can_ids: {
    title: "Inspect CAN traffic",
    detail: "Observed message IDs and their update frequencies.",
  },
  search_candidates: {
    title: "Search candidate fields",
    detail:
      "Deterministic ranking and equivalence evidence returned to the model.",
  },
  analyze_candidate: {
    title: "Analyze, fit and compare",
    detail:
      "Fitted metrics and affine alternatives collected in one tool result.",
  },
};
export function EvidenceTimeline({ data }: { data: Evidence }) {
  return (
    <section className="agent-section" id="agent">
      <div className="section-top">
        <div>
          <p className="eyebrow">05 / Evidence-grounded agent</p>
          <h2>The model chooses. The evidence decides.</h2>
        </div>
        <span className="status">
          {data.attempts} attempts · {data.retries} retries
        </span>
      </div>
      <div className="agent-grid">
        <div>
          <div className="ownership-key">
            <span>
              <b className="det-mark">D</b> Deterministic evidence
            </span>
            <span>
              <b className="model-mark">M</b> Model judgment
            </span>
          </div>
          {data.tools.length ? (
            <ol className="timeline">
              {data.tools.map((t, i) => (
                <li key={t.id}>
                  <span className="step-number">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3>
                      {toolNames[t.name]?.title ?? t.name}{" "}
                      <span className="det-mark">D</span>
                    </h3>
                    <code>{t.name}</code>
                    <p>
                      {toolNames[t.name]?.detail ?? "Recorded tool result."}{" "}
                      {t.ok ? "Successful." : "Reported an error."}
                    </p>
                  </div>
                </li>
              ))}
              <li>
                <span className="step-number final-step">✓</span>
                <div>
                  <h3>Select → hydrate → validate</h3>
                  <p>
                    <span className="model-mark">M</span> Select fitted evidence
                    and assess confidence.
                    <br />
                    <span className="det-mark">D</span> Assemble exact metrics
                    and validate the conclusion.
                  </p>
                  <span className="status">
                    {data.status} · validation{" "}
                    {data.turns.findLast((t) => t.validation === "passed")
                      ? "passed"
                      : "not recorded"}
                  </span>
                </div>
              </li>
            </ol>
          ) : (
            <p className="missing-state">
              Tool trace not included in this evidence bundle.
            </p>
          )}
          <details className="turn-details">
            <summary>Recorded provider turns ({data.turns.length})</summary>
            {data.turns.length ? (
              data.turns.map((t) => (
                <div key={t.turn} className="turn-row">
                  <b>Turn {t.turn}</b>
                  <span>
                    {t.phase} · {t.response_kind.replaceAll("_", " ")} ·{" "}
                    {t.tool_call_count} tools
                  </span>
                  <small>
                    Conclusion validation: {t.validation.replaceAll("_", " ")}
                  </small>
                </div>
              ))
            ) : (
              <p>Provider-turn diagnostics were not exported.</p>
            )}
          </details>
        </div>
        <div className="interpretation">
          <p className="eyebrow">
            <span className="model-mark">M</span> Agent interpretation
          </p>
          <blockquote>
            {data.rationale ? (
              <ol className="interpretation-points">
                {Array.from(
                  new Intl.Segmenter("en", { granularity: "sentence" }).segment(
                    data.rationale,
                  ),
                ).map(({ segment }, index) => (
                  <li key={index}>
                    <span className="interpretation-point-number" aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <p className="interpretation-point-text">{segment.trim()}</p>
                  </li>
                ))}
              </ol>
            ) : (
              "No rationale was exported for this run."
            )}
          </blockquote>
          <p className="small muted">
            Stored model interpretation. Numerical evidence above comes from
            deterministic tools.
          </p>
          <div className="decision-box">
            <p className="overline">Recorded AgentDecision</p>
            {data.decision ? (
              <>
                <code>candidate_ref: {data.decision.candidate_ref}</code>
                <dl>
                  <div>
                    <dt>Signal confidence</dt>
                    <dd>{data.decision.signal_confidence}</dd>
                  </div>
                  <div>
                    <dt>Layout confidence</dt>
                    <dd>{data.decision.layout_confidence}</dd>
                  </div>
                  <div>
                    <dt>Layout ambiguous</dt>
                    <dd>{String(data.decision.layout_ambiguous)}</dd>
                  </div>
                  <div>
                    <dt>Alternative refs</dt>
                    <dd>
                      {data.decision.alternative_refs.join(", ") ||
                        "None selected"}
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <p>Decision reference not exported.</p>
            )}
          </div>
          <a
            className="source-link"
            href={evidenceUrl("agent_run_01.json")}
            target="_blank"
            rel="noreferrer"
          >
            Open complete recorded evidence ↗
          </a>
        </div>
      </div>
      <p className="small muted">
        Actual recorded sequence, not a simulated run. Fitting and comparison
        happened inside candidate analysis; hydration and validation are
        deterministic finalization steps.
      </p>
    </section>
  );
}

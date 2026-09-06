import { useEffect, useId, useRef, useState } from "react";
import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { evidenceUrl, metric, type Evidence, type Sample } from "./evidence";

export function ReconstructionChart({ data }: { data: Evidence }) {
  const host = useRef<HTMLDivElement>(null),
    id = useId();
  const [width, setWidth] = useState(800),
    [index, setIndex] = useState(0);
  useEffect(() => {
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.max(260, entries[0].contentRect.width)),
    );
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const samples = data.samples;
  if (!samples.length)
    return (
      <section className="panel">
        <h2>Reconstruction unavailable</h2>
        <p>No exported samples in this evidence bundle.</p>
      </section>
    );
  const mobile = width < 540,
    height = mobile ? 260 : 354;
  const left = 40,
    right = mobile ? 14 : 126,
    top = mobile ? 24 : 30,
    bottom = mobile ? 40 : 46;
  const start = samples[0].timestamp,
    duration = samples[samples.length - 1].timestamp - start;
  const values = samples.flatMap((s) => [s.reference, s.reconstructed]);
  const x = scaleLinear()
    .domain([0, duration])
    .range([left, width - right]);
  const y = scaleLinear()
    .domain([Math.min(...values) - 3, Math.max(...values) + 3])
    .nice()
    .range([height - bottom, top]);
  const path = (key: "reference" | "reconstructed") =>
    line<Sample>()
      .x((s) => x(s.timestamp - start))
      .y((s) => y(s[key]))(samples) ?? "";
  const selected = samples[Math.min(index, samples.length - 1)],
    last = samples[samples.length - 1];
  const refLabelY = Math.min(height - bottom - 28, y(last.reference) - 12),
    recLabelY = Math.max(refLabelY + 24, y(last.reconstructed) + 12);
  function inspect(clientX: number) {
    const bounds = host.current?.getBoundingClientRect();
    if (!bounds) return;
    const time = x.invert(clientX - bounds.left) + start;
    let lo = 0,
      hi = samples.length - 1;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (samples[mid].timestamp < time) lo = mid + 1;
      else hi = mid;
    }
    setIndex(
      lo > 0 &&
        Math.abs(samples[lo - 1].timestamp - time) <
          Math.abs(samples[lo].timestamp - time)
        ? lo - 1
        : lo,
    );
  }
  return (
    <section
      className="chart-section"
      id="reconstruction"
      aria-labelledby="chart-heading"
    >
      <div className="section-top">
        <div>
          <p className="eyebrow">01 / Physical evidence</p>
          <h2 id="chart-heading">A signal that tracks the reference.</h2>
        </div>
        <span className="tag">{samples.length} aligned samples</span>
      </div>
      <div className="chart-context">
        <span>
          Speed <span className="muted">/ km/h</span>
        </span>
        <div className="chart-key">
          <span className="key-ref">GNSS reference</span>
          <span className="key-rec">CAN reconstruction</span>
        </div>
      </div>
      <div ref={host} className="chart-host">
        <svg
          data-testid="reconstruction-chart"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={`${id}-title ${id}-desc`}
          onPointerMove={(e) => {
            if (e.pointerType === "mouse") inspect(e.clientX);
          }}
          onPointerDown={(e) => inspect(e.clientX)}
        >
          <title id={`${id}-title`}>
            GNSS speed and reconstructed CAN signal over time
          </title>
          <desc id={`${id}-desc`}>
            The two saved series closely track over {metric(duration, 1)}{" "}
            seconds. Correlation {metric(data.metrics.correlation, 4)} and RMSE{" "}
            {metric(data.metrics.rmse)} km/h. Dashed neutral line is GNSS; solid
            green is reconstruction. Use the sample slider or download the CSV
            for exact values.
          </desc>
          {y.ticks(5).map((t) => (
            <g key={t}>
              <line
                x1={left}
                x2={width - right}
                y1={y(t)}
                y2={y(t)}
                className="grid-line"
              />
              <text
                x={left - 10}
                y={y(t) + 4}
                textAnchor="end"
                className="axis-text"
              >
                {t}
              </text>
            </g>
          ))}
          {x.ticks(mobile ? 4 : 6).map((t) => (
            <text
              key={t}
              x={x(t)}
              y={height - 18}
              textAnchor="middle"
              className="axis-text"
            >
              {t}s
            </text>
          ))}
          <path d={path("reference")} className="reference-line" />
          <path d={path("reconstructed")} className="reconstruction-line" />
          <line
            x1={x(selected.timestamp - start)}
            x2={x(selected.timestamp - start)}
            y1={top}
            y2={height - bottom}
            className="inspection-line"
          />
          <circle
            cx={x(selected.timestamp - start)}
            cy={y(selected.reconstructed)}
            r="4"
            className="inspection-dot"
          />
          {!mobile && (
            <g>
              <path
                d={`M${x(duration)},${y(last.reference)} L${width - right + 12},${refLabelY} h6`}
                className="label-leader reference-line"
              />
              <text
                x={width - right + 22}
                y={refLabelY + 4}
                className="direct-label"
              >
                GNSS reference
              </text>
              <path
                d={`M${x(duration)},${y(last.reconstructed)} L${width - right + 12},${recLabelY} h6`}
                className="label-leader reconstruction-line"
              />
              <text
                x={width - right + 22}
                y={recLabelY + 4}
                className="direct-label accent-text"
              >
                Reconstructed
              </text>
            </g>
          )}
        </svg>
      </div>
      <div className="chart-bottom">
        <p>
          Elapsed time from first aligned sample{" "}
          <span className="muted">· saved rank #1 reconstruction</span>
        </p>
        <a href={evidenceUrl("reconstructed.csv")} download>
          Export CSV ↗
        </a>
      </div>
      <div className="sample-inspector">
        <label htmlFor={`${id}-sample`}>
          Inspect sample{" "}
          <span className="mono">
            {index + 1}/{samples.length}
          </span>
        </label>
        <input
          id={`${id}-sample`}
          type="range"
          min="0"
          max={samples.length - 1}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
          aria-valuetext={`${metric(selected.timestamp - start, 2)} seconds; reference ${metric(selected.reference)}; reconstructed ${metric(selected.reconstructed)} km/h; raw ${selected.raw}`}
        />
        <div className="sample-readout">
          <span>
            <small>TIME</small>
            {metric(selected.timestamp - start, 2)} s
          </span>
          <span>
            <small>REFERENCE</small>
            {metric(selected.reference)} <i>km/h</i>
          </span>
          <span className="accent-text">
            <small>RECONSTRUCTED</small>
            {metric(selected.reconstructed)} <i>km/h</i>
          </span>
          <span className="raw-reading">
            <small>RAW</small>
            {selected.raw}
          </span>
        </div>
      </div>
      <p className="chart-footnote">
        Measured agreement:{" "}
        <strong>r {metric(data.metrics.correlation, 4)}</strong> ·{" "}
        <strong>RMSE {metric(data.metrics.rmse)} km/h</strong>. In-sample
        evidence from one capture, not held-out accuracy.
      </p>
    </section>
  );
}

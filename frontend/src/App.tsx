import { useEffect, useRef, useState } from "react";
import {
  AmbiguityView,
  BitfieldView,
  CandidateTable,
  EvidenceTimeline,
  ResultSummary,
} from "./components";
import { ReconstructionChart } from "./Chart";
import {
  candidateKey,
  evidenceUrl,
  loadEvidence,
  type Candidate,
  type Evidence,
} from "./evidence";

function DemoControls({
  data,
  onRun,
  loading,
}: {
  data?: Evidence;
  onRun: () => void;
  loading: boolean;
}) {
  const fields = [
    ["CAN log", "real_can_log.csv"],
    ["Reference CSV", "real_speed_reference.csv"],
    ["Reference column", "speed_kph"],
    ["Alignment", data?.config.alignment ?? "nearest"],
    [
      "Timestamp tolerance",
      `${data?.config.timestamp_tolerance ?? 0.02} seconds`,
    ],
    ["Minimum samples", String(data?.config.min_samples ?? 300)],
    [
      "Provider / model",
      `${data?.provider ?? "ollama"} / ${data?.model ?? "gpt-oss:120b-cloud"}`,
    ],
  ];
  return (
    <>
      <div className="rail-heading">
        <p className="eyebrow">Analysis session</p>
        <span className="tag">STATIC DEMO</span>
      </div>
      <div className="dataset-name">
        <span className="dataset-symbol" aria-hidden="true">
          ▥
        </span>
        <div>
          <strong>Toyota RAV4</strong>
          <small>2017 · comma2k19</small>
        </div>
      </div>
      <p className="rail-description">
        Raw vehicle traffic.
        <br />
        An independent speed reference.
      </p>
      <div className="input-fields">
        {fields.map(([label, value]) => (
          <label key={label}>
            <span>{label}</span>
            <input readOnly value={value} aria-label={label} />
          </label>
        ))}
      </div>
      <button className="run-button" onClick={onRun} disabled={loading}>
        <span aria-hidden="true">▷</span>{" "}
        {loading ? "Loading evidence…" : "Run Toyota RAV4 Demo"}
      </button>
      <p className="demo-note">
        Loads the recorded evidence bundle.
        <br />
        Inputs are read-only. No live execution.
      </p>
      <div className="rail-bottom">
        <span className="status-dot" aria-hidden="true" /> Backend independent
        <p>
          No API keys. No uploads.
          <br />
          Deterministic evidence, locally viewed.
        </p>
      </div>
    </>
  );
}

export default function App() {
  const [data, setData] = useState<Evidence>(),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [notice, setNotice] = useState("");
  const [key, setKey] = useState(() =>
    new URLSearchParams(location.search).get("candidate"),
  );
  const dialog = useRef<HTMLDialogElement>(null),
    settings = useRef<HTMLButtonElement>(null);
  async function run(reset = false) {
    setLoading(true);
    setError("");
    try {
      const next = await loadEvidence();
      setData(next);
      if (reset) {
        setKey(null);
        history.pushState(null, "", location.pathname);
        setNotice("Toyota RAV4 evidence loaded. Recorded conclusion restored.");
      }
    } catch {
      setError(
        "The curated evidence could not be loaded or validated. Run npm run prepare:evidence, then retry.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void run();
    const pop = () =>
      setKey(new URLSearchParams(location.search).get("candidate"));
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  const inspected =
    data?.ranked.find((c) => candidateKey(c) === key) ?? data?.selected;
  function select(c: Candidate) {
    const next = candidateKey(c);
    setKey(next);
    const url = new URL(location.href);
    url.searchParams.set("candidate", next);
    history.pushState(null, "", url);
    setNotice(
      `Inspecting start ${c.start_bit}, ${c.width_bits}-bit ${c.endian}-endian ${c.signed ? "signed" : "unsigned"} layout. Recorded conclusion unchanged.`,
    );
  }
  const [rankingOpen, setRankingOpen] = useState(
    () => !window.matchMedia("(max-width: 650px)").matches,
  );
  return (
    <>
      <a className="skip-link" href="#workspace">
        Skip to signal evidence
      </a>
      <header className="app-header">
        <a
          className="brand"
          href={location.pathname}
          aria-label="CANary workspace"
        >
          <img src={`${import.meta.env.BASE_URL}canary.svg`} alt="" />
          <span>
            CANary
            <span className="brand-subtitle">
              Evidence-grounded CAN signal discovery
            </span>
          </span>
        </a>
        <div className="header-context">
          <span className="context-label">Real Toyota RAV4 demo</span>
          <span className="header-divider" />
          <a
            href="https://github.com/eead-dev/canary"
            target="_blank"
            rel="noreferrer"
            className="repository-link"
          >
            Repository <span aria-hidden="true">↗</span>
          </a>
          <button
            className="mobile-settings"
            ref={settings}
            onClick={() => dialog.current?.showModal()}
          >
            Session
          </button>
        </div>
      </header>
      <div className="workspace-shell">
        <aside
          className="control-rail"
          aria-label="Read-only analysis configuration"
        >
          <DemoControls
            data={data}
            loading={loading}
            onRun={() => void run(true)}
          />
        </aside>
        <main id="workspace">
          <div className="workspace-location">
            <span>
              Workspace <span aria-hidden="true">/</span>{" "}
              <strong>Signal discovery</strong>
            </span>
            <span className="recorded-label">RECORDED EVIDENCE</span>
          </div>
          <p className="sr-only" role="status">
            {notice}
          </p>
          {error ? (
            <section className="load-state" role="alert">
              <p className="eyebrow">Evidence unavailable</p>
              <h1>Unable to open this capture.</h1>
              <p>{error}</p>
              <button className="run-button" onClick={() => void run()}>
                Retry loading evidence
              </button>
            </section>
          ) : !data ? (
            <section className="load-state" aria-live="polite">
              <p className="eyebrow">Opening curated evidence</p>
              <h1>Loading the Toyota capture…</h1>
              <p>Reading saved metrics, reconstruction and agent records.</p>
            </section>
          ) : (
            <>
              <div className="capture-context">
                <span>
                  COMMA2K19 <i> / </i> 60-SECOND CAPTURE
                </span>
                <div>
                  <b>{data.frames.toLocaleString("en-US")}</b> frames{" "}
                  <span>·</span> <b>{data.ids}</b> CAN IDs <span>·</span>{" "}
                  <b>{data.referenceSamples}</b> GNSS samples
                </div>
              </div>
              <ResultSummary data={data} />
              <ReconstructionChart data={data} />
              <div className="encoding-grid">
                <AmbiguityView
                  data={data}
                  inspected={inspected!}
                  onSelect={select}
                />
                <BitfieldView data={data} value={inspected!} />
              </div>
              <div className="ranking-disclosure">
                <button
                  className="section-toggle"
                  aria-expanded={rankingOpen}
                  aria-controls="ranking-content"
                  onClick={() => setRankingOpen(!rankingOpen)}
                >
                  Ranked candidates{" "}
                  <span aria-hidden="true">{rankingOpen ? "−" : "+"}</span>
                </button>
                {rankingOpen && (
                  <div id="ranking-content">
                    <CandidateTable
                      data={data}
                      inspected={inspected!}
                      onSelect={select}
                    />
                  </div>
                )}
              </div>
              <EvidenceTimeline data={data} />
              <footer className="evidence-footer">
                <div>
                  <strong>Evidence before confidence.</strong>
                  <p>
                    Blind discovery used no DBC. Public definitions were
                    consulted separately, after discovery. Exact layout remains
                    ambiguous.
                  </p>
                </div>
                <div className="footer-links">
                  <a
                    href={evidenceUrl("manifest.json")}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Evidence manifest ↗
                  </a>
                  <a
                    href={evidenceUrl("report.html")}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Original report ↗
                  </a>
                  <a
                    href={evidenceUrl("validation.json")}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Post-discovery validation ↗
                  </a>
                </div>
                <small>
                  Source: comma.ai comma2k19 · MIT · capture provenance and
                  attribution in repository. Single-capture, in-sample evidence.
                </small>
              </footer>
            </>
          )}
        </main>
      </div>
      <dialog
        ref={dialog}
        aria-labelledby="session-heading"
        className="settings-dialog"
        onClose={() => settings.current?.focus()}
      >
        <div className="dialog-header">
          <h2 id="session-heading">Demo configuration</h2>
          <button
            onClick={() => dialog.current?.close()}
            aria-label="Close session settings"
          >
            ✕
          </button>
        </div>
        <DemoControls
          data={data}
          loading={loading}
          onRun={() => {
            void run(true);
            dialog.current?.close();
          }}
        />
      </dialog>
    </>
  );
}

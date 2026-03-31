"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

const LS_URL = "kmbl_autonomous_url";
const LS_THREAD = "kmbl_autonomous_thread_id";
const LS_IDENTITY = "kmbl_autonomous_identity_id";

/** Mirrors orchestrator StartRunResponse / GraphRunDetail session_staging */
type SessionStagingLinks = {
  graph_run_id: string;
  thread_id: string;
  control_plane_live_habitat_path?: string;
  control_plane_staging_preview_path: string;
  orchestrator_working_staging_json_path: string;
};

type RunResult = {
  time: string;
  graph_run_id?: string;
  status?: string;
  staging_snapshot_id?: string;
  error?: string;
};

function pickSessionStaging(raw: Record<string, unknown> | null | undefined): SessionStagingLinks | null {
  if (!raw || typeof raw !== "object") return null;
  const ss = raw.session_staging;
  if (!ss || typeof ss !== "object") return null;
  const o = ss as Record<string, unknown>;
  const gid = o.graph_run_id;
  const tid = o.thread_id;
  if (typeof gid !== "string" || typeof tid !== "string") return null;
  const previewPath =
    typeof o.control_plane_staging_preview_path === "string"
      ? o.control_plane_staging_preview_path
      : `/api/runs/${encodeURIComponent(gid)}/staging-preview`;
  return {
    graph_run_id: gid,
    thread_id: tid,
    control_plane_live_habitat_path:
      typeof o.control_plane_live_habitat_path === "string" ? o.control_plane_live_habitat_path : undefined,
    control_plane_staging_preview_path: previewPath,
    orchestrator_working_staging_json_path:
      typeof o.orchestrator_working_staging_json_path === "string"
        ? o.orchestrator_working_staging_json_path
        : "",
  };
}

export default function AutonomousPage() {
  const [url, setUrl] = useState("");
  const [savedUrl, setSavedUrl] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [identityId, setIdentityId] = useState<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const identityIdRef = useRef<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runCount, setRunCount] = useState(0);
  const [currentRun, setCurrentRun] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunResult[]>([]);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<string[]>([]);
  const messagesRef = useRef<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const stopRef = useRef(false);
  const runsEndRef = useRef<HTMLDivElement>(null);
  /** Latest session staging links from start or run-detail poll (updates during a run). */
  const [sessionStaging, setSessionStaging] = useState<SessionStagingLinks | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    const stored = localStorage.getItem(LS_URL);
    if (stored) {
      setSavedUrl(stored);
      setUrl(stored);
    }
    const t = localStorage.getItem(LS_THREAD);
    const i = localStorage.getItem(LS_IDENTITY);
    if (t) {
      setThreadId(t);
      threadIdRef.current = t;
    }
    if (i) {
      setIdentityId(i);
      identityIdRef.current = i;
    }
  }, []);

  useEffect(() => {
    runsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runs]);

  const saveUrl = () => {
    if (!url.trim()) return;
    localStorage.setItem(LS_URL, url.trim());
    setSavedUrl(url.trim());
  };

  const resetSession = () => {
    localStorage.removeItem(LS_THREAD);
    localStorage.removeItem(LS_IDENTITY);
    setThreadId(null);
    setIdentityId(null);
    threadIdRef.current = null;
    identityIdRef.current = null;
    setSessionStaging(null);
  };

  const liveHabitatHref = (tid: string) =>
    `/habitat/live/${encodeURIComponent(tid)}`;

  const triggerRun = async (): Promise<RunResult> => {
    const targetUrl = savedUrl || url.trim();
    if (!targetUrl) {
      return { time: new Date().toLocaleTimeString(), error: "No URL set" };
    }

    const instructionSnapshot = [...messagesRef.current];

    try {
      const body: Record<string, unknown> = {
        identity_url: targetUrl,
        trigger_type: "prompt",
        scenario_preset: "identity_url_static_v1",
      };

      const tidLoop = threadIdRef.current;
      const iidLoop = identityIdRef.current;
      if (tidLoop && iidLoop) {
        body.thread_id = tidLoop;
        body.identity_id = iidLoop;
      }

      if (instructionSnapshot.length > 0) {
        body.user_instructions = instructionSnapshot.join("\n");
      }

      const res = await fetch("/api/runs/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = (await res.json()) as Record<string, unknown>;

      if (!res.ok) {
        let errorMsg = `HTTP ${res.status}`;
        if (typeof data.detail === "string") {
          errorMsg = data.detail;
        } else if (Array.isArray(data.detail)) {
          errorMsg = data.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join(", ");
        } else if (typeof data.error === "string") {
          errorMsg = data.error;
        } else if (data.detail) {
          errorMsg = JSON.stringify(data.detail);
        }
        return {
          time: new Date().toLocaleTimeString(),
          error: errorMsg,
        };
      }

      const tid = typeof data.thread_id === "string" ? data.thread_id : null;
      const iid = typeof data.identity_id === "string" ? data.identity_id : null;
      if (tid) {
        localStorage.setItem(LS_THREAD, tid);
        setThreadId(tid);
        threadIdRef.current = tid;
      }
      if (iid) {
        localStorage.setItem(LS_IDENTITY, iid);
        setIdentityId(iid);
        identityIdRef.current = iid;
      }

      const ss = pickSessionStaging(data);
      if (ss) setSessionStaging(ss);

      const graphRunId = typeof data.graph_run_id === "string" ? data.graph_run_id : null;
      if (graphRunId) {
        setCurrentRun(graphRunId);
      }

      let status = "running";
      let stagingId: string | null = null;

      if (graphRunId) {
        for (let i = 0; i < 120 && status === "running"; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          if (stopRef.current) break;

          try {
            const pollRes = await fetch(`/api/runs/${graphRunId}`);
            const pollData = (await pollRes.json()) as Record<string, unknown>;
            const polled = pickSessionStaging(pollData);
            if (polled) setSessionStaging(polled);

            const s =
              pollData?.summary && typeof pollData.summary === "object"
                ? (pollData.summary as { status?: string }).status
                : pollData.status;
            status = typeof s === "string" ? s : "running";
            const ao = pollData.associated_outputs as { staging_snapshot_id?: string } | undefined;
            stagingId = ao?.staging_snapshot_id ?? (pollData.staging_snapshot_id as string | undefined) ?? null;

            if (status === "completed" || status === "failed") break;
          } catch {
            // Keep polling
          }
        }
      }

      if (instructionSnapshot.length > 0) {
        setMessages([]);
      }

      return {
        time: new Date().toLocaleTimeString(),
        graph_run_id: graphRunId ?? undefined,
        status,
        staging_snapshot_id: stagingId ?? undefined,
      };
    } catch (e) {
      return {
        time: new Date().toLocaleTimeString(),
        error: e instanceof Error ? e.message : String(e),
      };
    }
  };

  const startLoop = async () => {
    if (!savedUrl && !url.trim()) {
      setError("Enter a URL first");
      return;
    }
    if (!savedUrl) saveUrl();

    setRunning(true);
    setError(null);
    stopRef.current = false;

    while (!stopRef.current) {
      const result = await triggerRun();
      setRuns((prev) => [...prev.slice(-49), result]);
      setRunCount((c) => c + 1);
      setCurrentRun(null);

      if (stopRef.current) break;

      await new Promise((r) => setTimeout(r, 3000));
    }

    setRunning(false);
  };

  const stopLoop = () => {
    stopRef.current = true;
    setRunning(false);
  };

  const sendMessage = () => {
    if (!message.trim()) return;
    setMessages((prev) => [...prev, message.trim()]);
    setMessage("");
  };

  const clearMessages = () => setMessages([]);

  const tid = threadId;
  const previewGraphRunId = sessionStaging?.graph_run_id ?? currentRun;

  return (
    <div className="autonomous-page" style={{ maxWidth: 920, margin: "0 auto", padding: "1.25rem 1.5rem 2rem" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", marginBottom: "1.25rem", flexWrap: "wrap" }}>
        <div>
          <h1 className="pub-page-title" style={{ margin: 0 }}>Autonomous</h1>
          <p className="muted small" style={{ margin: "0.35rem 0 0", maxWidth: "42rem" }}>
            Identity URL loop: same thread keeps <strong>working staging</strong> and ratings. Use{" "}
            <strong>Live habitat</strong> to watch the mutable surface; use <strong>Review</strong> links for frozen snapshots after a successful stage.
          </p>
        </div>
        <Link href="/" className="muted small">← Home</Link>
      </header>

      {error && (
        <div className="op-banner op-banner--neutral" role="alert" style={{ marginBottom: "1rem", borderColor: "#8b3a3a" }}>
          {error}
        </div>
      )}

      {/* Live session — primary navigation for ongoing work */}
      {tid ? (
        <div className="op-banner op-banner--staging" style={{ marginBottom: "1.25rem" }}>
          <h2 className="op-section-title" style={{ margin: "0 0 0.5rem", fontSize: "1.05rem" }}>
            Live session (thread {shortId(tid)})
          </h2>
          <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.65 }}>
            <li>
              <Link href={liveHabitatHref(tid)} style={{ fontWeight: 600 }}>
                Open live habitat
              </Link>
              <span className="muted small"> — iframe of <strong>current working staging</strong>; refreshes as generator iterations land.</span>
            </li>
            {previewGraphRunId ? (
              <li>
                <a href={`/api/runs/${encodeURIComponent(previewGraphRunId)}/staging-preview`} target="_blank" rel="noopener noreferrer">
                  Raw HTML preview
                </a>
                <span className="muted small"> — assembled HTML for this graph run&apos;s thread.</span>
                {" "}
                <Link href={`/runs/${encodeURIComponent(previewGraphRunId)}`} className="small">
                  Run detail
                </Link>
              </li>
            ) : (
              <li className="muted small">Start a run to attach staging preview and run detail links.</li>
            )}
          </ul>
        </div>
      ) : (
        <p className="op-banner op-banner--neutral" style={{ marginBottom: "1.25rem" }}>
          After your first run completes, this page will show <strong>live habitat</strong> and preview links for the session thread.
        </p>
      )}

      <details className="op-card op-card--compact" style={{ marginBottom: "1rem" }}>
        <summary className="muted" style={{ cursor: "pointer", fontWeight: 600 }}>
          Working staging vs review snapshots (architecture)
        </summary>
        <div style={{ marginTop: "0.65rem", fontSize: "0.9rem", lineHeight: 1.55 }}>
          <p style={{ margin: "0 0 0.5rem" }}>
            <strong>Working staging</strong> is the mutable surface per thread. Planner/generator/evaluator see{" "}
            <code className="mono small">working_staging_facts</code> from this live state.{" "}
            <strong>Live habitat</strong> reflects it in real time.
          </p>
          <p style={{ margin: "0 0 0.5rem" }}>
            A <strong>staging snapshot</strong> is a frozen row created when the graph stages after evaluator pass/partial. It is for <strong>human review</strong>; it does not replace working staging. Approving or rating a snapshot informs future runs via signals — it does not &quot;paste&quot; that snapshot over the habitat. The canonical flow is: iterations mutate working staging → optional snapshot for review → publication/canon separately.
          </p>
          <p style={{ margin: 0 }} className="muted small">
            Server cron autonomous loops (<code className="mono">/orchestrator/loops</code>) use the same staging model; this page uses <code className="mono">POST /api/runs/start</code> in a client loop.
          </p>
        </div>
      </details>

      {/* URL */}
      <div className="op-card" style={{ marginBottom: "1rem" }}>
        <h2 className="op-section-title" style={{ marginBottom: "0.5rem" }}>Identity URL</h2>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: savedUrl ? "0.5rem" : 0 }}>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            style={{
              flex: 1,
              padding: "0.6rem 0.8rem",
              borderRadius: 6,
              border: "1px solid #444",
              background: "#0d0d1a",
              color: "#fff",
              fontSize: "0.95rem",
            }}
          />
          <button
            type="button"
            onClick={saveUrl}
            disabled={!url.trim()}
            className="op-btn op-btn--primary"
            style={{ opacity: url.trim() ? 1 : 0.5 }}
          >
            Save
          </button>
        </div>
        {savedUrl && (
          <p className="muted small" style={{ margin: 0 }}>
            Saved: <span className="mono">{savedUrl}</span>
          </p>
        )}
        <div style={{ marginTop: "0.75rem", display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", fontSize: "0.85rem" }}>
          {threadId && identityId ? (
            <span style={{ color: "#8fbc8f" }}>
              Session locked — reuse thread + identity on each loop iteration.
            </span>
          ) : (
            <span className="muted">First run creates identity + thread; later runs continue the same session.</span>
          )}
          <button type="button" onClick={resetSession} className="op-btn op-btn--secondary" style={{ fontSize: "0.8rem" }}>
            New session
          </button>
        </div>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={startLoop}
          disabled={running || (!savedUrl && !url.trim())}
          className="op-btn op-btn--primary"
          style={{
            background: running ? "#1a5c38" : "#2d6a4f",
            color: "#fff",
            fontWeight: 600,
            padding: "0.65rem 1.25rem",
          }}
        >
          {running ? "Running…" : "▶ Start loop"}
        </button>
        <button
          type="button"
          onClick={stopLoop}
          disabled={!running}
          className="op-btn op-btn--primary"
          style={{
            background: running ? "#c0392b" : "#4a2c2c",
            color: "#fff",
            fontWeight: 600,
            padding: "0.65rem 1.25rem",
          }}
        >
          Stop
        </button>
        <span className={`op-badge ${running ? "op-badge--gallery" : "op-badge--neutral"}`}>
          {running ? "active" : "idle"}
        </span>
        <span className="muted small" style={{ marginLeft: "auto" }}>Iterations: {runCount}</span>
      </div>

      {/* Instructions */}
      <div className="op-card" style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
          <h2 className="op-section-title" style={{ margin: 0 }}>Planner instructions</h2>
          {messages.length > 0 && (
            <button type="button" onClick={clearMessages} className="muted small" style={{ background: "none", border: "none", cursor: "pointer" }}>
              Clear
            </button>
          )}
        </div>
        <p className="muted small" style={{ margin: "0 0 0.75rem" }}>
          Sent once per run as <code className="mono">user_instructions</code>, then cleared from the queue.
        </p>
        {messages.length > 0 && (
          <div style={{ marginBottom: "0.75rem" }}>
            {messages.map((m, i) => (
              <div key={i} style={{ background: "#1e3a5f", padding: "0.45rem 0.65rem", borderRadius: 6, marginBottom: "0.25rem", fontSize: "0.9rem" }}>
                {m}
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && sendMessage()}
            placeholder="e.g. warmer palette, tighter hero"
            style={{
              flex: 1,
              padding: "0.6rem 0.8rem",
              borderRadius: 6,
              border: "1px solid #444",
              background: "#0d0d1a",
              color: "#fff",
              fontSize: "0.9rem",
            }}
          />
          <button type="button" onClick={sendMessage} disabled={!message.trim()} className="op-btn op-btn--secondary" style={{ opacity: message.trim() ? 1 : 0.5 }}>
            Add
          </button>
        </div>
      </div>

      {/* Run log */}
      <div className="op-card">
        <h2 className="op-section-title" style={{ marginBottom: "0.5rem" }}>Run log</h2>
        <div style={{
          maxHeight: 320,
          overflowY: "auto",
          fontFamily: "ui-monospace, monospace",
          fontSize: "0.82rem",
          background: "rgba(0,0,0,0.25)",
          borderRadius: 4,
          padding: "0.5rem 0.65rem",
        }}>
          {currentRun && (
            <div style={{ padding: "0.35rem 0", borderBottom: "1px solid #333", color: "#e67e22" }}>
              In flight… <Link href={`/runs/${encodeURIComponent(currentRun)}`} className="mono">{shortId(currentRun)}</Link>
              {tid ? (
                <>
                  {" · "}
                  <Link href={liveHabitatHref(tid)}>habitat</Link>
                </>
              ) : null}
            </div>
          )}
          {runs.length === 0 && !currentRun && (
            <p className="muted" style={{ margin: 0 }}>No iterations yet.</p>
          )}
          {runs.map((r, i) => (
            <div key={i} style={{ padding: "0.45rem 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
              <span className="muted">{r.time}</span>
              {" "}
              {r.error ? (
                <span style={{ color: "#e74c3c" }}>{r.error}</span>
              ) : (
                <>
                  <span style={{ color: r.status === "completed" ? "#52b788" : "#f4a261" }}>{r.status}</span>
                  {r.graph_run_id ? (
                    <>
                      {" "}
                      <Link href={`/runs/${encodeURIComponent(r.graph_run_id)}`}>run</Link>
                    </>
                  ) : null}
                  {tid ? (
                    <>
                      {" "}
                      <Link href={liveHabitatHref(tid)}>habitat</Link>
                    </>
                  ) : null}
                  {r.staging_snapshot_id ? (
                    <>
                      {" → "}
                      <Link href={`/review/staging/${encodeURIComponent(r.staging_snapshot_id)}`}>
                        snapshot
                      </Link>
                    </>
                  ) : null}
                </>
              )}
            </div>
          ))}
          <div ref={runsEndRef} />
        </div>
      </div>
    </div>
  );
}

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 10 ? `${s.slice(0, 10)}…` : id;
}

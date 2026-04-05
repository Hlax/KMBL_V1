"use client";

import { useCallback, useMemo, useRef, useState } from "react";

import { scenarioBadgeFromScenarioTag, scenarioBadgeLabel } from "@/lib/gallery-strip-visibility";
import {
  fetchRunStartExclusive,
  isRunStartBlocked,
} from "@/lib/run-start-single-flight";

/** Next.js API route wrapper around orchestrator JSON (and 502/500 envelopes). */
type ProxyPayload = {
  ok?: boolean;
  httpStatus?: number;
  url?: string;
  data?: unknown;
  error?: string;
};

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

function ProxyWrapperSummary({ p }: { p: ProxyPayload }) {
  return (
    <dl className="debug-kv" style={{ marginBottom: "0.75rem" }}>
      <dt>ok</dt>
      <dd>{p.ok !== undefined ? String(p.ok) : "—"}</dd>
      <dt>httpStatus</dt>
      <dd>{p.httpStatus != null ? String(p.httpStatus) : "—"}</dd>
      <dt>url</dt>
      <dd>{p.url ?? "—"}</dd>
      <dt>data</dt>
      <dd className="muted" style={{ fontFamily: "inherit" }}>
        Orchestrator body (see below)
      </dd>
    </dl>
  );
}

function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = (status || "").toLowerCase();
  const ok =
    s === "completed" ||
    s === "succeeded" ||
    s === "success" ||
    s === "passed";
  const fail = s === "failed" || s === "error" || s === "rejected";
  const cls = ok
    ? "debug-badge debug-badge--ok"
    : fail
      ? "debug-badge debug-badge--fail"
      : "debug-badge debug-badge--neutral";
  return <span className={cls}>{status || "—"}</span>;
}

function panelClassForPayload(p: ProxyPayload, innerStatus: string | null): string {
  const http = p.httpStatus ?? 0;
  if (p.error && p.ok === undefined && !p.data) return "debug-panel debug-panel--err";
  if (http >= 400) return "debug-panel debug-panel--err";
  if (!p.ok) return "debug-panel debug-panel--err";
  const s = (innerStatus || "").toLowerCase();
  if (s === "failed") return "debug-panel debug-panel--warn";
  if (s === "completed" || s === "succeeded") return "debug-panel debug-panel--ok";
  return "debug-panel";
}

function OrchestratorFields({ data }: { data: Record<string, unknown> }) {
  const evalObj = isRecord(data.evaluation) ? data.evaluation : null;
  const spec = isRecord(data.build_spec) ? data.build_spec : null;
  const cand = isRecord(data.build_candidate) ? data.build_candidate : null;
  const hasDetail = "detail" in data && data.detail != null;

  return (
    <dl className="debug-kv">
      {hasDetail && (
        <>
          <dt>detail</dt>
          <dd>
            {typeof data.detail === "string"
              ? data.detail
              : JSON.stringify(data.detail)}
          </dd>
        </>
      )}
      <dt>graph_run_id</dt>
      <dd>{str(data.graph_run_id) ?? "—"}</dd>
      <dt>thread_id</dt>
      <dd>{str(data.thread_id) ?? "—"}</dd>
      <dt>status</dt>
      <dd>
        <StatusBadge status={str(data.status)} />
      </dd>
      {"scenario_preset" in data && data.scenario_preset != null && (
        <>
          <dt>scenario_preset</dt>
          <dd>
            <code>{str(data.scenario_preset)}</code>
          </dd>
        </>
      )}
      {"effective_event_input" in data && data.effective_event_input != null && (
        <>
          <dt>effective_event_input</dt>
          <dd>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                fontSize: "0.78rem",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {JSON.stringify(data.effective_event_input, null, 2)}
            </pre>
          </dd>
        </>
      )}
      {"scenario_tag" in data && data.scenario_tag != null && (
        <>
          <dt>scenario_tag</dt>
          <dd>
            <code>{str(data.scenario_tag)}</code>
            {(() => {
              const tag = str(data.scenario_tag);
              const b = tag ? scenarioBadgeFromScenarioTag(tag) : null;
              const sb = scenarioBadgeLabel(b);
              return sb ? (
                <span className={sb.className} style={{ marginLeft: "0.5rem" }}>
                  {sb.label}
                </span>
              ) : null;
            })()}
          </dd>
        </>
      )}
      {"outputs_substantive" in data && typeof data.outputs_substantive === "boolean" && (
        <>
          <dt>outputs_substantive</dt>
          <dd>
            <span
              className={
                data.outputs_substantive
                  ? "debug-badge debug-badge--ok"
                  : "debug-badge debug-badge--fail"
              }
            >
              {data.outputs_substantive ? "yes (heuristic)" : "no / minimal"}
            </span>
          </dd>
        </>
      )}
      {"run_event_input" in data && data.run_event_input != null && (
        <>
          <dt>run_event_input (checkpoint)</dt>
          <dd>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                fontSize: "0.78rem",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {JSON.stringify(data.run_event_input, null, 2)}
            </pre>
          </dd>
        </>
      )}
      {"failure_phase" in data && data.failure_phase != null && (
        <>
          <dt>failure_phase</dt>
          <dd>{str(data.failure_phase) ?? "—"}</dd>
        </>
      )}
      {"failure" in data && data.failure != null && (
        <>
          <dt>failure</dt>
          <dd>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                fontSize: "0.8rem",
                fontFamily: "ui-monospace, monospace",
              }}
            >
              {JSON.stringify(data.failure, null, 2)}
            </pre>
          </dd>
        </>
      )}
      {"error_kind" in data && data.error_kind != null && (
        <>
          <dt>error_kind</dt>
          <dd>{str(data.error_kind) ?? "—"}</dd>
        </>
      )}
      {"error_message" in data && data.error_message != null && (
        <>
          <dt>error_message</dt>
          <dd>{str(data.error_message) ?? "—"}</dd>
        </>
      )}
      {evalObj && (
        <>
          <dt>evaluation_report_id</dt>
          <dd>{str(evalObj.evaluation_report_id) ?? "—"}</dd>
          <dt>evaluation.status</dt>
          <dd>{str(evalObj.status) ?? "—"}</dd>
          <dt>evaluation.summary</dt>
          <dd>{str(evalObj.summary) ?? "—"}</dd>
        </>
      )}
      {spec && (
        <>
          <dt>build_spec.id</dt>
          <dd>{str(spec.build_spec_id) ?? "—"}</dd>
          <dt>build_spec.status</dt>
          <dd>{str(spec.status) ?? "—"}</dd>
          <dt>build_spec.title_hint</dt>
          <dd>{str(spec.title_hint) ?? "—"}</dd>
        </>
      )}
      {cand && (
        <>
          <dt>build_candidate.id</dt>
          <dd>{str(cand.build_candidate_id) ?? "—"}</dd>
          <dt>build_candidate.status</dt>
          <dd>{str(cand.status) ?? "—"}</dd>
          {cand.candidate_kind != null && (
            <>
              <dt>build_candidate.kind</dt>
              <dd>{str(cand.candidate_kind) ?? "—"}</dd>
            </>
          )}
        </>
      )}
    </dl>
  );
}

function ResultBlock({
  title,
  payload,
}: {
  title: string;
  payload: ProxyPayload;
}) {
  const inner = payload.data;
  const innerStatus = isRecord(inner) ? str(inner.status) : null;
  const panelClass = panelClassForPayload(payload, innerStatus);
  const configError = payload.error && !payload.url;

  return (
    <div style={{ marginBottom: "1.25rem" }}>
      <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>{title}</h3>
      <p className="muted" style={{ fontSize: "0.8rem", marginBottom: "0.5rem" }}>
        Proxy wrapper: <code>{"{ ok, httpStatus, url, data }"}</code>
      </p>
      <div className={panelClass}>
        <ProxyWrapperSummary p={payload} />
        {configError && (
          <p role="alert" style={{ color: "#f87171", marginTop: 0 }}>
            {payload.error}
          </p>
        )}
        {payload.error && payload.url && (
          <p role="alert" style={{ color: "#f87171", marginTop: 0 }}>
            {payload.error}
          </p>
        )}
        {payload.httpStatus != null && payload.httpStatus >= 400 && !configError && (
          <p role="alert" style={{ color: "#fca5a5", marginBottom: "0.5rem" }}>
            HTTP {payload.httpStatus} — see <code>data</code> for FastAPI{" "}
            <code>detail</code> or message.
          </p>
        )}
        {isRecord(inner) && (
          <>
            <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem" }}>
              Outcome:{" "}
              {innerStatus?.toLowerCase() === "running" ? (
                <strong style={{ color: "#93c5fd" }}>in progress</strong>
              ) : innerStatus?.toLowerCase() === "completed" ? (
                <strong style={{ color: "#86efac" }}>success path</strong>
              ) : innerStatus?.toLowerCase() === "failed" ? (
                <strong style={{ color: "#fde68a" }}>failed run</strong>
              ) : (
                <strong>see status</strong>
              )}
            </p>
            <OrchestratorFields data={inner} />
          </>
        )}
        {inner !== undefined && !isRecord(inner) && (
          <pre
            style={{
              margin: 0,
              whiteSpace: "pre-wrap",
              fontSize: "0.85rem",
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {typeof inner === "string" ? inner : JSON.stringify(inner, null, 2)}
          </pre>
        )}
        <details style={{ marginTop: "0.75rem" }}>
          <summary className="muted" style={{ cursor: "pointer", fontSize: "0.85rem" }}>
            Raw JSON (full proxy response)
          </summary>
          <pre
            style={{
              marginTop: "0.5rem",
              padding: "0.75rem",
              overflow: "auto",
              fontSize: "0.8rem",
              background: "#0c0c0f",
              borderRadius: "4px",
            }}
          >
            {JSON.stringify(payload, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  );
}

const POLL_INTERVAL_MS = 1500;
const POLL_MAX_ROUNDS = 200;

function isTerminalRunStatus(status: string | null | undefined): boolean {
  const s = (status || "").toLowerCase();
  return s === "completed" || s === "failed";
}

export function RunDebugPanel() {
  const [graphRunId, setGraphRunId] = useState("");
  const [startResult, setStartResult] = useState<ProxyPayload | null>(null);
  const [statusResult, setStatusResult] = useState<ProxyPayload | null>(null);
  const [busy, setBusy] = useState<"start" | "status" | "poll" | null>(null);
  const [pollNote, setPollNote] = useState<string | null>(null);
  const [lastStartMode, setLastStartMode] = useState<
    "smoke" | "seeded" | "gallery" | "gallery_varied" | null
  >(
    null,
  );
  const pollAbortRef = useRef<AbortController | null>(null);

  const statusInnerFailed = useMemo(() => {
    if (!statusResult?.data || !isRecord(statusResult.data)) return false;
    return (statusResult.data as { status?: string }).status === "failed";
  }, [statusResult]);

  const getStatusPayload = useCallback(
    async (id: string, signal?: AbortSignal): Promise<ProxyPayload> => {
      const res = await fetch(
        `/api/orchestrator/runs/${encodeURIComponent(id)}`,
        { cache: "no-store", signal },
      );
      const json = (await res.json()) as ProxyPayload;
      return {
        ...json,
        httpStatus: json.httpStatus ?? res.status,
        ok: json.ok !== undefined ? json.ok : res.ok,
      };
    },
    [],
  );

  const pollUntilTerminal = useCallback(
    async (id: string) => {
      pollAbortRef.current?.abort();
      const ac = new AbortController();
      pollAbortRef.current = ac;
      setPollNote(null);
      setBusy("poll");
      try {
        for (let i = 0; i < POLL_MAX_ROUNDS; i++) {
          if (ac.signal.aborted) return;
          const merged = await getStatusPayload(id, ac.signal);
          setStatusResult(merged);
          const inner = merged.data;
          if (isRecord(inner)) {
            const st = str(inner.status);
            if (isTerminalRunStatus(st)) {
              return;
            }
          }
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          if (ac.signal.aborted) return;
        }
        setPollNote(
          "Polling stopped after 5 minutes; last GET response is above — use “Fetch run status” to continue.",
        );
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setStatusResult({
          ok: false,
          error: e instanceof Error ? e.message : String(e),
        });
      } finally {
        if (pollAbortRef.current === ac) pollAbortRef.current = null;
        setBusy(null);
      }
    },
    [getStatusPayload],
  );

  const startRun = useCallback(
    async (mode: "smoke" | "seeded" | "gallery" | "gallery_varied") => {
      pollAbortRef.current?.abort();
      setBusy("start");
      setStartResult(null);
      setStatusResult(null);
      setPollNote(null);
      setLastStartMode(mode);
      const body =
        mode === "smoke"
          ? {}
          : mode === "seeded"
            ? { scenario_preset: "seeded_local_v1" as const }
            : mode === "gallery"
              ? { scenario_preset: "seeded_gallery_strip_v1" as const }
              : { scenario_preset: "seeded_gallery_strip_varied_v1" as const };
      let merged: ProxyPayload | null = null;
      try {
        const res = await fetchRunStartExclusive(
          "/api/orchestrator/runs/start",
          body,
          { cache: "no-store" },
        );
        if (isRunStartBlocked(res)) {
          setStartResult({
            ok: false,
            error: res.message,
          });
          return;
        }
        const json = (await res.json()) as ProxyPayload;
        merged = {
          ...json,
          httpStatus: json.httpStatus ?? res.status,
          ok: json.ok !== undefined ? json.ok : res.ok,
        };
        setStartResult(merged);
        const inner = merged.data as { graph_run_id?: string } | undefined;
        if (inner?.graph_run_id) {
          setGraphRunId(inner.graph_run_id);
        }
      } catch (e) {
        setStartResult({
          ok: false,
          error: e instanceof Error ? e.message : String(e),
        });
      } finally {
        setBusy(null);
      }
      if (merged?.ok) {
        const inner = merged.data as { graph_run_id?: string } | undefined;
        const gid = inner?.graph_run_id;
        if (gid) {
          void pollUntilTerminal(gid);
        }
      }
    },
    [pollUntilTerminal],
  );

  const fetchStatus = useCallback(async () => {
    const id = graphRunId.trim();
    if (!id) {
      setStatusResult({ ok: false, error: "Enter a graph_run_id" });
      return;
    }
    pollAbortRef.current?.abort();
    setBusy("status");
    setStatusResult(null);
    setPollNote(null);
    try {
      setStatusResult(await getStatusPayload(id));
    } catch (e) {
      setStatusResult({
        ok: false,
        error: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setBusy(null);
    }
  }, [graphRunId, getStatusPayload]);

  return (
    <section
      aria-labelledby="run-debug-heading"
      style={{ marginTop: "2rem" }}
    >
      <h2 id="run-debug-heading">Graph run (local debug)</h2>
      <p className="muted">
        <code>POST /orchestrator/runs/start</code> returns immediately with{" "}
        <code>status: running</code> and ids; this panel then polls{" "}
        <code>GET /orchestrator/runs/{"{id}"}</code> until{" "}
        <code>completed</code> or <code>failed</code>. Traffic goes through
        Next.js API routes (server-side fetch — no CORS). Requires orchestrator +
        Supabase env on the Python side for persisted rows.
      </p>
      <p className="muted" style={{ fontSize: "0.88rem" }}>
        <strong>Smoke</strong> sends <code>{"{}"}</code>.{" "}
        <strong>Seeded</strong> sends{" "}
        <code>{"{ \"scenario_preset\": \"seeded_local_v1\" }"}</code> so the
        orchestrator injects the canonical local <code>event_input</code>.{" "}
        <strong>Gallery strip</strong> sends{" "}
        <code>{"{ \"scenario_preset\": \"seeded_gallery_strip_v1\" }"}</code>{" "}
        for deterministic smoke. <strong>Gallery varied</strong> sends{" "}
        <code>{"{ \"scenario_preset\": \"seeded_gallery_strip_varied_v1\" }"}</code> with bounded
        nonces and variants (see <code>effective_event_input</code>). With{" "}
        <code>KILOCLAW_GENERATOR_OPENAI_IMAGE_CONFIG_KEY=kmbl-image-gen</code> in repo-root{" "}
        <code>.env.local</code> (orchestrator restarted), KMBL routes the generator step to that
        OpenClaw agent for explicit image intent; the gateway must have{" "}
        <code>OPENAI_API_KEY</code> for Images API. Terminal outcome and errors are on the GET panel
        after polling.
      </p>
      {lastStartMode && (
        <p style={{ fontSize: "0.88rem", marginBottom: "0.5rem" }}>
          Last start button:{" "}
          <code>
            {lastStartMode === "smoke"
              ? "smoke ({})"
              : lastStartMode === "seeded"
                ? "seeded (preset)"
                : lastStartMode === "gallery"
                  ? "gallery strip (preset)"
                  : "gallery varied (preset)"}
          </code>
        </p>
      )}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "0.75rem",
        }}
      >
        <button
          type="button"
          onClick={() => startRun("smoke")}
          disabled={busy !== null}
        >
          {busy === "start"
            ? "Starting…"
            : busy === "poll"
              ? "Polling…"
              : "Start smoke run ({})"}
        </button>
        <button
          type="button"
          onClick={() => startRun("seeded")}
          disabled={busy !== null}
        >
          {busy === "start"
            ? "Starting…"
            : busy === "poll"
              ? "Polling…"
              : "Start seeded local run"}
        </button>
        <button
          type="button"
          onClick={() => startRun("gallery")}
          disabled={busy !== null}
        >
          {busy === "start"
            ? "Starting…"
            : busy === "poll"
              ? "Polling…"
              : "Start gallery strip run"}
        </button>
        <button
          type="button"
          onClick={() => startRun("gallery_varied")}
          disabled={busy !== null}
        >
          {busy === "start"
            ? "Starting…"
            : busy === "poll"
              ? "Polling…"
              : "Start gallery varied run"}
        </button>
      </div>
      {busy === "poll" && (
        <p className="muted" style={{ fontSize: "0.88rem", marginBottom: "0.75rem" }}>
          Polling <code>GET /orchestrator/runs/{"{id}"}</code> every{" "}
          {POLL_INTERVAL_MS / 1000}s until <code>completed</code> or{" "}
          <code>failed</code>…
        </p>
      )}
      {startResult && (
        <ResultBlock title="POST /orchestrator/runs/start (proxied)" payload={startResult} />
      )}
      <div style={{ marginBottom: "0.5rem" }}>
        <label htmlFor="graph-run-id" className="muted">
          graph_run_id
        </label>
        <br />
        <input
          id="graph-run-id"
          value={graphRunId}
          onChange={(e) => setGraphRunId(e.target.value)}
          placeholder="filled after start, or paste from Supabase"
          style={{
            width: "100%",
            maxWidth: "36rem",
            marginTop: "0.25rem",
            padding: "0.35rem 0.5rem",
            fontFamily: "ui-monospace, monospace",
            fontSize: "0.9rem",
          }}
        />
      </div>
      <button type="button" onClick={fetchStatus} disabled={busy !== null}>
        {busy === "status" ? "Loading…" : "Fetch run status"}
      </button>
      {pollNote && (
        <p className="muted" style={{ fontSize: "0.88rem", marginTop: "0.5rem" }}>
          {pollNote}
        </p>
      )}
      {statusResult && statusInnerFailed && (
        <p role="alert" style={{ color: "#fbbf24", marginBottom: "0.75rem" }}>
          Run <code>status: failed</code> — see below for{" "}
          <code>failure_phase</code>, <code>failure</code>,{" "}
          <code>error_kind</code>, <code>error_message</code>.
        </p>
      )}
      {statusResult && (
        <ResultBlock title="GET /orchestrator/runs/{id} (proxied)" payload={statusResult} />
      )}
    </section>
  );
}

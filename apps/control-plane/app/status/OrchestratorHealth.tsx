"use client";

import { useEffect, useState } from "react";

type HealthPayload = {
  reachable: boolean;
  urlChecked: string;
  httpStatus: number | null;
  body: unknown;
  error: string | null;
};

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

export function OrchestratorHealth({
  configuredBaseUrl,
}: {
  configuredBaseUrl: string;
}) {
  const [data, setData] = useState<HealthPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/orchestrator-health", { cache: "no-store" });
        const json = (await res.json()) as HealthPayload;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) {
          setData({
            reachable: false,
            urlChecked: `${configuredBaseUrl || "(unset)"}/health`,
            httpStatus: null,
            body: null,
            error: e instanceof Error ? e.message : String(e),
          });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [configuredBaseUrl]);

  const readiness = data?.body != null && isRecord(data.body)
    ? data.body.readiness
    : null;
  const readinessRec =
    readiness != null && isRecord(readiness) ? readiness : null;
  const repoBackend =
    data?.body != null && isRecord(data.body)
      ? data.body.repository_backend
      : null;

  const summary =
    data == null
      ? "…"
      : data.reachable
        ? "reachable"
        : "unreachable";

  return (
    <section aria-labelledby="orchestrator-health-heading" className="cp-health-compact">
      <h2 id="orchestrator-health-heading" className="op-section-title op-section-title--sub">
        Orchestrator health
      </h2>
      <p className="muted small" style={{ marginBottom: "0.35rem" }}>
        <code>NEXT_PUBLIC_ORCHESTRATOR_URL</code>:{" "}
        {configuredBaseUrl ? (
          <code>{configuredBaseUrl}</code>
        ) : (
          <strong>not set</strong>
        )}
      </p>
      <p className="cp-loading-line" style={{ marginBottom: "0.5rem" }}>
        {loading ? (
          <>
            <span className="cp-spinner" aria-hidden />
            Checking…
          </>
        ) : (
          <>
            Status: <strong>{summary}</strong>
          </>
        )}
        {readinessRec && typeof readinessRec.ready_for_full_local_run === "boolean" && (
          <>
            {" "}
            · local run:{" "}
            <strong
              style={{
                color: readinessRec.ready_for_full_local_run ? "#86efac" : "#fbbf24",
              }}
            >
              {readinessRec.ready_for_full_local_run
                ? "config ready (keys set)"
                : "config incomplete"}
            </strong>
          </>
        )}
      </p>
      {data && (
        <>
          <p className="muted small">
            Probed: <code>{data.urlChecked}</code>
            {data.httpStatus != null ? (
              <>
                {" "}
                · HTTP <code>{data.httpStatus}</code>
              </>
            ) : null}
            {repoBackend != null ? (
              <>
                {" "}
                · repo <code>{String(repoBackend)}</code>
              </>
            ) : null}
          </p>
          {readinessRec && (
            <p className="muted small" style={{ marginBottom: "0.35rem" }}>
              Supabase: {String(readinessRec.supabase_configured ?? "—")} · KiloClaw:{" "}
              {String(readinessRec.kiloclaw_configured ?? "—")} · persisted runs:{" "}
              {String(readinessRec.persisted_runs_available ?? "—")}
            </p>
          )}
          {data.error && (
            <p role="alert" className="cp-error-inline">
              {data.error}
            </p>
          )}
          {data.body != null && (
            <details className="cp-raw-details" style={{ marginTop: "0.5rem" }}>
              <summary className="muted small">Raw health JSON</summary>
              <pre className="op-pre small-pre" style={{ marginTop: "0.35rem" }}>
                {typeof data.body === "string"
                  ? data.body
                  : JSON.stringify(data.body, null, 2)}
              </pre>
            </details>
          )}
        </>
      )}
      <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
        Server-side <code>/api/orchestrator-health</code> → orchestrator <code>/health</code>.
      </p>
    </section>
  );
}

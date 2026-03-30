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
    <section aria-labelledby="orchestrator-health-heading">
      <h2 id="orchestrator-health-heading">Orchestrator health</h2>
      <p className="muted">
        <code>NEXT_PUBLIC_ORCHESTRATOR_URL</code>:{" "}
        {configuredBaseUrl ? (
          <code>{configuredBaseUrl}</code>
        ) : (
          <strong>not set</strong>
        )}
      </p>
      <p>
        Status:{" "}
        {loading ? (
          <span>loading…</span>
        ) : (
          <strong>{summary}</strong>
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
          <p className="muted">
            Probed URL: <code>{data.urlChecked}</code>
          </p>
          {data.httpStatus != null && (
            <p className="muted">
              HTTP: <code>{data.httpStatus}</code>
            </p>
          )}
          {repoBackend != null && (
            <p className="muted">
              repository_backend: <code>{String(repoBackend)}</code>
            </p>
          )}
          {readinessRec && (
            <dl className="debug-kv" style={{ marginTop: "0.5rem" }}>
              <dt>readiness.supabase_configured</dt>
              <dd>
                {String(readinessRec.supabase_configured ?? "—")}
              </dd>
              <dt>readiness.kiloclaw_configured</dt>
              <dd>
                {String(readinessRec.kiloclaw_configured ?? "—")}
              </dd>
              <dt>readiness.persisted_runs_available</dt>
              <dd>
                {String(readinessRec.persisted_runs_available ?? "—")}
              </dd>
            </dl>
          )}
          {data.error && (
            <p role="alert">
              Error: <code>{data.error}</code>
            </p>
          )}
          {data.body != null && (
            <pre
              style={{
                marginTop: "0.75rem",
                padding: "0.75rem",
                overflow: "auto",
                fontSize: "0.85rem",
                background: "#16161a",
                borderRadius: "6px",
              }}
            >
              {typeof data.body === "string"
                ? data.body
                : JSON.stringify(data.body, null, 2)}
            </pre>
          )}
        </>
      )}
      <p className="muted" style={{ fontSize: "0.85rem" }}>
        The browser calls this app&apos;s{" "}
        <code>/api/orchestrator-health</code>; that route performs{" "}
        <code>GET {configuredBaseUrl || "…"}/health</code> from the Next.js server
        (avoids CORS from the browser to FastAPI).
      </p>
    </section>
  );
}

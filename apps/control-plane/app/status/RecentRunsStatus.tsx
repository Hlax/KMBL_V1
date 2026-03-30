"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { GraphRunListItem, GraphRunListResponse } from "@/lib/api-types";

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 8 ? `${s.slice(0, 8)}…` : id;
}

function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusBadgeClass(s: string) {
  const x = s.toLowerCase();
  if (x === "completed") return "op-badge op-badge--ok";
  if (x === "failed") return "op-badge op-badge--fail";
  if (x === "running" || x === "paused") return "op-badge op-badge--warn";
  return "op-badge op-badge--neutral";
}

/**
 * Last N runs from GET /api/runs (orchestrator index).
 */
export function RecentRunsStatus() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<GraphRunListItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/runs?limit=8", { cache: "no-store" });
        const json = (await res.json()) as GraphRunListResponse;
        if (cancelled) return;
        if (!res.ok) {
          setError(typeof json.error === "string" ? json.error : `HTTP ${res.status}`);
          setRows([]);
          return;
        }
        setError(null);
        setRows(Array.isArray(json.runs) ? json.runs : []);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setRows([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-labelledby="recent-runs-heading" className="cp-recent-runs">
      <h2 id="recent-runs-heading" className="op-section-title">
        Recent runs
      </h2>
      <p className="muted small" style={{ marginBottom: "0.65rem" }}>
        Newest first from the orchestrator index.{" "}
        <Link href="/runs">Full list &amp; filters →</Link>
      </p>
      {loading && (
        <p className="cp-loading-line">
          <span className="cp-spinner" aria-hidden />
          Loading…
        </p>
      )}
      {error && !loading && (
        <p role="alert" className="cp-error-inline">
          {error}{" "}
          <span className="muted">— Check orchestrator URL and /api/runs.</span>
        </p>
      )}
      {!loading && !error && rows.length === 0 && (
        <p className="muted small">No runs in the index yet.</p>
      )}
      {!loading && !error && rows.length > 0 && (
        <ul className="cp-recent-runs__list">
          {rows.map((r) => (
            <li key={r.graph_run_id} className="cp-recent-runs__row">
              <div className="cp-recent-runs__main">
                <Link href={`/runs/${encodeURIComponent(r.graph_run_id)}`} className="mono">
                  {shortId(r.graph_run_id)}
                </Link>
                <span className={statusBadgeClass(r.status)}>{r.status}</span>
                <span className="muted small">
                  iter {r.max_iteration_index ?? "—"}
                </span>
              </div>
              <div className="cp-recent-runs__meta muted small">
                {formatWhen(r.started_at)}
              </div>
              <div className="cp-recent-runs__links">
                <Link href={`/runs/${encodeURIComponent(r.graph_run_id)}`}>View run</Link>
                {r.latest_staging_snapshot_id ? (
                  <>
                    {" · "}
                    <Link
                      href={`/review/staging/${encodeURIComponent(r.latest_staging_snapshot_id)}`}
                    >
                      Staging
                    </Link>
                  </>
                ) : (
                  <span className="muted"> · no staging</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

import { AgentThoughtStream } from "@/app/components/AgentThoughtStream";
import { MaterializeReviewSnapshotButton } from "@/app/components/MaterializeReviewSnapshotButton";
import { parseOrchestratorErrorMessage } from "@/lib/orchestrator-error-message";

/** Staging preview iframe reload cadence (same-origin proxy to working-staging HTML). */
const PREVIEW_REFRESH_MS = 5 * 60 * 1000;

type LiveBody = {
  kind?: string;
  read_model?: Record<string, unknown>;
  preview_surface?: Record<string, unknown>;
  thread?: Record<string, unknown> | null;
};

export function LiveHabitatClient({
  threadId,
  initial,
  previewSrc,
}: {
  threadId: string;
  initial: LiveBody | null;
  previewSrc: string;
}) {
  const [data, setData] = useState<LiveBody | null>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [iframeKey, setIframeKey] = useState(0);

  const refresh = useCallback(
    async (reloadPreview: boolean) => {
      try {
        const r = await fetch(`/api/habitat/live/${encodeURIComponent(threadId)}`, {
          cache: "no-store",
        });
        const text = await r.text();
        let parsed: LiveBody;
        try {
          parsed = JSON.parse(text) as LiveBody;
        } catch {
          setErr("Invalid JSON from live habitat API");
          return;
        }
        if (!r.ok) {
          setErr(parseOrchestratorErrorMessage(parsed, r.status));
          return;
        }
        setErr(null);
        setData(parsed);
        if (reloadPreview) {
          setIframeKey((k) => k + 1);
        }
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    },
    [threadId],
  );

  useEffect(() => {
    const id = setInterval(() => void refresh(true), PREVIEW_REFRESH_MS);
    return () => clearInterval(id);
  }, [refresh]);

  const rm = data?.read_model;
  const ps = data?.preview_surface;
  const hasPreviewable =
    rm?.has_previewable_html === true ||
    (Array.isArray(ps?.html_paths) && (ps.html_paths as unknown[]).length > 0);
  const defaultEntry =
    ps?.default_entry_path != null && String(ps.default_entry_path).trim()
      ? String(ps.default_entry_path)
      : null;
  const previewErr =
    ps?.preview_error != null && String(ps.preview_error).trim()
      ? String(ps.preview_error)
      : null;
  const lastBc =
    rm?.last_update_build_candidate_id != null && String(rm.last_update_build_candidate_id).trim()
      ? String(rm.last_update_build_candidate_id)
      : null;
  const rawRev = rm?.revision;
  const revision: string | number | undefined =
    rawRev === null || rawRev === undefined
      ? undefined
      : typeof rawRev === "string" || typeof rawRev === "number"
        ? rawRev
        : undefined;
  const status = rm?.status != null ? String(rm.status) : undefined;

  return (
    <div className="live-habitat-root">
      {err ? (
        <p className="muted small" role="alert" style={{ color: "#e74c3c" }}>
          {err}
        </p>
      ) : null}
      {previewErr || !hasPreviewable ? (
        <div className="op-banner op-banner--warn" style={{ marginBottom: "0.75rem" }}>
          <strong>Preview not assembled for this working staging payload.</strong>{" "}
          {previewErr ? (
            <span className="mono small">{previewErr}</span>
          ) : (
            <span className="small">
              Orchestrator reports no previewable HTML in the live read model — the iframe below may be
              empty or error. If you used a <strong>graph_run_id</strong> in the URL by mistake, use{" "}
              <strong>thread_id</strong> from the run page instead.
            </span>
          )}
        </div>
      ) : (
        <div className="op-banner op-banner--neutral" style={{ marginBottom: "0.75rem" }}>
          <strong>Live preview available</strong> — mutable working staging (not a frozen review snapshot).
          {defaultEntry ? (
            <>
              {" "}
              Entry: <code className="mono small">{defaultEntry}</code>
            </>
          ) : null}
          {lastBc ? (
            <>
              {" "}
              · Last build candidate: <code className="mono small">{lastBc}</code>
            </>
          ) : null}
        </div>
      )}
      <div className="live-habitat-split">
        <div className="live-habitat-split__preview">
          <div className="live-habitat-frame-wrap">
            <iframe
              key={iframeKey}
              title="Live working staging preview"
              src={previewSrc}
              className="live-habitat-iframe"
              sandbox="allow-scripts allow-same-origin"
            />
          </div>
          <div className="op-card op-card--compact live-habitat-meta-card">
            <h2 className="op-section-title" style={{ marginBottom: "0.35rem" }}>
              Habitat details
            </h2>
            <dl className="live-habitat-meta">
              <div>
                <dt>Revision</dt>
                <dd>{rm?.revision != null ? String(rm.revision) : "—"}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd className="mono small" title={String(rm?.updated_at ?? "")}>
                  {rm?.updated_at ? String(rm.updated_at) : "—"}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{rm?.status != null ? String(rm.status) : "—"}</dd>
              </div>
              <div>
                <dt>Last update mode</dt>
                <dd>{rm?.last_update_mode != null ? String(rm.last_update_mode) : "—"}</dd>
              </div>
              <div>
                <dt>Alignment (last)</dt>
                <dd>
                  {rm?.last_alignment_score != null && rm.last_alignment_score !== ""
                    ? String(rm.last_alignment_score)
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Previewable HTML</dt>
                <dd>{hasPreviewable ? "yes" : "no"}</dd>
              </div>
              <div>
                <dt>Default entry</dt>
                <dd className="mono small">{defaultEntry ?? "—"}</dd>
              </div>
              <div>
                <dt>HTML paths</dt>
                <dd className="mono small">
                  {Array.isArray(ps?.html_paths) && ps.html_paths.length
                    ? (ps.html_paths as string[]).join(", ")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Block anchors</dt>
                <dd className="mono small">
                  {Array.isArray(ps?.block_preview_anchors) && ps.block_preview_anchors.length
                    ? (ps.block_preview_anchors as string[]).join(", ")
                    : "—"}
                </dd>
              </div>
            </dl>
            <p className="muted small" style={{ marginBottom: "0.5rem" }}>
              Preview reloads every {PREVIEW_REFRESH_MS / 60_000} min (and metadata refetches on the same
              interval). Use <strong>Refresh now</strong> for an immediate iframe reload — not tied to
              graph iteration timing.
              <button
                type="button"
                onClick={() => void refresh(true)}
                style={{
                  background: "none",
                  border: "none",
                  color: "#7cb7ff",
                  cursor: "pointer",
                  textDecoration: "underline",
                  padding: 0,
                  font: "inherit",
                  marginLeft: "0.35rem",
                }}
              >
                Refresh now
              </button>
            </p>
            <p className="small" style={{ marginBottom: 0 }}>
              <MaterializeReviewSnapshotButton threadId={threadId} />{" "}
              <span className="muted small">
                Create a frozen staging review row from this live state (when automatic snapshots were
                skipped by policy).
              </span>
            </p>
          </div>
        </div>
        <div className="live-habitat-split__console">
          <AgentThoughtStream threadId={threadId} revision={revision} status={status} />
        </div>
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useState } from "react";

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
          setErr(
            typeof (parsed as { error?: string }).error === "string"
              ? (parsed as { error: string }).error
              : `HTTP ${r.status}`,
          );
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

  return (
    <div className="live-habitat-root">
      {err ? (
        <p className="muted small" role="alert" style={{ color: "#e74c3c" }}>
          {err}
        </p>
      ) : null}
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
          Live metadata
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
        <p className="muted small" style={{ marginBottom: 0 }}>
          Preview above reloads every {PREVIEW_REFRESH_MS / 60_000} minutes (same assembly as run staging
          preview).{" "}
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
            }}
          >
            Refresh now
          </button>
        </p>
      </div>
    </div>
  );
}

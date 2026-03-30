"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

const POLL_MS = 1500;
const POLL_MAX = 200;

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

function terminalStatus(st: string | null): boolean {
  const s = (st || "").toLowerCase();
  return s === "completed" || s === "failed";
}

type Phase = "idle" | "starting" | "polling" | "detail" | "success" | "failed";

type SmokeRow = {
  label: string;
  preset: string;
  phase: Phase;
  graphRunId: string | null;
  stagingSnapshotId: string | null;
  runStatus: string | null;
  error: string | null;
  note: string | null;
  /** From GET /api/staging/{id} when available */
  hasStaticFrontend: boolean | null;
  hasPreviewableHtml: boolean | null;
  staticFileCount: number | null;
  hasGalleryStrip: boolean | null;
  galleryImageArtifacts: number | null;
  contentKind: string | null;
};

function emptyRow(label: string, preset: string): SmokeRow {
  return {
    label,
    preset,
    phase: "idle",
    graphRunId: null,
    stagingSnapshotId: null,
    runStatus: null,
    error: null,
    note: null,
    hasStaticFrontend: null,
    hasPreviewableHtml: null,
    staticFileCount: null,
    hasGalleryStrip: null,
    galleryImageArtifacts: null,
    contentKind: null,
  };
}

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, { cache: "no-store", ...init });
  const text = await res.text();
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * Operator/dev verification: start a seeded run, poll, then load detail + staging read models.
 * All traffic via Next.js API routes → orchestrator (no KiloClaw from the browser).
 */
export function VerificationSmokePanel() {
  const [staticRow, setStaticRow] = useState(() =>
    emptyRow("Static preview path", "seeded_local_v1"),
  );
  const [imageRow, setImageRow] = useState(() =>
    emptyRow("Image artifact path", "seeded_gallery_strip_v1"),
  );
  const [busy, setBusy] = useState<"static" | "image" | null>(null);

  const runOne = useCallback(
    async (kind: "static" | "image") => {
      const preset =
        kind === "static" ? "seeded_local_v1" : "seeded_gallery_strip_v1";
      const setRow = kind === "static" ? setStaticRow : setImageRow;
      setBusy(kind);
      setRow((r) => ({
        ...emptyRow(r.label, r.preset),
        label: r.label,
        preset,
        phase: "starting",
      }));

      let graphRunId: string | null = null;

      try {
        const startRes = await fetch("/api/orchestrator/runs/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenario_preset: preset }),
        });
        const startWrap = (await startRes.json()) as {
          ok?: boolean;
          data?: unknown;
          error?: string;
        };
        if (!startRes.ok || startWrap.ok === false) {
          throw new Error(
            startWrap.error ||
              `Start failed HTTP ${startRes.status}`,
          );
        }
        const inner = startWrap.data;
        const gid =
          isRecord(inner) ? str(inner.graph_run_id) : null;
        if (!gid) {
          throw new Error("No graph_run_id in start response");
        }
        graphRunId = gid;
        setRow((r) => ({
          ...r,
          phase: "polling",
          graphRunId: gid,
        }));

        let status: string | null = null;
        for (let i = 0; i < POLL_MAX; i++) {
          const proxy = (await fetchJson(
            `/api/orchestrator/runs/${encodeURIComponent(gid)}`,
          )) as { ok?: boolean; data?: unknown };
          const data = isRecord(proxy.data) ? proxy.data : null;
          status = data ? str(data.status) : null;
          setRow((r) => ({ ...r, runStatus: status }));
          if (status && terminalStatus(status)) break;
          await new Promise((x) => setTimeout(x, POLL_MS));
        }

        if (!terminalStatus(status)) {
          throw new Error(
            "Run did not reach completed/failed within time budget — fetch run manually",
          );
        }

        setRow((r) => ({ ...r, phase: "detail" }));

        const detail = await fetchJson(
          `/api/runs/${encodeURIComponent(gid)}`,
        );
        if (!isRecord(detail)) {
          throw new Error("Unexpected detail response");
        }
        const ao = detail.associated_outputs;
        const stagingId =
          isRecord(ao) && typeof ao.staging_snapshot_id === "string"
            ? ao.staging_snapshot_id
            : null;

        if (!stagingId) {
          const failed = (status || "").toLowerCase() === "failed";
          setRow((r) => ({
            ...r,
            phase: "failed",
            stagingSnapshotId: null,
            error: failed
              ? "Run failed before staging snapshot (see Graph run debug panel for failure fields)"
              : "No staging_snapshot_id on detail — run may not have produced staging yet",
            note:
              kind === "static"
                ? "Seeded local runs do not guarantee static_frontend_file_v1; generator must emit static artifacts for preview HTML."
                : "Gallery strip runs normally produce a staging row when the graph completes staging.",
          }));
          return;
        }

        const st = await fetch(`/api/staging/${encodeURIComponent(stagingId)}`, {
          cache: "no-store",
        });
        const stJson = (await st.json()) as Record<string, unknown>;
        if (!st.ok) {
          setRow((r) => ({
            ...r,
            phase: "failed",
            stagingSnapshotId: stagingId,
            error:
              typeof stJson.error === "string"
                ? stJson.error
                : `Staging GET HTTP ${st.status}`,
          }));
          return;
        }

        const hasStatic = stJson.has_static_frontend === true;
        const hasPrev = stJson.has_previewable_html === true;
        const sfc =
          typeof stJson.static_frontend_file_count === "number"
            ? stJson.static_frontend_file_count
            : null;
        const hasG = stJson.has_gallery_strip === true;
        const gia =
          typeof stJson.gallery_image_artifact_count === "number"
            ? stJson.gallery_image_artifact_count
            : null;
        const ck =
          typeof stJson.content_kind === "string" ? stJson.content_kind : null;

        setRow((r) => ({
          ...r,
          phase: "success",
          stagingSnapshotId: stagingId,
          hasStaticFrontend: hasStatic,
          hasPreviewableHtml: hasPrev,
          staticFileCount: sfc,
          hasGalleryStrip: hasG,
          galleryImageArtifacts: gia,
          contentKind: ck,
          note:
            kind === "static"
              ? hasPrev
                ? "has_previewable_html: open static preview below"
                : "No previewable static bundle yet — static preview URL may 404 until generator emits static_frontend_file_v1"
              : hasG
                ? "Gallery strip present — review staging for image artifacts"
                : "Staging exists but no gallery strip in payload (check generator output)",
        }));
      } catch (e) {
        setRow((r) => ({
          ...r,
          phase: "failed",
          graphRunId,
          error: e instanceof Error ? e.message : String(e),
        }));
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const renderRow = (row: SmokeRow, kind: "static" | "image") => {
    const sid = row.stagingSnapshotId;
    const gid = row.graphRunId;
    const reviewUrl = sid ? `/review/staging/${encodeURIComponent(sid)}` : null;
    const staticPreviewUrl = sid
      ? `/api/staging/${encodeURIComponent(sid)}/static-preview`
      : null;

    return (
      <div
        style={{
          border: "1px solid #2a2a33",
          borderRadius: 6,
          padding: "0.75rem 1rem",
          marginBottom: "0.75rem",
          background: "#12121a",
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: "0.35rem" }}>{row.label}</div>
        <p className="muted" style={{ fontSize: "0.82rem", margin: "0 0 0.5rem" }}>
          Preset <code>{row.preset}</code> → POST <code>/api/orchestrator/runs/start</code> → poll{" "}
          <code>GET /api/orchestrator/runs/{"{id}"}</code> → <code>GET /api/runs/{"{id}"}</code> (detail) →{" "}
          <code>GET /api/staging/{"{id}"}</code>
        </p>
        <button
          type="button"
          onClick={() => void runOne(kind)}
          disabled={busy !== null}
          style={{ marginBottom: "0.5rem" }}
        >
          {busy === kind ? (
            <span className="cp-loading-line">
              <span className="cp-spinner" aria-hidden />
              Running…
            </span>
          ) : kind === "static" ? (
            "Run static preview smoke"
          ) : (
            "Run image artifact smoke"
          )}
        </button>
        {busy === kind && (row.phase === "polling" || row.phase === "detail") && (
          <p className="muted small" style={{ marginTop: "-0.25rem", marginBottom: "0.35rem" }}>
            Polling run status, then loading staging…
          </p>
        )}
        <dl className="debug-kv" style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
          <dt>state</dt>
          <dd>
            <code>{row.phase}</code>
            {row.runStatus ? (
              <>
                {" "}
                · run <code>{row.runStatus}</code>
              </>
            ) : null}
          </dd>
          {gid && (
            <>
              <dt>graph_run_id</dt>
              <dd>
                <Link href={`/runs/${encodeURIComponent(gid)}`} className="mono">
                  {gid}
                </Link>
              </dd>
            </>
          )}
          {sid && (
            <>
              <dt>staging_snapshot_id</dt>
              <dd className="mono">{sid}</dd>
            </>
          )}
          {row.contentKind != null && (
            <>
              <dt>content_kind</dt>
              <dd>{row.contentKind}</dd>
            </>
          )}
          {row.hasStaticFrontend != null && (
            <>
              <dt>has_static_frontend</dt>
              <dd>{row.hasStaticFrontend ? "yes" : "no"}</dd>
            </>
          )}
          {row.staticFileCount != null && (
            <>
              <dt>static_frontend_file_count</dt>
              <dd>{row.staticFileCount}</dd>
            </>
          )}
          {row.hasPreviewableHtml != null && (
            <>
              <dt>has_previewable_html</dt>
              <dd>{row.hasPreviewableHtml ? "yes" : "no"}</dd>
            </>
          )}
          {row.hasGalleryStrip != null && (
            <>
              <dt>has_gallery_strip</dt>
              <dd>{row.hasGalleryStrip ? "yes" : "no"}</dd>
            </>
          )}
          {row.galleryImageArtifacts != null && (
            <>
              <dt>gallery_image_artifact_count</dt>
              <dd>{row.galleryImageArtifacts}</dd>
            </>
          )}
        </dl>
        {row.error && (
          <p role="alert" style={{ color: "#f87171", fontSize: "0.88rem", marginTop: "0.5rem" }}>
            {row.error}
          </p>
        )}
        {row.note && (
          <p className="muted" style={{ fontSize: "0.82rem", marginTop: "0.35rem" }}>
            {row.note}
          </p>
        )}
        {sid && (
          <p style={{ fontSize: "0.88rem", marginTop: "0.5rem" }}>
            {reviewUrl && (
              <>
                <Link href={reviewUrl}>Staging review</Link>
                {" · "}
              </>
            )}
            {staticPreviewUrl && (
              <a href={staticPreviewUrl} target="_blank" rel="noopener noreferrer">
                Static preview (new tab)
              </a>
            )}
          </p>
        )}
      </div>
    );
  };

  return (
    <section aria-labelledby="verification-smoke-heading" className="cp-verify-section">
      <h2 id="verification-smoke-heading" className="op-section-title">
        Verification (smoke)
      </h2>
      <p className="muted" style={{ marginBottom: "0.75rem" }}>
        Quick checks after routing/budget changes: starts a <strong>seeded</strong> graph run via the
        orchestrator, waits for a terminal status, then loads staging metrics. Same APIs as the debug
        panel below — links surface run, staging, and static preview without digging into logs.
      </p>
      {renderRow(staticRow, "static")}
      {renderRow(imageRow, "image")}
    </section>
  );
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { IdentityContextLinks, IdentityNavExtras } from "@/app/components/IdentityNavExtras";
import { identityOverviewPath } from "@/lib/identity-nav";
import { serverOriginFromHeaders } from "@/lib/server-origin";
import type {
  LifecycleTimelineItem,
  LinkedPublicationItem,
  StagingDetail,
  StagingEvaluationDetail,
  StagingLineage,
} from "@/lib/api-types";
import {
  buildStagingOperatorActions,
  type StagingOperatorAction,
} from "@/lib/review-publication-audit-read-model";
import { ExperimentGalleryStrip } from "@/app/components/ExperimentGalleryStrip";
import { galleryStripVisibilityFromStagingPayload } from "@/lib/gallery-strip-visibility";
import { OperatorOutputSurface } from "@/app/components/OperatorOutputSurface";
import { parseUIGalleryStripV1FromPayload } from "@/lib/ui-gallery-strip-v1";
import { StagingReviewActions } from "./StagingReviewActions";
import { StagingFactsCard } from "@/app/components/StagingFactsCard";
import { ImageReviewSection } from "@/app/components/ImageReviewSection";

export const dynamic = "force-dynamic";

function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 8 ? `${s.slice(0, 8)}…` : id;
}

function isSafePreviewUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

function PayloadHints({ payload }: { payload: Record<string, unknown> | undefined }) {
  if (!payload || typeof payload !== "object") return null;
  const ids = payload.ids;
  const summary = payload.summary;
  const ev = payload.evaluation;
  const arts = payload.artifacts;
  const rows: { k: string; v: string }[] = [];

  if (ids && typeof ids === "object") {
    const o = ids as Record<string, unknown>;
    for (const key of ["thread_id", "graph_run_id", "build_candidate_id", "evaluation_report_id"]) {
      const v = o[key];
      if (v != null) rows.push({ k: key, v: String(v) });
    }
  }
  if (summary && typeof summary === "object") {
    const s = summary as Record<string, unknown>;
    if (typeof s.type === "string") rows.push({ k: "summary.type", v: s.type });
    if (typeof s.title === "string") rows.push({ k: "summary.title", v: s.title });
  }
  if (ev && typeof ev === "object") {
    const e = ev as Record<string, unknown>;
    if (typeof e.status === "string") rows.push({ k: "evaluation.status", v: e.status });
  }
  if (arts && typeof arts === "object") {
    const a = arts as { artifact_refs?: unknown };
    const n = Array.isArray(a.artifact_refs) ? a.artifact_refs.length : 0;
    rows.push({ k: "artifacts", v: `${n} ref(s)` });
  }

  if (rows.length === 0) return null;
  return (
    <dl className="debug-kv">
      {rows.flatMap((r) => [
        <dt key={`${r.k}-k`}>{r.k}</dt>,
        <dd key={`${r.k}-v`}>{r.v}</dd>,
      ])}
    </dl>
  );
}

function LifecycleTimeline({ items }: { items: LifecycleTimelineItem[] }) {
  if (!items.length) return null;
  return (
    <div className="debug-panel">
      <h2 className="op-section-title">Lifecycle (persisted)</h2>
      <p className="muted small">
        Derived from stored staging and publication rows only — not live graph execution.
      </p>
      <ul className="op-timeline">
        {items.map((it, i) => (
          <li
            key={`${it.kind}-${it.at ?? i}-${it.ref_publication_snapshot_id ?? ""}`}
            className={it.kind === "published" ? "op-timeline__pub" : undefined}
          >
            <span className="op-timeline__label">{it.label}</span>
            {it.at ? <span className="op-timeline__at">{formatWhen(it.at)}</span> : null}
            {it.ref_publication_snapshot_id ? (
              <span className="op-timeline__at">
                <Link href={`/publication/${encodeURIComponent(it.ref_publication_snapshot_id)}`}>
                  publication {shortId(it.ref_publication_snapshot_id)}
                </Link>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LineageSection({ lineage }: { lineage: StagingLineage | undefined }) {
  if (!lineage) return null;
  return (
    <div className="debug-panel">
      <h2 className="op-section-title">Lineage &amp; traceability</h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Identity and runtime ids — links open related operator surfaces.
      </p>
      <dl className="debug-kv pub-lineage-dl">
        <dt>identity_id</dt>
        <dd>
          {lineage.identity_id ? (
            <>
              <Link href={identityOverviewPath(lineage.identity_id)} title="Identity overview">
                {lineage.identity_id}
              </Link>
              <span className="muted small"> · </span>
              <IdentityContextLinks identityId={lineage.identity_id} />
            </>
          ) : (
            <span className="muted">—</span>
          )}
        </dd>
        <dt>thread_id</dt>
        <dd className="mono">{lineage.thread_id}</dd>
        <dt>graph_run_id</dt>
        <dd className="mono">
          {lineage.graph_run_id ? (
            <Link href={`/runs/${encodeURIComponent(lineage.graph_run_id)}`}>
              {lineage.graph_run_id}
            </Link>
          ) : (
            "—"
          )}
        </dd>
        <dt>build_candidate_id</dt>
        <dd className="mono">{lineage.build_candidate_id}</dd>
        <dt>evaluation_report_id</dt>
        <dd className="mono">{lineage.evaluation_report_id ?? "—"}</dd>
      </dl>
    </div>
  );
}

function EvaluationSection({ ev }: { ev: StagingEvaluationDetail | undefined }) {
  if (!ev || !ev.present) {
    return (
      <div className="op-eval-detail">
        <p className="muted" style={{ marginTop: 0 }}>
          No evaluation block in persisted snapshot payload.
        </p>
      </div>
    );
  }
  const mp = ev.metrics_preview ?? {};
  const mpKeys = Object.keys(mp);
  return (
    <div className="op-eval-detail">
      <h2 className="op-section-title" style={{ marginTop: 0 }}>
        Evaluation (persisted)
      </h2>
      <p className="muted small">
        From the evaluator output embedded in the staging snapshot — not a live LangGraph poll.
      </p>
      <dl className="debug-kv">
        <dt>status</dt>
        <dd>
          <span className="op-badge op-badge--neutral">{ev.status ?? "—"}</span>
        </dd>
        <dt>summary</dt>
        <dd>{ev.summary || "—"}</dd>
        <dt>issues</dt>
        <dd>{ev.issue_count ?? 0}</dd>
        <dt>artifact refs</dt>
        <dd>{ev.artifact_count ?? 0}</dd>
        <dt>metrics keys</dt>
        <dd>{ev.metrics_key_count ?? 0}</dd>
      </dl>
      {mpKeys.length > 0 ? (
        <>
          <h3 className="op-subtitle">Metrics preview</h3>
          <dl className="debug-kv">
            {mpKeys.flatMap((k) => [
              <dt key={`${k}-k`} className="mono">
                {k}
              </dt>,
              <dd key={`${k}-v`} className="small">
                {String((mp as Record<string, unknown>)[k])}
              </dd>,
            ])}
          </dl>
        </>
      ) : null}
    </div>
  );
}

function StagingOperatorActionsPanel({ actions }: { actions: StagingOperatorAction[] }) {
  if (actions.length === 0) {
    return (
      <div className="debug-panel">
        <h2 className="op-section-title">Operator actions (persisted)</h2>
        <p className="muted small">
          Derived from staging <code>approved_at</code> / <code>approved_by</code> and linked
          publication rows only — nothing inferred from graph execution.
        </p>
        <p className="muted">No approval or publication actions recorded yet.</p>
      </div>
    );
  }
  return (
    <div className="debug-panel">
      <h2 className="op-section-title">Operator actions (persisted)</h2>
      <p className="muted small">
        Approve and publish steps recorded on stored rows — not inferred from graph runtime.
      </p>
      <ul className="op-list op-list--compact">
        {actions.map((a, i) => (
          <li key={`${a.kind}-${a.at}-${i}`} className="op-card op-card--compact">
            <p className="op-card__title">
              <span
                className={
                  a.kind === "published"
                    ? "op-badge op-badge--canon"
                    : a.kind === "rejected"
                      ? "op-badge op-badge--rejected"
                      : "op-badge op-badge--staging"
                }
              >
                {a.kind}
              </span>{" "}
              {a.label}
            </p>
            <dl className="debug-kv op-card__dl">
              <dt>when</dt>
              <dd>{formatWhen(a.at)}</dd>
              <dt>actor</dt>
              <dd>{a.actor ?? "—"}</dd>
              {a.kind === "published" && a.publicationSnapshotId ? (
                <>
                  <dt>publication</dt>
                  <dd className="mono">
                    <Link href={`/publication/${encodeURIComponent(a.publicationSnapshotId)}`}>
                      {shortId(a.publicationSnapshotId)}
                    </Link>
                  </dd>
                </>
              ) : null}
            </dl>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LinkedPublications({
  items,
}: {
  items: LinkedPublicationItem[];
}) {
  if (!items.length) return null;
  return (
    <div className="debug-panel debug-panel--ok">
      <h2 className="op-section-title">Canon — linked publication(s)</h2>
      <p className="muted small">
        These rows are the immutable canon line for this staging id. The server allows one publish
        per staging snapshot — for another canon snapshot, create a new staging row from the graph.
      </p>
      <ul className="op-list op-list--compact">
        {items.map((p) => (
          <li key={p.publication_snapshot_id} className="op-card op-card--compact">
            <p className="op-card__title">
              <Link href={`/publication/${encodeURIComponent(p.publication_snapshot_id)}`}>
                {shortId(p.publication_snapshot_id)}
              </Link>
              <span className="pub-index-row__badge" style={{ marginLeft: "0.35rem" }}>
                canon
              </span>
            </p>
            <p className="pub-index-row__meta-line mono small">{p.publication_snapshot_id}</p>
            <dl className="debug-kv op-card__dl">
              <dt>visibility</dt>
              <dd>
                <span className="op-badge op-badge--canon">{p.visibility}</span>
              </dd>
              <dt>published</dt>
              <dd>{formatWhen(p.published_at)}</dd>
              <dt>by</dt>
              <dd>{p.published_by ?? "—"}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default async function StagingReviewPage({
  params,
}: {
  params: { stagingSnapshotId: string };
}) {
  const { stagingSnapshotId } = params;
  const origin = serverOriginFromHeaders();
  const url = `${origin}/api/staging/${encodeURIComponent(stagingSnapshotId)}`;

  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    return (
      <>
        <h1 className="pub-page-title">Staging review</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not reach the server</p>
          <p className="pub-empty__body">{e instanceof Error ? e.message : String(e)}</p>
          <p style={{ marginTop: "1rem" }}>
            <Link href="/review">← Review list</Link>
          </p>
        </div>
      </>
    );
  }

  const text = await res.text();
  let data: StagingDetail | null = null;
  try {
    data = JSON.parse(text) as StagingDetail;
  } catch {
    /* handled below */
  }

  if (res.status === 404) {
    notFound();
  }

  if (!res.ok || !data) {
    const err =
      typeof data?.error === "string"
        ? data.error
        : text.slice(0, 400);
    return (
      <>
        <h1 className="pub-page-title">Staging review</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load this staging snapshot</p>
          <p className="pub-empty__body">
            HTTP {res.status}. {err}
          </p>
          <p style={{ marginTop: "1rem" }}>
            <Link href="/review">← Review list</Link>
          </p>
        </div>
      </>
    );
  }

  const title = data.short_title?.trim() || `Staging ${data.staging_snapshot_id}`;
  const payload = data.snapshot_payload_json;
  const previewFromPayload =
    payload &&
    typeof payload.preview === "object" &&
    payload.preview !== null &&
    typeof (payload.preview as Record<string, unknown>).preview_url === "string"
      ? String((payload.preview as Record<string, unknown>).preview_url).trim()
      : "";
  const preview = (data.preview_url?.trim() || previewFromPayload || "") as string;
  const showIframe = preview && isSafePreviewUrl(preview);
  const showStaticFePreview = data.has_previewable_html === true;
  const staticPreviewSrc = `/api/staging/${encodeURIComponent(data.staging_snapshot_id)}/static-preview`;
  const rr = data.review_readiness ?? {};
  const linked = data.linked_publications ?? [];
  const timeline = data.lifecycle_timeline ?? [];
  const lineage = data.lineage;
  const evaluation = data.evaluation;
  const stagingOperatorActions = buildStagingOperatorActions(data);

  const identityForNav =
    (data.identity_id && String(data.identity_id).trim()) ||
    (data.lineage?.identity_id && String(data.lineage.identity_id).trim()) ||
    null;

  const lineageIdentity = lineage?.identity_id ?? data.identity_id ?? null;
  const evalStatus = evaluation?.present ? evaluation.status : null;
  const evalSummary = data.evaluation_summary?.trim() || null;
  const hasCanon = linked.length > 0;
  const primaryPub = linked[0]?.publication_snapshot_id ?? null;
  const galleryStrip = parseUIGalleryStripV1FromPayload(payload);
  const gv = galleryStripVisibilityFromStagingPayload(
    payload && typeof payload === "object" ? (payload as Record<string, unknown>) : undefined,
  );
  const showGalleryStripBanner =
    data.content_kind === "gallery_strip" || data.has_gallery_strip === true || gv.hasGalleryStrip;

  return (
    <>
      <p className="muted small cp-crumb-line">
        <Link href="/review">← Review list</Link>
        {identityForNav ? (
          <>
            {" · "}
            <IdentityNavExtras identityId={identityForNav} />
          </>
        ) : null}
      </p>

      <h1 className="pub-page-title">{title}</h1>
      <p className="pub-page-id mono">{data.staging_snapshot_id}</p>

      {showGalleryStripBanner ? (
        <p className="op-banner op-banner--gallery-strip" style={{ marginBottom: "0.75rem" }}>
          <span className="op-badge op-badge--gallery" style={{ marginRight: "0.5rem" }}>
            Gallery strip
          </span>
          <span className="muted small">
            {data.gallery_strip_item_count ?? gv.galleryStripItemCount} items ·{" "}
            {data.gallery_image_artifact_count ?? gv.galleryImageArtifactCount} image artifact(s) ·{" "}
            {data.gallery_items_with_artifact_key ?? gv.galleryItemsWithArtifactKey} linked by key
          </span>
        </p>
      ) : null}

      {showStaticFePreview ? (
        <p className="op-banner op-banner--neutral" style={{ marginBottom: "0.75rem" }}>
          <span className="op-badge op-badge--neutral" style={{ marginRight: "0.5rem" }}>
            Static HTML/CSS/JS
          </span>
          <span className="muted small">
            {data.static_frontend_file_count ?? 0} file(s) · {data.static_frontend_bundle_count ?? 0}{" "}
            bundle(s) — assembled preview below
          </span>
        </p>
      ) : null}

      <p className="op-banner op-banner--staging" style={{ marginBottom: "1rem" }}>
        <strong>Staging (review surface)</strong> — persisted snapshot for operator review. Canon
        is a separate <Link href="/publication">publication</Link> snapshot.
      </p>

      <StagingFactsCard staging={data} publicationSnapshotId={primaryPub} />

      {(showGalleryStripBanner || (data.gallery_image_artifact_count ?? 0) > 0) && (
        <ImageReviewSection
          hasGalleryStrip={data.has_gallery_strip === true || gv.hasGalleryStrip}
          galleryStripItemCount={data.gallery_strip_item_count ?? gv.galleryStripItemCount}
          galleryImageArtifactCount={data.gallery_image_artifact_count ?? gv.galleryImageArtifactCount}
          galleryItemsWithArtifactKey={
            data.gallery_items_with_artifact_key ?? gv.galleryItemsWithArtifactKey
          }
          hasPreviewableHtml={showStaticFePreview}
          staticPreviewHref={staticPreviewSrc}
          payload={payload && typeof payload === "object" ? (payload as Record<string, unknown>) : undefined}
          galleryStrip={galleryStrip}
        />
      )}

      <section className="pub-hero" aria-labelledby="staging-hero-h">
        <div className="pub-hero__head">
          <h2 id="staging-hero-h" className="op-section-title" style={{ margin: 0 }}>
            Staging at a glance
          </h2>
          <span className="pub-hero__timestamp" title="When this staging row was created">
            Created {formatWhen(data.created_at)}
          </span>
        </div>
        <div className="pub-hero__grid">
          <div>
            <span className="pub-hero__label">Status</span>
            <div className="pub-hero__value">
              <span
                className={
                  data.status === "rejected"
                    ? "op-badge op-badge--rejected"
                    : "op-badge op-badge--staging"
                }
              >
                {data.status}
              </span>
              {data.status === "review_ready" ? (
                <span className="muted small" style={{ marginLeft: "0.35rem" }}>
                  Awaiting operator approval
                </span>
              ) : null}
              {data.status === "rejected" ? (
                <span className="muted small" style={{ marginLeft: "0.35rem" }}>
                  Closed — no approve or publish
                </span>
              ) : null}
            </div>
          </div>
          <div>
            <span className="pub-hero__label">Evaluation (payload)</span>
            <div className="pub-hero__value">
              {evalStatus ? (
                <span className="op-badge op-badge--neutral">{evalStatus}</span>
              ) : (
                <span className="muted">—</span>
              )}
            </div>
            {evalSummary ? (
              <p className="small muted" style={{ margin: "0.35rem 0 0", lineHeight: 1.45 }}>
                {evalSummary.length > 220 ? `${evalSummary.slice(0, 220)}…` : evalSummary}
              </p>
            ) : null}
          </div>
          <div>
            <span className="pub-hero__label">Canon</span>
            <div className="pub-hero__value">
              {hasCanon && primaryPub ? (
                <>
                  <span className="op-badge op-badge--canon">Published</span>
                  <span className="muted small" style={{ marginLeft: "0.35rem" }}>
                    {linked.length} snapshot(s)
                  </span>
                  <p className="muted small" style={{ margin: "0.35rem 0 0", lineHeight: 1.45 }}>
                    Immutable publication row(s) for this staging id — duplicate publish is blocked.
                  </p>
                  <div style={{ marginTop: "0.35rem" }}>
                    <Link
                      className="op-btn op-btn--primary"
                      href={`/publication/${encodeURIComponent(primaryPub)}`}
                    >
                      Open canon (publication) →
                    </Link>
                  </div>
                </>
              ) : data.status === "rejected" ? (
                <span className="muted">Not available — staging is rejected</span>
              ) : data.status === "approved" ? (
                <>
                  <span className="op-badge op-badge--publish">Publish-ready</span>
                  <p className="muted small" style={{ margin: "0.35rem 0 0", lineHeight: 1.45 }}>
                    No canon row yet — use <strong>Publish to canon</strong> in operator actions
                    below (once).
                  </p>
                </>
              ) : data.status === "review_ready" ? (
                <p className="muted small" style={{ margin: 0, lineHeight: 1.45 }}>
                  Not published — <strong>approve</strong> staging first, then publish once.
                </p>
              ) : (
                <span className="muted">Not published to canon yet</span>
              )}
            </div>
          </div>
        </div>

        {(lineageIdentity || lineage?.thread_id || lineage?.graph_run_id) && (
          <div className="pub-hero__grid" style={{ marginTop: "0.85rem" }}>
            <div>
              <span className="pub-hero__label">Identity</span>
              <div className="pub-hero__value small">
                {lineageIdentity ? (
                  <>
                    <Link href={identityOverviewPath(lineageIdentity)}>{lineageIdentity}</Link>
                    <span className="muted small"> · </span>
                    <IdentityContextLinks identityId={lineageIdentity} />
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </div>
            </div>
            <div>
              <span className="pub-hero__label">Thread / run</span>
              <div className="pub-hero__value mono small">
                {lineage?.thread_id ? <span>{lineage.thread_id}</span> : <span className="muted">—</span>}
                {lineage?.graph_run_id ? (
                  <>
                    <br />
                    <Link href={`/runs/${encodeURIComponent(lineage.graph_run_id)}`}>
                      Run {shortId(lineage.graph_run_id)}
                    </Link>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </section>

      {galleryStrip ? (
        <ExperimentGalleryStrip
          data={galleryStrip}
          contextLabel="Gallery strip (bounded UI experiment)"
        />
      ) : null}

      <OperatorOutputSurface
        payload={payload}
        rowPreviewUrl={data.preview_url}
        evaluation={evaluation}
        graphRunId={lineage?.graph_run_id ?? data.graph_run_id ?? null}
        variant="staging"
      />

      {showStaticFePreview ? (
        <div className="op-panel op-panel--embed">
          <h2 className="op-section-title">Static front-end preview</h2>
          <p className="muted small">
            Assembled from persisted <code className="mono">static_frontend_file_v1</code> artifacts
            (inlined CSS/JS from the same bundle). Same-origin iframe — scripts run sandboxed.
          </p>
          <p className="small" style={{ marginTop: "0.35rem" }}>
            <a className="op-btn op-btn--secondary" href={staticPreviewSrc} target="_blank" rel="noreferrer">
              Open preview in new tab
            </a>
          </p>
          <div className="op-preview-frame">
            <iframe
              title="Static staging preview"
              src={staticPreviewSrc}
              sandbox="allow-scripts allow-same-origin"
              loading="lazy"
            />
          </div>
        </div>
      ) : null}

      {showIframe ? (
        <div className="op-panel op-panel--embed">
          <h2 className="op-section-title">Embedded preview</h2>
          <p className="muted small">
            Sandboxed iframe; if the site blocks embedding, use <strong>Open preview in new tab</strong>{" "}
            above.
          </p>
          <div className="op-preview-frame">
            <iframe
              title="Staging preview"
              src={preview}
              sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
              loading="lazy"
            />
          </div>
        </div>
      ) : null}

      {data.review_readiness_explanation ? (
        <div className="op-banner op-banner--neutral" role="status">
          <strong>Review readiness.</strong>{" "}
          <span className="muted">
            ready={String(rr.ready)} · approved={String(rr.approved)} · rejected=
            {String(rr.rejected)} · staging_status={String(rr.staging_status ?? data.status)}
          </span>
          <p className="small" style={{ margin: "0.5rem 0 0", color: "var(--fg)" }}>
            {data.review_readiness_explanation}
          </p>
        </div>
      ) : null}

      <div className="debug-panel">
        <h2 className="op-section-title">Staging record</h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          Persisted columns — use for audit and correlation with runs and canon.
        </p>
        <dl className="debug-kv">
          <dt>payload_version</dt>
          <dd>{data.payload_version ?? "—"}</dd>
          {data.approved_at ? (
            <>
              <dt>approved_at</dt>
              <dd>{formatWhen(data.approved_at)}</dd>
            </>
          ) : null}
          {data.approved_by ? (
            <>
              <dt>approved_by</dt>
              <dd className="mono">{data.approved_by}</dd>
            </>
          ) : null}
          {data.rejected_at ? (
            <>
              <dt>rejected_at</dt>
              <dd>{formatWhen(data.rejected_at)}</dd>
            </>
          ) : null}
          {data.rejected_by ? (
            <>
              <dt>rejected_by</dt>
              <dd className="mono">{data.rejected_by}</dd>
            </>
          ) : null}
          {data.rejection_reason ? (
            <>
              <dt>rejection_reason</dt>
              <dd>{data.rejection_reason}</dd>
            </>
          ) : null}
          {data.identity_hint ? (
            <>
              <dt>identity_hint</dt>
              <dd className="mono">{data.identity_hint}</dd>
            </>
          ) : null}
        </dl>
      </div>

      <LinkedPublications items={linked} />

      <StagingOperatorActionsPanel actions={stagingOperatorActions} />

      <LifecycleTimeline items={timeline} />

      <LineageSection lineage={lineage} />

      <details className="debug-panel">
        <summary>Evaluation metrics &amp; counts (persisted)</summary>
        <EvaluationSection ev={evaluation} />
      </details>

      <details className="debug-panel">
        <summary>Payload hints (debug)</summary>
        <PayloadHints payload={payload} />
      </details>

      <section className="staging-actions">
        <h2 className="op-section-title">Operator actions</h2>
        <StagingReviewActions
          stagingSnapshotId={data.staging_snapshot_id}
          status={data.status}
          linkedPublicationCount={linked.length}
          primaryLinkedPublicationId={linked[0]?.publication_snapshot_id ?? null}
        />
      </section>

      <details className="debug-panel">
        <summary>Raw JSON (debug)</summary>
        <pre className="op-pre">{JSON.stringify(data, null, 2)}</pre>
      </details>
    </>
  );
}

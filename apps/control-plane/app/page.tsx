import Link from "next/link";
import { ExperimentGalleryStrip } from "@/app/components/ExperimentGalleryStrip";
import type { OperatorHomeSummary } from "@/lib/api-types";
import { fetchGalleryStripForHomePage } from "@/lib/experiment-gallery-home";
import { serverOriginFromHeaders } from "@/lib/server-origin";

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
  return s.length >= 10 ? `${s.slice(0, 10)}…` : id;
}

export default async function HomePage() {
  const origin = serverOriginFromHeaders();
  const pinnedGallery = await fetchGalleryStripForHomePage(origin);
  let summary: OperatorHomeSummary | null = null;
  let httpError: string | null = null;
  try {
    const res = await fetch(`${origin}/api/operator-summary`, { cache: "no-store" });
    const text = await res.text();
    try {
      summary = JSON.parse(text) as OperatorHomeSummary;
    } catch {
      httpError = res.ok ? "Invalid JSON from /api/operator-summary" : text.slice(0, 200);
    }
    if (!res.ok && !httpError) {
      httpError =
        typeof summary?.error === "string"
          ? summary.error
          : `HTTP ${res.status} ${text.slice(0, 200)}`;
    }
  } catch (e) {
    httpError = e instanceof Error ? e.message : String(e);
  }

  const backendUnimplemented = summary?.backend_unimplemented === true;
  const rt = summary?.runtime;
  const rq = summary?.review_queue;
  const cn = summary?.canon;

  const rfv = rq?.ready_for_review ?? 0;
  const rtp = rq?.ready_to_publish ?? 0;
  const attention = rt?.runs_needing_attention ?? 0;

  return (
    <>
      <h1 className="pub-page-title">Operator summary</h1>
      <p className="muted" style={{ marginTop: "-0.2rem", marginBottom: "0.85rem" }}>
        Your command view over persisted orchestrator rows — bounded windows, not a live stream.
        Refresh to update counts; execution stays in the Python service. Use the global{" "}
        <strong>Flow</strong> strip in the header: <strong>Run</strong> → <strong>Review</strong> →{" "}
        <strong>Preview</strong> → <strong>Publish</strong> — then drill into a run or staging row
        for image and static output.
      </p>

      <p className="op-banner op-banner--neutral">
        <strong>What you are seeing.</strong> Aggregates from stored staging, publication, and
        graph_run tables only. Use <Link href="/runs">Runs</Link> to find a graph run,{" "}
        <Link href="/review">Review</Link> for staging snapshots and previews,{" "}
        <Link href="/publication">Publication</Link> for canon; optional{" "}
        <code className="mono">identity_id</code> filters tie the same lineage across surfaces.
        Where a row shows <code className="mono">identity_id</code>, follow its overview link for a
        compact cross-surface view.
      </p>

      <nav className="op-home-surface-links" aria-label="Primary operator surfaces">
        <Link className="op-home-surface-links__a op-home-surface-links__a--staging" href="/review">
          Review queue
        </Link>
        <Link className="op-home-surface-links__a op-home-surface-links__a--canon" href="/publication">
          Publication
        </Link>
        <Link className="op-home-surface-links__a op-home-surface-links__a--runs" href="/runs">
          Runs
        </Link>
      </nav>

      {pinnedGallery ? (
        <ExperimentGalleryStrip
          data={pinnedGallery.strip}
          contextLabel="Gallery strip (pinned staging)"
          stagingHref={`/review/staging/${encodeURIComponent(pinnedGallery.stagingId)}`}
        />
      ) : null}

      {httpError ? (
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load operator summary</p>
          <p className="pub-empty__body mono small">{httpError}</p>
          <p className="pub-empty__body" style={{ marginTop: "0.75rem" }}>
            <Link href="/review">Review</Link>
            {" · "}
            <Link href="/publication">Publication</Link>
            {" · "}
            <Link href="/runs">Runs</Link>
          </p>
        </div>
      ) : null}

      {!httpError && backendUnimplemented ? (
        <p className="op-banner op-banner--warn" role="status">
          <strong>Summary API not on this orchestrator build.</strong>{" "}
          {summary?.message ??
            "Counts may be placeholders until GET /orchestrator/operator-summary is available."}
        </p>
      ) : null}

      {!httpError ? (
        <div className="op-home-dashboard">
          <div className="op-home-card-grid">
            <section
              className="op-card op-card--compact op-home-card op-home-card--review"
              aria-labelledby="home-review-h"
            >
              <h2 id="home-review-h" className="op-section-title">
                <Link href="/review">Review queue</Link>
              </h2>
              <p className="muted small" style={{ marginBottom: "0.5rem" }}>
                Staging snapshots by review action — window up to 500 recent rows (
                <span className="mono">created_at</span>).
              </p>
              <div className="op-home-card__badges">
                {rfv > 0 ? (
                  <span className="op-badge op-badge--attention" title="ready_for_review">
                    {rfv} need review
                  </span>
                ) : (
                  <span className="op-badge op-badge--neutral">0 need review</span>
                )}
                {rtp > 0 ? (
                  <span className="op-badge op-badge--publish" title="ready_to_publish">
                    {rtp} ready to publish
                  </span>
                ) : null}
              </div>
              <dl className="pub-lineage-dl op-home-card__dl">
                <dt>Ready for review</dt>
                <dd>{rq?.ready_for_review ?? "—"}</dd>
                <dt>Ready to publish</dt>
                <dd>{rq?.ready_to_publish ?? "—"}</dd>
                <dt>Published (linked)</dt>
                <dd>{rq?.published ?? "—"}</dd>
                <dt>Other / not actionable</dt>
                <dd>{rq?.not_actionable ?? "—"}</dd>
              </dl>
              <p className="op-card__foot">
                <Link href="/review">Open review queue →</Link>
              </p>
            </section>

            <section
              className="op-card op-card--compact op-home-card op-home-card--canon"
              aria-labelledby="home-canon-h"
            >
              <h2 id="home-canon-h" className="op-section-title">
                <Link href="/publication">Canon</Link>
              </h2>
              <p className="muted small" style={{ marginBottom: "0.5rem" }}>
                Latest immutable publication in scope (same rule as publication index &quot;current&quot;).
              </p>
              <div className="op-home-card__badges">
                {cn?.has_current_publication ? (
                  <span className="op-badge op-badge--canon">Current snapshot present</span>
                ) : (
                  <span className="op-badge op-badge--neutral">No current publication</span>
                )}
              </div>
              <dl className="pub-lineage-dl op-home-card__dl">
                <dt>Latest snapshot</dt>
                <dd className="mono small">
                  {cn?.latest_publication_snapshot_id ? (
                    <Link
                      className="op-break-long"
                      href={`/publication/${encodeURIComponent(cn.latest_publication_snapshot_id)}`}
                    >
                      {shortId(cn.latest_publication_snapshot_id)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </dd>
                <dt>Published at</dt>
                <dd>{formatWhen(cn?.latest_published_at)}</dd>
              </dl>
              <p className="op-card__foot">
                <Link href="/publication">Open publication →</Link>
              </p>
            </section>

            <section
              className="op-card op-card--compact op-home-card op-home-card--runtime"
              aria-labelledby="home-runtime-h"
            >
              <h2 id="home-runtime-h" className="op-section-title">
                <Link href="/runs">Recent runs</Link>
              </h2>
              <p className="muted small" style={{ marginBottom: "0.5rem" }}>
                Graph runs in the summary window (up to {rt?.runs_in_window ?? "—"} loaded for
                counts).
              </p>
              <div className="op-home-card__badges">
                {attention > 0 ? (
                  <span className="op-badge op-badge--attention" title="Non-healthy attention_state">
                    {attention} need attention
                  </span>
                ) : (
                  <span className="op-badge op-badge--neutral">No attention flag</span>
                )}
              </div>
              <dl className="pub-lineage-dl op-home-card__dl">
                <dt>Runs in window</dt>
                <dd>{rt?.runs_in_window ?? "—"}</dd>
                <dt>Failed</dt>
                <dd>{rt?.failed_count ?? "—"}</dd>
                <dt>Paused</dt>
                <dd>{rt?.paused_count ?? "—"}</dd>
              </dl>
              <p className="op-card__foot">
                <Link href="/runs">Open runs →</Link>
              </p>
            </section>
          </div>
        </div>
      ) : null}

      <p className="muted small op-home-footnote cp-crumb-line" style={{ marginBottom: 0 }}>
        <Link href="/status">Status / graph debug</Link> — orchestrator health and local inspection
        (developer-oriented).
      </p>
    </>
  );
}

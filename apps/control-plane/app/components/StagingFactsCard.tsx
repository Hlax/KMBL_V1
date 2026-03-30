import Link from "next/link";
import type { StagingDetail } from "@/lib/api-types";

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 10 ? `${s.slice(0, 10)}…` : id;
}

/** Minimal persisted staging flags for list cards (maps from ProposalRow or staging GET). */
export type StagingFactsLike = {
  staging_snapshot_id: string;
  status?: string;
  has_static_frontend?: boolean;
  has_previewable_html?: boolean;
  has_gallery_strip?: boolean;
  gallery_image_artifact_count?: number;
};

type Props = {
  /** Full staging GET response */
  staging?: StagingDetail | null;
  /** Compact flags without full staging (e.g. review queue row) */
  facts?: StagingFactsLike | null;
  /** When fetch failed */
  error?: string | null;
  variant?: "full" | "compact";
  /** When set, show link to canon detail */
  publicationSnapshotId?: string | null;
};

function resolveFacts(
  staging: StagingDetail | null | undefined,
  facts: StagingFactsLike | null | undefined,
): StagingFactsLike | null {
  if (staging?.staging_snapshot_id) {
    return {
      staging_snapshot_id: staging.staging_snapshot_id,
      status: staging.status,
      has_static_frontend: staging.has_static_frontend,
      has_previewable_html: staging.has_previewable_html,
      has_gallery_strip: staging.has_gallery_strip,
      gallery_image_artifact_count: staging.gallery_image_artifact_count,
    };
  }
  if (facts?.staging_snapshot_id) {
    return facts;
  }
  return null;
}

/**
 * Consistent staging snapshot summary + actions (review + static preview when available).
 */
export function StagingFactsCard({
  staging,
  facts,
  error,
  variant = "full",
  publicationSnapshotId,
}: Props) {
  if (error) {
    return (
      <div className="op-card op-card--compact op-staging-facts">
        <p className="op-staging-facts__title">Staging snapshot</p>
        <p role="alert" className="muted small">
          Could not load staging flags: {error}
        </p>
      </div>
    );
  }
  const r = resolveFacts(staging ?? null, facts ?? null);
  if (!r) {
    return null;
  }
  const sid = r.staging_snapshot_id;
  const reviewHref = `/review/staging/${encodeURIComponent(sid)}`;
  const previewHref = `/api/staging/${encodeURIComponent(sid)}/static-preview`;
  const canPreview = r.has_previewable_html === true;
  const compact = variant === "compact";

  return (
    <div
      className={`op-card op-card--compact op-staging-facts${compact ? " op-staging-facts--compact" : ""}`}
    >
      <p className="op-staging-facts__title">Staging snapshot</p>
      <dl className="op-staging-facts__dl">
        <div>
          <dt>id</dt>
          <dd>
            <span className="mono small" title={sid}>
              {shortId(sid)}
            </span>
          </dd>
        </div>
        <div>
          <dt>status</dt>
          <dd>
            <span className="op-badge op-badge--neutral">{r.status ?? "—"}</span>
          </dd>
        </div>
        <div>
          <dt>static FE</dt>
          <dd>{r.has_static_frontend ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>previewable HTML</dt>
          <dd>{r.has_previewable_html ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>gallery strip</dt>
          <dd>{r.has_gallery_strip ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>image artifacts</dt>
          <dd>{r.gallery_image_artifact_count ?? 0}</dd>
        </div>
      </dl>
      <p className="op-staging-facts__actions">
        <Link href={reviewHref}>Open staging review</Link>
        {canPreview ? (
          <>
            {" · "}
            <a href={previewHref} target="_blank" rel="noopener noreferrer">
              Static preview
            </a>
          </>
        ) : (
          <span className="muted small"> · static preview unavailable (no previewable HTML)</span>
        )}
        {publicationSnapshotId ? (
          <>
            {" · "}
            <Link href={`/publication/${encodeURIComponent(publicationSnapshotId)}`}>
              Publication detail
            </Link>
          </>
        ) : null}
      </p>
    </div>
  );
}

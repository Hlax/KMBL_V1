import Link from "next/link";
import type { StagingDetail } from "@/lib/api-types";
import { artifactRoleCountsFromPayload } from "@/lib/image-artifact-read-model";
import { galleryStripVisibilityFromStagingPayload } from "@/lib/gallery-strip-visibility";

type Props = {
  staging: StagingDetail | null;
  error?: string | null;
};

/**
 * Publication detail: compact image context from source staging (no extra API).
 */
export function SourceStagingImageFacts({ staging, error }: Props) {
  if (error) {
    return (
      <div className="op-card op-card--compact op-source-image-facts" role="status">
        <p className="op-staging-facts__title">Source image (staging)</p>
        <p className="muted small">Could not load staging for image summary: {error}</p>
      </div>
    );
  }
  if (!staging?.staging_snapshot_id) return null;

  const payload =
    staging.snapshot_payload_json && typeof staging.snapshot_payload_json === "object"
      ? (staging.snapshot_payload_json as Record<string, unknown>)
      : undefined;
  const gv = galleryStripVisibilityFromStagingPayload(payload);
  const imageish =
    staging.has_gallery_strip === true ||
    (staging.gallery_image_artifact_count ?? 0) > 0 ||
    gv.hasGalleryStrip ||
    gv.galleryImageArtifactCount > 0;

  if (!imageish) return null;

  const roles = artifactRoleCountsFromPayload(payload);
  const sid = staging.staging_snapshot_id;
  const stagingHref = `/review/staging/${encodeURIComponent(sid)}`;

  return (
    <div className="op-card op-card--compact op-source-image-facts">
      <p className="op-staging-facts__title">Source image (staging)</p>
      <p className="muted small" style={{ marginTop: 0 }}>
        Canon payload mirrors this staging snapshot. Image-bearing summary from persisted staging
        flags and artifact roles.
      </p>
      <dl className="op-staging-facts__dl">
        <div>
          <dt>Gallery strip</dt>
          <dd>{staging.has_gallery_strip || gv.hasGalleryStrip ? "yes" : "no"}</dd>
        </div>
        <div>
          <dt>Image artifacts</dt>
          <dd>{staging.gallery_image_artifact_count ?? gv.galleryImageArtifactCount}</dd>
        </div>
        <div>
          <dt>Previewable HTML</dt>
          <dd>{staging.has_previewable_html ? "yes" : "no"}</dd>
        </div>
      </dl>
      {roles.length > 0 ? (
        <ul className="op-source-image-facts__roles">
          {roles.map((r) => (
            <li key={r.role}>
              <span className="op-badge op-badge--neutral">{r.label}</span>
              <span className="muted small"> ×{r.count}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">No artifact role fields on refs in payload (or empty refs).</p>
      )}
      <p className="op-staging-facts__actions" style={{ marginBottom: 0 }}>
        <Link href={stagingHref}>Open staging review for images →</Link>
      </p>
    </div>
  );
}

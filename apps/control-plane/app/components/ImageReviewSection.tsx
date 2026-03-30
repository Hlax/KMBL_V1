import type { UIGalleryStripV1 } from "@/lib/ui-gallery-strip-v1";
import {
  artifactRoleCountsFromPayload,
  galleryArtifactLinksFromPayload,
  stripPreviewThumbsFromGallery,
  type ArtifactRoleCount,
} from "@/lib/image-artifact-read-model";

type Props = {
  hasGalleryStrip: boolean;
  galleryStripItemCount: number;
  galleryImageArtifactCount: number;
  galleryItemsWithArtifactKey: number;
  hasPreviewableHtml: boolean;
  staticPreviewHref: string;
  payload: Record<string, unknown> | undefined;
  galleryStrip: UIGalleryStripV1 | null;
};

type PreviewTile = {
  key: string;
  label: string;
  src: string;
  linkHref: string;
  captionNote?: string;
};

function RoleChips({ rows }: { rows: ArtifactRoleCount[] }) {
  if (!rows.length) {
    return <span className="muted small">No artifact refs with a role field (or empty refs).</span>;
  }
  return (
    <ul className="op-image-review__roles">
      {rows.map((r) => (
        <li key={r.role}>
          <span className="op-badge op-badge--neutral">{r.label}</span>
          <span className="muted small"> ×{r.count}</span>
          <span className="mono small op-image-review__role-raw" title={r.role}>
            {r.role}
          </span>
        </li>
      ))}
    </ul>
  );
}

function buildPreviewTiles(
  galleryStrip: UIGalleryStripV1 | null,
  payload: Record<string, unknown> | undefined,
): PreviewTile[] {
  const stripThumbs = stripPreviewThumbsFromGallery(galleryStrip, 8);
  const out: PreviewTile[] = [];
  for (let i = 0; i < stripThumbs.length; i++) {
    const t = stripThumbs[i];
    const link = t.href || t.src;
    out.push({
      key: `strip-${i}`,
      label: t.label,
      src: t.src,
      linkHref: link,
      captionNote: t.imageArtifactKey ? `key: ${t.imageArtifactKey}` : undefined,
    });
  }
  if (out.length > 0) return out;
  const artifactLinks = galleryArtifactLinksFromPayload(payload, 8);
  for (let i = 0; i < artifactLinks.length; i++) {
    const a = artifactLinks[i];
    out.push({
      key: `art-${i}`,
      label: a.key,
      src: a.thumbUrl || a.url,
      linkHref: a.url,
      captionNote: "gallery_strip_image_v1",
    });
  }
  return out;
}

/**
 * Staging detail: scannable image/gallery review — facts, roles, safe thumbnails/links, next actions.
 */
export function ImageReviewSection({
  hasGalleryStrip,
  galleryStripItemCount,
  galleryImageArtifactCount,
  galleryItemsWithArtifactKey,
  hasPreviewableHtml,
  staticPreviewHref,
  payload,
  galleryStrip,
}: Props) {
  const roleCounts = artifactRoleCountsFromPayload(payload);
  const previewTiles = buildPreviewTiles(galleryStrip, payload);

  return (
    <section className="op-image-review" aria-labelledby="op-image-review-h">
      <div className="op-image-review__head">
        <h2 id="op-image-review-h" className="op-section-title" style={{ margin: 0 }}>
          Image review
        </h2>
        <p className="muted small" style={{ margin: "0.25rem 0 0" }}>
          Persisted payload only — use the gallery strip and static preview to verify output.
        </p>
      </div>

      <div className="op-image-review__quick">
        <div className="op-image-review__stat">
          <span className="op-image-review__stat-label">Gallery strip</span>
          <span className="op-image-review__stat-value">{hasGalleryStrip ? "Yes" : "No"}</span>
          <span className="muted small">
            {galleryStripItemCount} item{galleryStripItemCount === 1 ? "" : "s"}
          </span>
        </div>
        <div className="op-image-review__stat">
          <span className="op-image-review__stat-label">Image artifacts</span>
          <span className="op-image-review__stat-value">{galleryImageArtifactCount}</span>
          <span className="muted small">gallery_strip_image_v1</span>
        </div>
        <div className="op-image-review__stat">
          <span className="op-image-review__stat-label">Strip ↔ key</span>
          <span className="op-image-review__stat-value">{galleryItemsWithArtifactKey}</span>
          <span className="muted small">linked items</span>
        </div>
        <div className="op-image-review__stat">
          <span className="op-image-review__stat-label">Static preview</span>
          <span className="op-image-review__stat-value">{hasPreviewableHtml ? "Yes" : "No"}</span>
          <span className="muted small">composed HTML</span>
        </div>
      </div>

      <div className="op-image-review__roles-block">
        <h3 className="op-subtitle">Artifact roles (payload)</h3>
        <RoleChips rows={roleCounts} />
      </div>

      {previewTiles.length > 0 ? (
        <div className="op-image-review__tiles-wrap">
          <h3 className="op-subtitle">Quick look</h3>
          <ul className="op-image-review__tiles" aria-label="Image thumbnails">
            {previewTiles.map((t) => (
              <li key={t.key} className="op-image-review__tile">
                <a
                  href={t.linkHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="op-image-review__tile-link"
                >
                  <div className="op-image-review__tile-img">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={t.src} alt="" loading="lazy" decoding="async" />
                  </div>
                  <span className="op-image-review__tile-cap mono small">{t.label}</span>
                  {t.captionNote ? (
                    <span className="op-image-review__tile-note muted small">{t.captionNote}</span>
                  ) : null}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : hasGalleryStrip || galleryImageArtifactCount > 0 ? (
        <p className="muted small op-image-review__no-thumb">
          No http(s) image URLs on strip items or gallery artifacts — check{" "}
          <strong>Operator output</strong> below or payload (debug).
        </p>
      ) : null}

      <div className="op-image-review__next">
        <h3 className="op-subtitle">What to open next</h3>
        <ol className="op-image-review__next-list">
          {hasGalleryStrip ? (
            <li>
              <a href="#op-gallery-strip-section">Jump to gallery strip</a> on this page for full
              tiles and captions.
            </li>
          ) : (
            <li>No gallery strip in this payload — use artifact roles and operator output.</li>
          )}
          {hasPreviewableHtml ? (
            <li>
              <a href={staticPreviewHref} target="_blank" rel="noopener noreferrer">
                Open static preview
              </a>{" "}
              for composed HTML/CSS/JS (mirrors staging facts card).
            </li>
          ) : (
            <li>Static preview unavailable — no previewable HTML on this snapshot.</li>
          )}
          <li>
            Cross-check counts with the <strong>Staging snapshot</strong> facts card at the top of
            this page.
          </li>
        </ol>
      </div>
    </section>
  );
}

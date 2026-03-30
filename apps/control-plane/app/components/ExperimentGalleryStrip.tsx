import Link from "next/link";
import type { UIGalleryStripV1 } from "@/lib/ui-gallery-strip-v1";

type Props = {
  data: UIGalleryStripV1;
  /** Shown in panel header — e.g. "Staging preview" vs "Pinned experiment (homepage)" */
  contextLabel?: string;
  stagingHref?: string | null;
};

export function ExperimentGalleryStrip({ data, contextLabel, stagingHref }: Props) {
  const label = contextLabel ?? "Gallery strip (experiment)";
  return (
    <section
      className="op-gallery-strip"
      id="op-gallery-strip-section"
      aria-labelledby="op-gallery-strip-h"
    >
      <div className="op-gallery-strip__head">
        <h2 id="op-gallery-strip-h" className="op-section-title" style={{ margin: 0 }}>
          {label}
        </h2>
        {data.headline ? (
          <p className="op-gallery-strip__headline muted small" style={{ margin: "0.25rem 0 0" }}>
            {data.headline}
          </p>
        ) : null}
        {stagingHref ? (
          <p className="muted small" style={{ margin: "0.35rem 0 0" }}>
            <Link href={stagingHref}>Open staging review →</Link>
          </p>
        ) : null}
      </div>
      <ul className="op-gallery-strip__list">
        {data.items.map((it, i) => {
          const imgSrc = it.image_thumb_url || it.image_url || null;
          const imgAlt = it.image_alt?.trim() || it.label;
          return (
            <li key={`${it.label}-${i}`} className="op-gallery-strip__item">
              {imgSrc ? (
                <div className="op-gallery-strip__thumb-wrap">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    className="op-gallery-strip__thumb"
                    src={imgSrc}
                    alt={imgAlt}
                    loading="lazy"
                    decoding="async"
                  />
                  {it.image_artifact_key ? (
                    <span className="op-gallery-strip__artifact-badge" title="Image from persisted artifact_outputs">
                      artifact
                    </span>
                  ) : null}
                </div>
              ) : (
                <div className="op-gallery-strip__thumb-wrap op-gallery-strip__thumb-wrap--placeholder" />
              )}
              <div className="op-gallery-strip__body">
                {it.href ? (
                  <a
                    className="op-gallery-strip__label"
                    href={it.href}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {it.label}
                  </a>
                ) : (
                  <span className="op-gallery-strip__label">{it.label}</span>
                )}
                {it.image_artifact_key ? (
                  <p className="op-gallery-strip__meta mono small">
                    key <span className="op-break-long">{it.image_artifact_key}</span>
                  </p>
                ) : null}
                {it.caption ? (
                  <p className="op-gallery-strip__caption muted small">{it.caption}</p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

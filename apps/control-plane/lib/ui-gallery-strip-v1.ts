/**
 * Bounded UI experiment: gallery strip (matches orchestrator `ui_gallery_strip_v1`).
 * Persisted at staging `snapshot_payload_json.metadata.working_state_patch.ui_gallery_strip_v1`.
 */

export type UIGalleryStripItemV1 = {
  label: string;
  caption?: string | null;
  image_url?: string | null;
  /** From resolved gallery_strip_image_v1 artifact (optional smaller preview) */
  image_thumb_url?: string | null;
  href?: string | null;
  image_alt?: string | null;
  /** When set, primary image came from persisted artifact_outputs (reviewable) */
  image_artifact_key?: string | null;
};

export type UIGalleryStripV1 = {
  headline?: string | null;
  items: UIGalleryStripItemV1[];
};

function isHttpUrl(s: string): boolean {
  return s.startsWith("http://") || s.startsWith("https://");
}

function parseItem(raw: unknown): UIGalleryStripItemV1 | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const label = o.label;
  if (typeof label !== "string" || !label.trim()) return null;
  const caption =
    typeof o.caption === "string" && o.caption.trim() ? o.caption.trim() : null;
  let image_url: string | null = null;
  if (typeof o.image_url === "string" && o.image_url.trim()) {
    const u = o.image_url.trim();
    if (isHttpUrl(u)) image_url = u;
  }
  let image_thumb_url: string | null = null;
  if (typeof o.image_thumb_url === "string" && o.image_thumb_url.trim()) {
    const u = o.image_thumb_url.trim();
    if (isHttpUrl(u)) image_thumb_url = u;
  }
  let image_alt: string | null = null;
  if (typeof o.image_alt === "string" && o.image_alt.trim()) {
    image_alt = o.image_alt.trim().slice(0, 500);
  }
  let image_artifact_key: string | null = null;
  if (typeof o.image_artifact_key === "string" && o.image_artifact_key.trim()) {
    image_artifact_key = o.image_artifact_key.trim();
  }
  let href: string | null = null;
  if (typeof o.href === "string" && o.href.trim()) {
    const h = o.href.trim();
    if (isHttpUrl(h)) href = h;
  }
  return {
    label: label.trim(),
    caption,
    image_url,
    image_thumb_url,
    href,
    image_alt,
    image_artifact_key,
  };
}

/** Parse from staging/publication snapshot payload root (versioned v1 body). */
export function parseUIGalleryStripV1FromPayload(
  payload: unknown,
): UIGalleryStripV1 | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Record<string, unknown>;
  const meta = p.metadata;
  if (!meta || typeof meta !== "object") return null;
  const m = meta as Record<string, unknown>;
  const wsp = m.working_state_patch;
  if (!wsp || typeof wsp !== "object") return null;
  const patch = wsp as Record<string, unknown>;
  const raw = patch.ui_gallery_strip_v1;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const o = raw as Record<string, unknown>;
  const itemsRaw = o.items;
  if (!Array.isArray(itemsRaw) || itemsRaw.length === 0) return null;
  const items: UIGalleryStripItemV1[] = [];
  for (const it of itemsRaw) {
    const parsed = parseItem(it);
    if (parsed) items.push(parsed);
  }
  if (items.length === 0) return null;
  let headline: string | null = null;
  if (typeof o.headline === "string" && o.headline.trim()) {
    headline = o.headline.trim().slice(0, 160);
  }
  return { headline, items };
}

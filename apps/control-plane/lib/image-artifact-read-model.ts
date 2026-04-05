/**
 * Read-only helpers for image / artifact review from persisted staging (or publication) payloads.
 * No inference beyond payload fields — unknown roles are shown as persisted strings.
 */

import type { UIGalleryStripV1 } from "@/lib/ui-gallery-strip-v1";

function isHttpUrl(s: string): boolean {
  return s.startsWith("http://") || s.startsWith("https://");
}

/** Human labels only for known contract roles; otherwise return the persisted role string. */
export function artifactRoleDisplayLabel(role: string): string {
  if (role === "gallery_strip_image_v1") return "Gallery image";
  if (role === "static_frontend_file_v1") return "Static front-end file";
  if (role === "interactive_frontend_app_v1") return "Interactive front-end app";
  return role;
}

export type ArtifactRoleCount = {
  role: string;
  count: number;
  label: string;
};

/** Counts `artifacts.artifact_refs[].role` when present. */
export function artifactRoleCountsFromPayload(payload: unknown): ArtifactRoleCount[] {
  if (!payload || typeof payload !== "object") return [];
  const arts = (payload as Record<string, unknown>).artifacts;
  if (!arts || typeof arts !== "object") return [];
  const refs = (arts as Record<string, unknown>).artifact_refs;
  if (!Array.isArray(refs)) return [];
  const counts = new Map<string, number>();
  for (const r of refs) {
    if (!r || typeof r !== "object") continue;
    const role = (r as Record<string, unknown>).role;
    if (typeof role !== "string" || !role.trim()) continue;
    const k = role.trim();
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .map(([role, count]) => ({
      role,
      count,
      label: artifactRoleDisplayLabel(role),
    }))
    .sort((a, b) => b.count - a.count || a.role.localeCompare(b.role));
}

export type GalleryArtifactLink = {
  key: string;
  url: string;
  thumbUrl: string | null;
  label: string;
};

/** Persisted `gallery_strip_image_v1` rows with safe http(s) URLs — for compact review links. */
export function galleryArtifactLinksFromPayload(payload: unknown, limit = 12): GalleryArtifactLink[] {
  if (!payload || typeof payload !== "object") return [];
  const arts = (payload as Record<string, unknown>).artifacts;
  if (!arts || typeof arts !== "object") return [];
  const refs = (arts as Record<string, unknown>).artifact_refs;
  if (!Array.isArray(refs)) return [];
  const out: GalleryArtifactLink[] = [];
  for (const r of refs) {
    if (!r || typeof r !== "object") continue;
    const o = r as Record<string, unknown>;
    if (o.role !== "gallery_strip_image_v1") continue;
    const url = o.url;
    if (typeof url !== "string" || !isHttpUrl(url)) continue;
    const key = typeof o.key === "string" && o.key.trim() ? o.key.trim() : "—";
    let thumbUrl: string | null = null;
    const tu = o.thumb_url;
    if (typeof tu === "string" && isHttpUrl(tu)) thumbUrl = tu;
    out.push({
      key,
      url,
      thumbUrl,
      label: artifactRoleDisplayLabel("gallery_strip_image_v1"),
    });
    if (out.length >= limit) break;
  }
  return out;
}

export type StripPreviewThumb = {
  label: string;
  src: string;
  href: string | null;
  imageArtifactKey: string | null;
};

/** Thumbs from parsed gallery strip items (URLs already validated at parse time). */
export function stripPreviewThumbsFromGallery(
  galleryStrip: UIGalleryStripV1 | null,
  limit = 8,
): StripPreviewThumb[] {
  if (!galleryStrip?.items?.length) return [];
  const thumbs: StripPreviewThumb[] = [];
  for (const it of galleryStrip.items) {
    const src = (it.image_thumb_url || it.image_url || "").trim();
    if (!src || !isHttpUrl(src)) continue;
    let href: string | null = null;
    if (it.href && it.href.trim()) {
      const h = it.href.trim();
      if (isHttpUrl(h)) href = h;
    }
    thumbs.push({
      label: it.label,
      src,
      href,
      imageArtifactKey: it.image_artifact_key ?? null,
    });
    if (thumbs.length >= limit) break;
  }
  return thumbs;
}

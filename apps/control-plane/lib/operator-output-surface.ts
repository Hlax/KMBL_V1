/**
 * Derives operator-facing labels from persisted staging/publication payload JSON only.
 * Tolerant of partial or legacy shapes — no backend contract changes.
 */

export type PreviewSurface = {
  previewUrl: string | null;
  sandboxRef: string | null;
};

export type ProducedSummary = {
  line: string;
  typeLabel: string | null;
  title: string | null;
};

export type ArtifactSurfaceItem = {
  key: string;
  label: string;
  href: string | null;
  /** Safe http(s) URL for optional thumbnail */
  thumbUrl: string | null;
  sublabel: string | null;
  isImage: boolean;
};

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg)(\?|$)/i;

export function safeHttpUrl(raw: string | null | undefined): string | null {
  if (!raw || typeof raw !== "string") return null;
  const t = raw.trim();
  if (!t) return null;
  try {
    const u = new URL(t);
    return u.protocol === "http:" || u.protocol === "https:" ? t : null;
  } catch {
    return null;
  }
}

function looksLikeImageUrl(url: string): boolean {
  return IMAGE_EXT.test(url) || url.includes("/image") || url.includes("image/");
}

function pickString(obj: Record<string, unknown>, keys: string[]): string | null {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

export function extractPreviewFromPayload(payload: Record<string, unknown> | undefined): PreviewSurface {
  if (!payload) return { previewUrl: null, sandboxRef: null };
  const pv = payload.preview;
  if (!pv || typeof pv !== "object") return { previewUrl: null, sandboxRef: null };
  const o = pv as Record<string, unknown>;
  const pu = pickString(o, ["preview_url", "previewUrl"]);
  const sandbox = pickString(o, ["sandbox_ref", "sandboxRef"]);
  return {
    previewUrl: safeHttpUrl(pu),
    sandboxRef: sandbox && sandbox.length > 0 ? sandbox : null,
  };
}

/** Prefer row-level preview when present; fall back to payload.preview */
export function resolvePreviewUrl(
  rowPreview: string | null | undefined,
  payload: Record<string, unknown> | undefined,
): string | null {
  const fromRow = safeHttpUrl(rowPreview ?? undefined);
  if (fromRow) return fromRow;
  return extractPreviewFromPayload(payload).previewUrl;
}

export function deriveProducedSummary(payload: Record<string, unknown> | undefined): ProducedSummary | null {
  if (!payload) return null;
  const summary = payload.summary;
  let typeLabel: string | null = null;
  let title: string | null = null;
  if (summary && typeof summary === "object") {
    const s = summary as Record<string, unknown>;
    const ty = s.type;
    const ti = s.title;
    if (typeof ty === "string" && ty.trim()) typeLabel = ty.trim();
    if (typeof ti === "string" && ti.trim()) title = ti.trim();
  }
  const parts: string[] = [];
  if (typeLabel) parts.push(typeLabel);
  if (title) parts.push(title);
  if (parts.length === 0) return null;
  const line = parts.join(" · ");
  return { line, typeLabel, title };
}

export function extractArtifactRefs(payload: Record<string, unknown> | undefined): unknown[] {
  if (!payload) return [];
  const arts = payload.artifacts;
  if (!arts || typeof arts !== "object") return [];
  const ar = (arts as Record<string, unknown>).artifact_refs;
  return Array.isArray(ar) ? ar : [];
}

function objectKeysHint(obj: Record<string, unknown>): string {
  const keys = Object.keys(obj).slice(0, 6);
  return keys.length ? keys.join(", ") : "object";
}

function normalizeOneArtifact(raw: unknown, index: number): ArtifactSurfaceItem {
  const key = `artifact-${index}`;
  if (raw == null) {
    return {
      key,
      label: `Artifact ${index + 1}`,
      href: null,
      thumbUrl: null,
      sublabel: String(raw),
      isImage: false,
    };
  }
  if (typeof raw === "string") {
    const href = safeHttpUrl(raw);
    const isImg = href ? looksLikeImageUrl(href) : false;
    return {
      key,
      label: href ? (isImg ? "Image" : "Link") : `Value ${index + 1}`,
      href,
      thumbUrl: isImg ? href : null,
      sublabel: href ? null : raw.length > 80 ? `${raw.slice(0, 77)}…` : raw,
      isImage: isImg,
    };
  }
  if (typeof raw === "number" || typeof raw === "boolean") {
    return {
      key,
      label: `Artifact ${index + 1}`,
      href: null,
      thumbUrl: null,
      sublabel: String(raw),
      isImage: false,
    };
  }
  if (typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    const role = pickString(o, ["role"]);
    if (role === "gallery_strip_image_v1") {
      const artKey = pickString(o, ["key"]);
      const href = safeHttpUrl(pickString(o, ["url"])) ?? null;
      const thumb = safeHttpUrl(pickString(o, ["thumb_url"])) ?? null;
      const alt = pickString(o, ["alt"]);
      const label = artKey ? `Gallery image · ${artKey}` : "Gallery image (artifact)";
      return {
        key: artKey ? `gallery-${artKey}` : key,
        label,
        href,
        thumbUrl: thumb ?? href,
        sublabel: alt ?? (artKey ? `key ${artKey}` : null),
        isImage: true,
      };
    }
    const href =
      safeHttpUrl(pickString(o, ["url", "href", "src", "preview_url", "previewUrl", "asset_url", "public_url"])) ??
      null;
    const mime = pickString(o, ["mime", "mime_type", "content_type"]);
    const kind = pickString(o, ["kind", "type", "role", "name"]);
    const title = pickString(o, ["title", "label", "filename", "id"]);
    const isImage =
      (mime?.toLowerCase().startsWith("image/") ?? false) ||
      (kind?.toLowerCase() === "image") ||
      (href ? looksLikeImageUrl(href) : false);
    const label =
      title ||
      kind ||
      (href ? (isImage ? "Image" : "Asset link") : `Structured output ${index + 1}`);
    const sub =
      href
        ? null
        : `Keys: ${objectKeysHint(o)}`;
    return {
      key,
      label,
      href,
      thumbUrl: isImage && href ? href : null,
      sublabel: sub,
      isImage,
    };
  }
  return {
    key,
    label: `Artifact ${index + 1}`,
    href: null,
    thumbUrl: null,
    sublabel: typeof raw === "string" ? raw : "Unsupported shape",
    isImage: false,
  };
}

export function normalizeArtifactRefs(payload: Record<string, unknown> | undefined): ArtifactSurfaceItem[] {
  const refs = extractArtifactRefs(payload);
  return refs.map((r, i) => normalizeOneArtifact(r, i));
}

export function extractEvaluationIssueStrings(
  payload: Record<string, unknown> | undefined,
  maxItems: number,
): string[] {
  if (!payload || maxItems <= 0) return [];
  const ev = payload.evaluation;
  if (!ev || typeof ev !== "object") return [];
  const issues = (ev as Record<string, unknown>).issues;
  if (!Array.isArray(issues)) return [];
  const out: string[] = [];
  for (const it of issues) {
    if (out.length >= maxItems) break;
    if (typeof it === "string" && it.trim()) {
      out.push(it.trim());
      continue;
    }
    if (it && typeof it === "object") {
      const o = it as Record<string, unknown>;
      const msg = pickString(o, ["message", "detail", "text", "summary", "description"]);
      if (msg) {
        out.push(msg);
        continue;
      }
      const code = pickString(o, ["code", "kind"]);
      if (code) out.push(code);
    }
  }
  return out;
}

export function evaluationIssueTotal(payload: Record<string, unknown> | undefined): number {
  if (!payload) return 0;
  const ev = payload.evaluation;
  if (!ev || typeof ev !== "object") return 0;
  const issues = (ev as Record<string, unknown>).issues;
  return Array.isArray(issues) ? issues.length : 0;
}

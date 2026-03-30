/**
 * Client-side read-model for gallery-strip inspection (mirrors orchestrator
 * `gallery_strip_visibility_from_staging_payload`). Use with staging snapshot payload roots.
 */

export type GalleryStripVisibility = {
  hasGalleryStrip: boolean;
  galleryStripItemCount: number;
  galleryImageArtifactCount: number;
  totalArtifactRefs: number;
  galleryItemsWithArtifactKey: number;
  galleryItemsUnlinkedImageKey: number;
};

export function galleryStripVisibilityFromStagingPayload(
  payload: Record<string, unknown> | undefined,
): GalleryStripVisibility {
  if (!payload || typeof payload !== "object") {
    return {
      hasGalleryStrip: false,
      galleryStripItemCount: 0,
      galleryImageArtifactCount: 0,
      totalArtifactRefs: 0,
      galleryItemsWithArtifactKey: 0,
      galleryItemsUnlinkedImageKey: 0,
    };
  }
  const meta = payload.metadata;
  let wsp: Record<string, unknown> = {};
  if (meta && typeof meta === "object") {
    const ws = (meta as Record<string, unknown>).working_state_patch;
    if (ws && typeof ws === "object") wsp = ws as Record<string, unknown>;
  }
  const strip = wsp.ui_gallery_strip_v1;
  const items = strip && typeof strip === "object" && !Array.isArray(strip)
    ? (strip as Record<string, unknown>).items
    : null;
  const itemList = Array.isArray(items) ? items : [];
  let withKey = 0;
  for (const it of itemList) {
    if (it && typeof it === "object" && (it as Record<string, unknown>).image_artifact_key) {
      withKey += 1;
    }
  }
  const arts = payload.artifacts;
  let refs: unknown[] = [];
  if (arts && typeof arts === "object") {
    const ar = (arts as Record<string, unknown>).artifact_refs;
    if (Array.isArray(ar)) refs = ar;
  }
  let gImg = 0;
  for (const a of refs) {
    if (a && typeof a === "object" && (a as Record<string, unknown>).role === "gallery_strip_image_v1") {
      gImg += 1;
    }
  }
  const stripCount = itemList.length;
  return {
    hasGalleryStrip: itemList.length > 0,
    galleryStripItemCount: stripCount,
    galleryImageArtifactCount: gImg,
    totalArtifactRefs: refs.length,
    galleryItemsWithArtifactKey: withKey,
    galleryItemsUnlinkedImageKey: Math.max(0, stripCount - withKey),
  };
}

/** Maps persisted `event_input.scenario` to the API `scenario_badge` string (orchestrator). */
export function scenarioBadgeFromScenarioTag(tag: string | null | undefined): string | null {
  if (!tag) return null;
  if (tag === "kmbl_seeded_gallery_strip_varied_v1") return "gallery_varied";
  if (tag === "kmbl_seeded_gallery_strip_v1") return "gallery_strip";
  if (tag === "kmbl_seeded_local_v1") return "local_seed";
  return "other";
}

export function scenarioBadgeLabel(
  badge: string | null | undefined,
): { className: string; label: string } | null {
  if (!badge) return null;
  if (badge === "gallery_strip") return { className: "op-badge op-badge--gallery", label: "gallery" };
  if (badge === "gallery_varied")
    return { className: "op-badge op-badge--gallery-varied", label: "gallery · varied" };
  if (badge === "local_seed") return { className: "op-badge op-badge--neutral", label: "seeded local" };
  if (badge === "other") return { className: "op-badge op-badge--neutral", label: "scenario" };
  return { className: "op-badge op-badge--neutral", label: badge };
}

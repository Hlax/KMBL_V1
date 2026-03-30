import type { StagingDetail } from "@/lib/api-types";
import { parseUIGalleryStripV1FromPayload, type UIGalleryStripV1 } from "@/lib/ui-gallery-strip-v1";

/**
 * When `NEXT_PUBLIC_UI_GALLERY_STAGING_SNAPSHOT_ID` is set, homepage shows the persisted
 * gallery strip from that staging row (read-only; rollback = new staging snapshot).
 */
export async function fetchGalleryStripForHomePage(
  origin: string,
): Promise<{ strip: UIGalleryStripV1; stagingId: string } | null> {
  const id = process.env.NEXT_PUBLIC_UI_GALLERY_STAGING_SNAPSHOT_ID?.trim();
  if (!id) return null;
  let res: Response;
  try {
    res = await fetch(`${origin}/api/staging/${encodeURIComponent(id)}`, { cache: "no-store" });
  } catch {
    return null;
  }
  if (!res.ok) return null;
  let data: StagingDetail;
  try {
    data = (await res.json()) as StagingDetail;
  } catch {
    return null;
  }
  const strip = parseUIGalleryStripV1FromPayload(data.snapshot_payload_json);
  if (!strip) return null;
  return { strip, stagingId: data.staging_snapshot_id };
}

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * POST /api/staging/{id}/approve → orchestrator POST /orchestrator/staging/{id}/approve
 */
export async function POST(
  request: Request,
  context: { params: { stagingSnapshotId: string } },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { stagingSnapshotId } = context.params;
  const url = `${base}/orchestrator/staging/${encodeURIComponent(stagingSnapshotId)}/approve`;
  const bodyText = await request.text();
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": request.headers.get("Content-Type") ?? "application/json" },
      body: bodyText || "{}",
      cache: "no-store",
    });
    const text = await res.text();
    let data: unknown = text;
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      /* keep raw */
    }
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}

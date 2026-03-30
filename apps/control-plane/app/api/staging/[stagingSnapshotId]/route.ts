import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Product-facing read: GET /api/staging/{id} → orchestrator GET /orchestrator/staging/{id}.
 * Returns persisted staging_snapshot rows only (same contract as the orchestrator).
 */
export async function GET(
  _request: Request,
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
  const url = `${base}/orchestrator/staging/${encodeURIComponent(stagingSnapshotId)}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
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
      {
        error: e instanceof Error ? e.message : String(e),
      },
      { status: 502 },
    );
  }
}

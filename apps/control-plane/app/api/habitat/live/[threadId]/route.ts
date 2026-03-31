import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * GET /api/habitat/live/{threadId} → orchestrator GET /orchestrator/working-staging/{id}/live
 * Compact read model + preview surface (mutable working staging — not a review snapshot).
 */
export async function GET(
  _request: Request,
  context: { params: { threadId: string } },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { threadId } = context.params;
  const url = `${base}/orchestrator/working-staging/${encodeURIComponent(threadId)}/live`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      data = { raw: text };
    }
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}

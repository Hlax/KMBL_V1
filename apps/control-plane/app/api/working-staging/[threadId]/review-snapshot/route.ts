import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * POST → orchestrator POST /orchestrator/working-staging/{thread_id}/review-snapshot
 * (materialize frozen staging_snapshot from live working staging + last eval/bc).
 */
export async function POST(
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
  const url = `${base}/orchestrator/working-staging/${encodeURIComponent(threadId)}/review-snapshot`;
  try {
    const res = await fetch(url, { method: "POST", cache: "no-store" });
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

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * POST → orchestrator POST /orchestrator/runs/{id}/interrupt (cooperative stop).
 */
export async function POST(
  _request: Request,
  context: { params: { graphRunId: string } },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { graphRunId } = context.params;
  const url = `${base}/orchestrator/runs/${encodeURIComponent(graphRunId)}/interrupt`;
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

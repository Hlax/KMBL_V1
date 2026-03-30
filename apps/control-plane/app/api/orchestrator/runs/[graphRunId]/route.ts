import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Proxy GET /orchestrator/runs/{graph_run_id} → FastAPI.
 */
export async function GET(
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
  const url = `${base}/orchestrator/runs/${encodeURIComponent(graphRunId)}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    let data: unknown = text;
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      /* raw */
    }
    return NextResponse.json(
      { ok: res.ok, httpStatus: res.status, url, data },
      { status: res.ok ? 200 : res.status },
    );
  } catch (e) {
    return NextResponse.json(
      {
        ok: false,
        url,
        error: e instanceof Error ? e.message : String(e),
      },
      { status: 502 },
    );
  }
}

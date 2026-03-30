import { NextResponse } from "next/server";

import {
  fallbackGraphRunDetail,
  isOrchestratorRouteNotFound,
  parseJsonSafe,
} from "@/lib/orchestrator-proxy";

export const dynamic = "force-dynamic";

/**
 * Pass H: GET /api/runs/{graphRunId} → orchestrator GET /orchestrator/runs/{id}/detail.
 * Persisted run read model only (no live streaming).
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
  const url = `${base}/orchestrator/runs/${encodeURIComponent(graphRunId)}/detail`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    const parsed = parseJsonSafe(text);
    if (isOrchestratorRouteNotFound(res.status, parsed.ok ? parsed.value : null, !parsed.ok)) {
      return NextResponse.json(fallbackGraphRunDetail(graphRunId), { status: 200 });
    }
    const data = parsed.ok ? parsed.value : text;
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

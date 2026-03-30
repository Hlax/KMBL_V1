import { NextResponse } from "next/server";

import {
  fallbackStagingList,
  isOrchestratorRouteNotFound,
  parseJsonSafe,
} from "@/lib/orchestrator-proxy";

export const dynamic = "force-dynamic";

/**
 * GET /api/staging → orchestrator GET /orchestrator/staging (persisted snapshot list).
 * Pass-through of persisted rows only.
 */
export async function GET(request: Request) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { searchParams } = new URL(request.url);
  const q = searchParams.toString();
  const url = `${base}/orchestrator/staging${q ? `?${q}` : ""}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    const parsed = parseJsonSafe(text);
    if (isOrchestratorRouteNotFound(res.status, parsed.ok ? parsed.value : null, !parsed.ok)) {
      return NextResponse.json(fallbackStagingList(), { status: 200 });
    }
    const data = parsed.ok ? parsed.value : text;
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    );
  }
}

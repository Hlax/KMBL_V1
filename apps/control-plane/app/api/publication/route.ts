import { NextResponse } from "next/server";

import {
  fallbackPublicationList,
  isOrchestratorRouteNotFound,
  parseJsonSafe,
} from "@/lib/orchestrator-proxy";

export const dynamic = "force-dynamic";

function orchestratorBase(): string | null {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  return base || null;
}

/**
 * GET /api/publication → orchestrator GET /orchestrator/publication
 * POST /api/publication → orchestrator POST /orchestrator/publication
 */
export async function GET(request: Request) {
  const base = orchestratorBase();
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { searchParams } = new URL(request.url);
  const q = searchParams.toString();
  const url = `${base}/orchestrator/publication${q ? `?${q}` : ""}`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    const parsed = parseJsonSafe(text);
    if (isOrchestratorRouteNotFound(res.status, parsed.ok ? parsed.value : null, !parsed.ok)) {
      return NextResponse.json(fallbackPublicationList(), { status: 200 });
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

export async function POST(request: Request) {
  const base = orchestratorBase();
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const url = `${base}/orchestrator/publication`;
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

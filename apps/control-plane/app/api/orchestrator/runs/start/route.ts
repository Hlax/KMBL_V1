import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Proxy POST /orchestrator/runs/start → FastAPI (server-side; avoids browser CORS).
 */
export async function POST(request: Request) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const url = `${base}/orchestrator/runs/start`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
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

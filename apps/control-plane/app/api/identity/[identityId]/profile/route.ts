import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** Proxy GET/PUT /orchestrator/identity/{id}/profile */
export async function GET(
  _request: Request,
  context: { params: Promise<{ identityId: string }> },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { identityId } = await context.params;
  const url = `${base}/orchestrator/identity/${encodeURIComponent(identityId)}/profile`;
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

export async function PUT(
  request: Request,
  context: { params: Promise<{ identityId: string }> },
) {
  const base = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL?.trim().replace(/\/$/, "") ?? "";
  if (!base) {
    return NextResponse.json(
      { error: "NEXT_PUBLIC_ORCHESTRATOR_URL is not set" },
      { status: 500 },
    );
  }
  const { identityId } = await context.params;
  let body: unknown = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  const url = `${base}/orchestrator/identity/${encodeURIComponent(identityId)}/profile`;
  try {
    const res = await fetch(url, {
      method: "PUT",
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

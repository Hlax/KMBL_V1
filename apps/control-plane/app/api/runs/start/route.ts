import { NextRequest, NextResponse } from "next/server";

import { getOrchestratorServerOrigin } from "@/lib/orchestrator-server-origin";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const base = getOrchestratorServerOrigin();

    const res = await fetch(`${base}/orchestrator/runs/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }
    
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 500 }
    );
  }
}

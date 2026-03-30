/**
 * FastAPI / Starlette returns `{"detail":"Not Found"}` when no route matches.
 * Resource-level 404s use a different `detail` string (e.g. "graph_run not found").
 */
export function parseJsonSafe(text: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

export function isOrchestratorRouteNotFound(
  status: number,
  parsed: unknown,
  parseFailed: boolean,
): boolean {
  if (status !== 404) return false;
  if (parseFailed) return true;
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const d = (parsed as { detail?: unknown }).detail;
    return d === "Not Found";
  }
  return false;
}

/**
 * Fallback bodies when the upstream URL returns FastAPI’s route miss (`{"detail":"Not Found"}`).
 * Current orchestrator builds expose these GET routes; keep fallbacks for mis-pointed URLs or
 * older binaries — they are not used when the orchestrator returns a real JSON body.
 */

export function fallbackRunsList() {
  return {
    runs: [] as unknown[],
    count: 0,
    basis: "backend_unimplemented",
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/runs is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackOperatorSummary() {
  return {
    basis: "persisted_rows_only" as const,
    runtime: {
      runs_in_window: 0,
      runs_needing_attention: 0,
      failed_count: 0,
      paused_count: 0,
    },
    review_queue: {
      ready_for_review: 0,
      ready_to_publish: 0,
      published: 0,
      not_actionable: 0,
    },
    canon: {
      has_current_publication: false,
      latest_publication_snapshot_id: null as string | null,
      latest_published_at: null as string | null,
    },
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/operator-summary is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackProposals() {
  return {
    proposals: [] as unknown[],
    count: 0,
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/proposals is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackPublicationList() {
  return {
    publications: [] as unknown[],
    count: 0,
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/publication is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackPublicationCurrent() {
  return {
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/publication/current is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackStagingList() {
  return {
    snapshots: [] as unknown[],
    count: 0,
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/staging is not available on this backend (route not implemented or wrong server).",
  };
}

export function fallbackGraphRunDetail(graphRunId: string) {
  return {
    backend_unimplemented: true,
    message:
      "Orchestrator GET /orchestrator/runs/{id}/detail is not available on this backend (route not implemented or wrong server).",
    summary: {
      graph_run_id: graphRunId,
      thread_id: "—",
      trigger_type: "—",
      status: "unknown",
      started_at: new Date(0).toISOString(),
      run_state_hint: "unavailable",
    },
    role_invocations: [],
    associated_outputs: {},
    timeline: [],
  };
}

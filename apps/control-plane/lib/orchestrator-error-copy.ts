/**
 * Human-readable copy for FastAPI `detail` objects from the orchestrator.
 * Keeps UI calm and actionable without changing backend contracts.
 */

export type ParsedOrchestratorDetail = {
  errorKind?: string;
  reason?: string;
  message?: string;
  publicationSnapshotId?: string;
  stagingSnapshotId?: string;
};

export function parseOrchestratorDetail(text: string): ParsedOrchestratorDetail | null {
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    const d = j.detail;
    if (!d || typeof d !== "object") return null;
    const o = d as Record<string, unknown>;
    return {
      errorKind: typeof o.error_kind === "string" ? o.error_kind : undefined,
      reason: typeof o.reason === "string" ? o.reason : undefined,
      message: typeof o.message === "string" ? o.message : undefined,
      publicationSnapshotId:
        typeof o.publication_snapshot_id === "string" ? o.publication_snapshot_id : undefined,
      stagingSnapshotId:
        typeof o.staging_snapshot_id === "string" ? o.staging_snapshot_id : undefined,
    };
  } catch {
    return null;
  }
}

/** POST /publication failures (409 / 4xx with structured detail). */
export function humanizePublicationError(text: string): string {
  const p = parseOrchestratorDetail(text);
  if (!p?.errorKind) {
    try {
      const j = JSON.parse(text) as { detail?: unknown; error?: string; message?: string };
      if (typeof j.error === "string") return j.error;
      if (typeof j.message === "string") return j.message;
      if (typeof j.detail === "string") return j.detail;
    } catch {
      /* fall through */
    }
    return text.slice(0, 500);
  }

  if (p.errorKind === "publication_already_exists_for_staging") {
    return (
      "Canon already exists for this staging snapshot. Only one publication row is allowed per " +
      "staging id — open the existing canon snapshot below instead of publishing again."
    );
  }

  if (p.errorKind === "publication_ineligible") {
    const r = p.reason;
    if (r === "staging_not_approved") {
      return (
        "Publishing needs an approved staging row. Approve this snapshot first, then use Publish " +
        "once — staging must be in approved status."
      );
    }
    if (r === "staging_not_eligible") {
      return (
        "This staging snapshot is not in a state that can be published (for example rejected or " +
        "otherwise ineligible). Use a new staging snapshot if you need another canon line."
      );
    }
    if (r === "review_not_satisfied") {
      return (
        "Publication checks failed on persisted review readiness. Confirm staging status and " +
        "evaluation on this snapshot, then try again."
      );
    }
    if (r === "invalid_payload") {
      return (
        "The stored staging payload is missing required fields for publication. Fix upstream " +
        "staging data or open a support path — the server did not accept this payload shape."
      );
    }
    return p.message ?? "Publication cannot be created from this staging snapshot.";
  }

  return p.message ?? text.slice(0, 400);
}

/** Approve / reject / unapprove and similar staging mutations. */
export function humanizeStagingMutationError(text: string): string {
  const p = parseOrchestratorDetail(text);
  if (!p?.errorKind) {
    try {
      const j = JSON.parse(text) as { detail?: unknown; error?: string; message?: string };
      if (typeof j.error === "string") return j.error;
      if (typeof j.message === "string") return j.message;
      if (typeof j.detail === "string") return j.detail;
    } catch {
      /* fall through */
    }
    return text.slice(0, 500);
  }

  switch (p.errorKind) {
    case "approve_ineligible":
      if (p.reason === "staging_rejected") {
        return (
          "This staging snapshot is rejected — it cannot be approved. Start a new staging " +
          "snapshot from the graph if you need another review cycle."
        );
      }
      if (p.reason === "staging_not_review_ready") {
        return p.message ?? "Approve only works when staging is review_ready.";
      }
      return p.message ?? "Approval is not allowed for this staging snapshot.";
    case "reject_blocked_canon_exists":
      return (
        "Cannot reject while a publication snapshot already exists for this staging id. Canon is " +
        "immutable — open the linked publication to inspect it."
      );
    case "reject_ineligible":
      return p.message ?? "Reject is not allowed for this staging snapshot.";
    case "unapprove_blocked_canon_exists":
      return (
        "Cannot withdraw approval after canon exists. A publication row is already tied to this " +
        "staging id."
      );
    case "unapprove_ineligible":
      return p.message ?? "Unapprove only applies when staging is approved and no canon exists.";
    default:
      return p.message ?? text.slice(0, 400);
  }
}

/**
 * Pass J — UI-only helpers for persisted attention fields (no client-side state).
 */

export function graphRunAttentionIsHealthy(state: string | undefined): boolean {
  return state === "healthy";
}

export function graphRunAttentionBannerClass(state: string | undefined): string {
  return graphRunAttentionIsHealthy(state)
    ? "op-attention-banner op-attention-banner--ok"
    : "op-attention-banner op-attention-banner--warn";
}

export function graphRunAttentionBadgeClass(state: string | undefined): string {
  return graphRunAttentionIsHealthy(state)
    ? "op-badge op-badge--neutral"
    : "op-badge op-badge--attention";
}

const REVIEW_ACTION_LABEL: Record<string, string> = {
  ready_for_review: "Review pending",
  ready_to_publish: "Ready to publish",
  published: "Published",
  rejected: "Rejected",
  not_actionable: "No action",
};

export function reviewActionShortLabel(state: string | undefined): string {
  if (!state) return "—";
  return REVIEW_ACTION_LABEL[state] ?? state;
}

export function reviewActionBadgeClass(state: string | undefined): string {
  if (state === "ready_for_review") return "op-badge op-badge--attention";
  if (state === "ready_to_publish") return "op-badge op-badge--publish";
  if (state === "published") return "op-badge op-badge--canon";
  if (state === "rejected") return "op-badge op-badge--rejected";
  return "op-badge op-badge--neutral";
}

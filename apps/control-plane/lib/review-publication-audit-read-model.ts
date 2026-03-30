/**
 * Pass M — derived audit views from persisted staging/publication JSON only.
 * No inference beyond what rows provide; keep helpers pure (no React).
 */

import type { ProposalRow, PublicationDetail, StagingDetail } from "./api-types";

export type StagingOperatorActionKind = "approved" | "rejected" | "published";

export type StagingOperatorAction = {
  kind: StagingOperatorActionKind;
  label: string;
  at: string;
  actor: string | null;
  publicationSnapshotId?: string;
};

/** Staging detail: approval row + linked publication rows only (chronological). */
export function buildStagingOperatorActions(detail: StagingDetail): StagingOperatorAction[] {
  const actions: StagingOperatorAction[] = [];
  if (detail.approved_at) {
    actions.push({
      kind: "approved",
      label: "Approved (staging)",
      at: detail.approved_at,
      actor: detail.approved_by ?? null,
    });
  }
  if (detail.rejected_at) {
    actions.push({
      kind: "rejected",
      label: "Rejected (staging)",
      at: detail.rejected_at,
      actor: detail.rejected_by ?? null,
    });
  }
  for (const pub of detail.linked_publications ?? []) {
    actions.push({
      kind: "published",
      label: "Published to canon",
      at: pub.published_at,
      actor: pub.published_by ?? null,
      publicationSnapshotId: pub.publication_snapshot_id,
    });
  }
  actions.sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
  return actions;
}

export type ProposalPublicationHint = "published" | "awaiting" | "none";

export type ProposalAuditHints = {
  approvedAt?: string | null;
  approvedBy?: string | null;
  publicationHint: ProposalPublicationHint;
};

/** Review list cards — persisted fields only. */
export function buildProposalAuditHints(p: ProposalRow): ProposalAuditHints {
  const pubs = p.linked_publication_count ?? 0;
  const status = p.staging_status ?? p.review_readiness?.staging_status ?? "";
  let publicationHint: ProposalPublicationHint = "none";
  if (pubs > 0) {
    publicationHint = "published";
  } else if (status === "approved") {
    publicationHint = "awaiting";
  }
  return {
    approvedAt: p.approved_at,
    approvedBy: p.approved_by,
    publicationHint,
  };
}

export type PublicationAuditFacts = {
  publishedAt: string;
  publishedBy: string | null;
  sourceStagingSnapshotId: string | null;
  parentPublicationSnapshotId: string | null;
};

/** Single struct for publication detail audit panel (persisted columns + lineage). */
export function buildPublicationAuditFacts(detail: PublicationDetail): PublicationAuditFacts {
  const pl = detail.publication_lineage;
  const sourceStaging =
    pl?.source_staging_snapshot_id ?? detail.source_staging_snapshot_id ?? null;
  const parentPub =
    pl?.parent_publication_snapshot_id ?? detail.parent_publication_snapshot_id ?? null;
  return {
    publishedAt: detail.published_at ?? "",
    publishedBy: detail.published_by ?? null,
    sourceStagingSnapshotId: sourceStaging ?? null,
    parentPublicationSnapshotId: parentPub ?? null,
  };
}

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { humanizePublicationError, humanizeStagingMutationError } from "@/lib/orchestrator-error-copy";

type Props = {
  stagingSnapshotId: string;
  status: string;
  linkedPublicationCount: number;
  primaryLinkedPublicationId?: string | null;
};

function parsePublicationDuplicate409(
  text: string,
): { publicationSnapshotId: string; message: string } | null {
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    const raw = j.detail;
    if (!raw || typeof raw !== "object") return null;
    const d = raw as Record<string, unknown>;
    if (d.error_kind !== "publication_already_exists_for_staging") return null;
    const pid = d.publication_snapshot_id;
    if (typeof pid !== "string" || !pid.trim()) return null;
    const msg =
      typeof d.message === "string" && d.message.trim()
        ? d.message.trim()
        : "A publication snapshot already exists for this staging snapshot.";
    return { publicationSnapshotId: pid.trim(), message: msg };
  } catch {
    return null;
  }
}

export function StagingReviewActions({
  stagingSnapshotId,
  status,
  linkedPublicationCount,
  primaryLinkedPublicationId,
}: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [approveMsg, setApproveMsg] = useState<string | null>(null);
  const [approveErr, setApproveErr] = useState<string | null>(null);
  const [pubMsg, setPubMsg] = useState<string | null>(null);
  const [pubErr, setPubErr] = useState<string | null>(null);
  const [pubDuplicateId, setPubDuplicateId] = useState<string | null>(null);
  const [lastPublicationId, setLastPublicationId] = useState<string | null>(null);
  const [rejectMsg, setRejectMsg] = useState<string | null>(null);
  const [rejectErr, setRejectErr] = useState<string | null>(null);
  const [unapproveMsg, setUnapproveMsg] = useState<string | null>(null);
  const [unapproveErr, setUnapproveErr] = useState<string | null>(null);
  const [approvedBy, setApprovedBy] = useState("");
  const [rejectedBy, setRejectedBy] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [unapprovedBy, setUnapprovedBy] = useState("");
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [publishedBy, setPublishedBy] = useState("");

  const hasCanon = linkedPublicationCount > 0;
  const canMutateCanon = !hasCanon;

  const showApprove = status === "review_ready";
  const showPublishForm = status === "approved" && !hasCanon;
  const showCanonNote = status === "approved" && hasCanon;
  const showReject = canMutateCanon && (status === "review_ready" || status === "approved");
  const showUnapprove = status === "approved" && canMutateCanon;
  const showRejectedTerminal = status === "rejected";

  async function onApprove() {
    setApproveMsg(null);
    setApproveErr(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/staging/${encodeURIComponent(stagingSnapshotId)}/approve`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved_by: approvedBy.trim() || undefined }),
        },
      );
      const text = await res.text();
      if (res.status === 200) {
        setApproveMsg("Approved (persisted on this staging row).");
        router.refresh();
        return;
      }
      setApproveErr(humanizeStagingMutationError(text));
    } catch (e) {
      setApproveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    setRejectMsg(null);
    setRejectErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/staging/${encodeURIComponent(stagingSnapshotId)}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          rejected_by: rejectedBy.trim() || undefined,
          rejection_reason: rejectionReason.trim() || undefined,
        }),
      });
      const text = await res.text();
      if (res.status === 200) {
        setRejectMsg("Rejected — this staging snapshot is closed for approval and publish.");
        router.refresh();
        return;
      }
      setRejectErr(humanizeStagingMutationError(text));
    } catch (e) {
      setRejectErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onUnapprove() {
    setUnapproveMsg(null);
    setUnapproveErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/staging/${encodeURIComponent(stagingSnapshotId)}/unapprove`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unapproved_by: unapprovedBy.trim() || undefined }),
      });
      const text = await res.text();
      if (res.status === 200) {
        setUnapproveMsg("Approval withdrawn — staging is review_ready again.");
        router.refresh();
        return;
      }
      setUnapproveErr(humanizeStagingMutationError(text));
    } catch (e) {
      setUnapproveErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(e: React.FormEvent) {
    e.preventDefault();
    setPubMsg(null);
    setPubErr(null);
    setPubDuplicateId(null);
    setLastPublicationId(null);
    setBusy(true);
    try {
      const res = await fetch("/api/publication", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          staging_snapshot_id: stagingSnapshotId,
          visibility,
          published_by: publishedBy.trim() || undefined,
        }),
      });
      const text = await res.text();
      let pubId: string | null = null;
      try {
        const j = JSON.parse(text) as { publication_snapshot_id?: string };
        if (typeof j.publication_snapshot_id === "string") pubId = j.publication_snapshot_id;
      } catch {
        /* ignore */
      }
      if (res.status === 200) {
        if (pubId) setLastPublicationId(pubId);
        setPubMsg("Canon created — publication snapshot is immutable.");
        router.refresh();
        return;
      }
      if (res.status === 409) {
        const dup = parsePublicationDuplicate409(text);
        if (dup) {
          setPubDuplicateId(dup.publicationSnapshotId);
          return;
        }
        setPubErr(humanizePublicationError(text));
        return;
      }
      setPubErr(humanizePublicationError(text));
    } catch (e) {
      setPubErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (showRejectedTerminal) {
    return (
      <div className="debug-panel op-panel--terminal-rejected">
        <h3 className="op-actions__h">Rejected — terminal</h3>
        <p className="muted small" style={{ marginBottom: 0 }}>
          This staging snapshot cannot be approved or published. Publish is not available. To try
          again, create a <strong>new staging snapshot</strong> from the graph.
        </p>
      </div>
    );
  }

  if (!showApprove && !showPublishForm && !showCanonNote && !showReject && !showUnapprove) {
    return (
      <div className="debug-panel">
        <p className="muted small" style={{ margin: 0 }}>
          No operator actions for status <strong>{status}</strong>
          {hasCanon ? " (canon already linked)" : ""}. Use approve when staging is{" "}
          <code>review_ready</code>, publish when <code>approved</code> and no canon row exists.
        </p>
      </div>
    );
  }

  if (showCanonNote && !showPublishForm && !showUnapprove && !showReject && !showApprove) {
    return (
      <div className="debug-panel debug-panel--ok">
        <h3 className="op-actions__h">Canon linked</h3>
        <p className="muted small">
          This staging id already has an immutable publication snapshot. Publish, withdraw approval,
          and reject are disabled — duplicate publish is blocked server-side.
        </p>
        {primaryLinkedPublicationId ? (
          <p style={{ marginTop: "0.65rem", marginBottom: 0 }}>
            <Link
              className="op-btn op-btn--primary"
              href={`/publication/${encodeURIComponent(primaryLinkedPublicationId)}`}
            >
              Open canon (publication) →
            </Link>
          </p>
        ) : (
          <p className="muted small" style={{ marginTop: "0.5rem", marginBottom: 0 }}>
            See <strong>Canon — linked publication(s)</strong> on this page for links.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="op-actions op-actions--staging-flow">
      {showPublishForm ? (
        <div className="debug-panel op-panel--publish-primary">
          <h3 className="op-actions__h">Publish to canon</h3>
          <p className="op-flow-lede">
            <span className="op-badge op-badge--publish">Ready</span> Staging is approved and no
            publication exists for this id — you may publish <strong>once</strong> to create
            immutable canon.
          </p>
          <p className="muted small">
            After publish, this staging id cannot publish again. For another canon line, use a new
            staging snapshot.
          </p>
          <form onSubmit={onPublish}>
            <label className="op-field">
              <span>Visibility</span>
              <select
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as "private" | "public")}
              >
                <option value="private">private</option>
                <option value="public">public</option>
              </select>
            </label>
            <label className="op-field">
              <span>Published by (optional)</span>
              <input
                type="text"
                value={publishedBy}
                onChange={(e) => setPublishedBy(e.target.value)}
                placeholder="operator id"
                autoComplete="off"
              />
            </label>
            <button type="submit" className="op-btn op-btn--primary" disabled={busy}>
              {busy ? "Working…" : "Publish to canon"}
            </button>
          </form>
          {pubMsg ? <p className="op-ok">{pubMsg}</p> : null}
          {pubDuplicateId ? (
            <div className="op-banner op-banner--canon" role="status" style={{ marginTop: "0.75rem" }}>
              <strong>Canon already exists.</strong> Another publish is not allowed for this staging
              id.{" "}
              <Link href={`/publication/${encodeURIComponent(pubDuplicateId)}`}>
                Open the existing publication →
              </Link>
              <span className="mono small" style={{ display: "block", marginTop: "0.35rem" }}>
                {pubDuplicateId}
              </span>
            </div>
          ) : null}
          {pubErr ? (
            <p className="op-err" role="alert">
              {pubErr}
            </p>
          ) : null}
          {lastPublicationId ? (
            <p className="op-ok">
              <Link href={`/publication/${encodeURIComponent(lastPublicationId)}`}>
                Open new publication →
              </Link>
            </p>
          ) : null}
        </div>
      ) : null}

      {showApprove ? (
        <div className="debug-panel">
          <h3 className="op-actions__h">Approve (staging)</h3>
          <p className="muted small">
            Required before publish. Records operator approval on this row only — does not create
            canon.
          </p>
          <label className="op-field">
            <span>Approved by (optional)</span>
            <input
              type="text"
              value={approvedBy}
              onChange={(e) => setApprovedBy(e.target.value)}
              placeholder="operator id"
              autoComplete="off"
            />
          </label>
          <button type="button" className="op-btn op-btn--primary" disabled={busy} onClick={onApprove}>
            {busy ? "Working…" : "Approve staging snapshot"}
          </button>
          {approveMsg ? <p className="op-ok">{approveMsg}</p> : null}
          {approveErr ? (
            <p className="op-err" role="alert">
              {approveErr}
            </p>
          ) : null}
        </div>
      ) : null}

      {showUnapprove ? (
        <div className="debug-panel">
          <h3 className="op-actions__h">Withdraw approval</h3>
          <p className="muted small">
            Returns staging to <code>review_ready</code> so you can continue review. Only when no
            canon snapshot exists for this staging id.
          </p>
          <label className="op-field">
            <span>Recorded by (optional)</span>
            <input
              type="text"
              value={unapprovedBy}
              onChange={(e) => setUnapprovedBy(e.target.value)}
              placeholder="operator id"
              autoComplete="off"
            />
          </label>
          <button type="button" className="op-btn" disabled={busy} onClick={onUnapprove}>
            {busy ? "Working…" : "Withdraw approval (back to review)"}
          </button>
          {unapproveMsg ? <p className="op-ok">{unapproveMsg}</p> : null}
          {unapproveErr ? (
            <p className="op-err" role="alert">
              {unapproveErr}
            </p>
          ) : null}
        </div>
      ) : null}

      {showReject ? (
        <div className="debug-panel op-panel--reject">
          <h3 className="op-actions__h">Reject staging</h3>
          <p className="muted small">
            <strong>Terminal.</strong> Sets <code>rejected</code> — no later approve or publish on
            this snapshot. Blocked if canon already exists.
            {status === "approved" ? (
              <> From approved, approval is cleared and the snapshot is marked rejected.</>
            ) : null}
          </p>
          <label className="op-field">
            <span>Rejected by (optional)</span>
            <input
              type="text"
              value={rejectedBy}
              onChange={(e) => setRejectedBy(e.target.value)}
              placeholder="operator id"
              autoComplete="off"
            />
          </label>
          <label className="op-field">
            <span>Reason (optional)</span>
            <textarea
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="Short note for audit"
              rows={3}
              className="op-textarea"
            />
          </label>
          <button type="button" className="op-btn op-btn--danger" disabled={busy} onClick={onReject}>
            {busy ? "Working…" : "Reject staging snapshot"}
          </button>
          {rejectMsg ? <p className="op-ok">{rejectMsg}</p> : null}
          {rejectErr ? (
            <p className="op-err" role="alert">
              {rejectErr}
            </p>
          ) : null}
        </div>
      ) : null}

      {showCanonNote ? (
        <div className="debug-panel debug-panel--ok">
          <h3 className="op-actions__h">Canon linked</h3>
          <p className="muted small">
            A publication snapshot already exists for this staging id. Publish is disabled; withdraw
            and reject are disabled while canon exists.
          </p>
          {primaryLinkedPublicationId ? (
            <p style={{ marginTop: "0.65rem", marginBottom: 0 }}>
              <Link
                className="op-btn op-btn--primary"
                href={`/publication/${encodeURIComponent(primaryLinkedPublicationId)}`}
              >
                Open canon (publication) →
              </Link>
            </p>
          ) : (
            <p className="muted small" style={{ marginTop: "0.5rem", marginBottom: 0 }}>
              See <strong>Canon — linked publication(s)</strong> on this page.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

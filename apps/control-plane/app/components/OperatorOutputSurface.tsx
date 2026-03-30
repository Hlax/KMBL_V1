import Link from "next/link";
import type { StagingEvaluationDetail } from "@/lib/api-types";
import {
  deriveProducedSummary,
  evaluationIssueTotal,
  extractEvaluationIssueStrings,
  normalizeArtifactRefs,
  resolvePreviewUrl,
  safeHttpUrl,
  type ArtifactSurfaceItem,
} from "@/lib/operator-output-surface";

type Props = {
  payload: Record<string, unknown> | undefined;
  /** Staging row `preview_url` — preferred when set */
  rowPreviewUrl?: string | null;
  evaluation?: StagingEvaluationDetail;
  graphRunId?: string | null;
  variant: "staging" | "publication";
};

function isSafePreviewEmbed(url: string): boolean {
  return safeHttpUrl(url) !== null;
}

function evaluationFromPayload(payload: Record<string, unknown> | undefined): {
  status: string | null;
  summary: string;
} {
  if (!payload) return { status: null, summary: "" };
  const ev = payload.evaluation;
  if (!ev || typeof ev !== "object") return { status: null, summary: "" };
  const o = ev as Record<string, unknown>;
  const st = o.status;
  const sum = o.summary;
  return {
    status: typeof st === "string" ? st : null,
    summary: typeof sum === "string" ? sum : "",
  };
}

function ArtifactCard({ item }: { item: ArtifactSurfaceItem }) {
  const body = (
    <>
      {item.thumbUrl ? (
        <div className="op-artifact-card__thumb-wrap">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            className="op-artifact-card__thumb"
            src={item.thumbUrl}
            alt=""
            loading="lazy"
            decoding="async"
          />
        </div>
      ) : null}
      <div className="op-artifact-card__body">
        <p className="op-artifact-card__label">{item.label}</p>
        {item.href ? (
          <p className="op-artifact-card__link op-break-long">
            {item.href.length > 56 ? `${item.href.slice(0, 56)}…` : item.href}
          </p>
        ) : item.sublabel ? (
          <p className="op-artifact-card__blob mono small">{item.sublabel}</p>
        ) : null}
      </div>
    </>
  );

  if (item.href) {
    return (
      <a
        className="op-artifact-card op-artifact-card--interactive"
        href={item.href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {body}
      </a>
    );
  }

  return <div className="op-artifact-card">{body}</div>;
}

export function OperatorOutputSurface({
  payload,
  rowPreviewUrl,
  evaluation,
  graphRunId,
  variant,
}: Props) {
  const preview = resolvePreviewUrl(rowPreviewUrl, payload);
  const produced = deriveProducedSummary(payload);
  const artifacts = normalizeArtifactRefs(payload);
  const issueTotal = evaluationIssueTotal(payload);
  const issueCountDisplay =
    typeof evaluation?.issue_count === "number" ? evaluation.issue_count : issueTotal;
  const issuePreview = extractEvaluationIssueStrings(payload, 4);
  const evPayload = evaluationFromPayload(payload);
  const evStatus =
    evaluation?.present && evaluation.status != null && String(evaluation.status).trim() !== ""
      ? evaluation.status
      : evPayload.status;
  const evSummary =
    evaluation?.present && evaluation.summary?.trim()
      ? evaluation.summary.trim()
      : evPayload.summary.trim();
  const showEvalBlock =
    Boolean(evStatus) ||
    issueCountDisplay > 0 ||
    evSummary.length > 0 ||
    (evaluation?.present ?? false);

  const heading =
    variant === "staging"
      ? "Generator output & evaluator context"
      : "Canon snapshot — produced output";

  return (
    <section className="op-output-surface" aria-labelledby="op-output-surface-h">
      <h2 id="op-output-surface-h" className="op-section-title">
        {heading}
      </h2>
      <p className="muted small op-output-surface__lede">
        {variant === "staging"
          ? "What the generator attached to this snapshot and what the evaluator recorded — from persisted payload only."
          : "Immutable copy of staging payload at publish time — preview, artifacts, and evaluation as stored."}
      </p>

      {produced ? (
        <div className="op-output-kicker">
          <span className="op-output-kicker__label">Produced</span>
          <p className="op-output-kicker__value">{produced.line}</p>
        </div>
      ) : null}

      <div className="op-output-actions">
        <div className="op-output-actions__primary">
          <span className="pub-hero__label">Preview</span>
          {preview ? (
            <>
              <a
                className="op-btn op-btn--primary op-output-open-btn"
                href={preview}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open preview in new tab
              </a>
              <p className="mono small muted op-output-url-line" title={preview}>
                {preview.length > 72 ? `${preview.slice(0, 72)}…` : preview}
              </p>
            </>
          ) : (
            <p className="muted small" style={{ margin: 0 }}>
              No preview URL on this snapshot.
            </p>
          )}
        </div>
        {payload &&
        typeof payload.preview === "object" &&
        payload.preview !== null &&
        typeof (payload.preview as Record<string, unknown>).sandbox_ref === "string" &&
        String((payload.preview as Record<string, unknown>).sandbox_ref).trim() ? (
          <div className="op-output-actions__secondary">
            <span className="pub-hero__label">Sandbox</span>
            <p className="mono small" style={{ margin: 0 }}>
              {String((payload.preview as Record<string, unknown>).sandbox_ref)}
            </p>
          </div>
        ) : null}
      </div>

      {artifacts.length > 0 ? (
        <div className="op-output-block">
          <h3 className="op-output-block__title">Linked outputs &amp; artifact refs</h3>
          <p className="muted small" style={{ marginTop: 0 }}>
            {artifacts.length} item{artifacts.length === 1 ? "" : "s"} from generator{" "}
            <code>artifact_refs</code> — open URLs directly; structured entries show fields.
          </p>
          <div className="op-artifact-grid">
            {artifacts.map((a) => (
              <ArtifactCard key={a.key} item={a} />
            ))}
          </div>
        </div>
      ) : (
        <div className="op-output-block op-output-block--muted">
          <h3 className="op-output-block__title">Artifact refs</h3>
          <p className="muted small" style={{ margin: 0 }}>
            No <code>artifact_refs</code> on this payload — generator did not persist linked assets here.
          </p>
        </div>
      )}

      {showEvalBlock ? (
        <div className="op-output-block op-output-eval">
          <h3 className="op-output-block__title">Evaluator</h3>
          <div className="op-output-eval__row">
            {evStatus ? (
              <span className="op-badge op-badge--neutral">{evStatus}</span>
            ) : (
              <span className="muted small">Status not in payload</span>
            )}
            {issueCountDisplay > 0 ? (
              <span className="muted small">
                {issueCountDisplay} issue{issueCountDisplay === 1 ? "" : "s"}
              </span>
            ) : null}
            {graphRunId ? (
              <span className="muted small">
                <Link href={`/runs/${encodeURIComponent(graphRunId)}`}>Run trace</Link>
              </span>
            ) : null}
          </div>
          {evSummary ? (
            <p className="op-output-eval__summary">{evSummary.length > 360 ? `${evSummary.slice(0, 360)}…` : evSummary}</p>
          ) : null}
          {issuePreview.length > 0 ? (
            <ul className="op-output-issues">
              {issuePreview.map((t, i) => (
                <li key={i}>{t.length > 200 ? `${t.slice(0, 200)}…` : t}</li>
              ))}
            </ul>
          ) : issueCountDisplay > 0 ? (
            <p className="muted small" style={{ marginBottom: 0 }}>
              {issueCountDisplay} issue(s) recorded — open <strong>Evaluation metrics (persisted)</strong>{" "}
              below for full detail.
            </p>
          ) : null}
        </div>
      ) : null}

      {preview && isSafePreviewEmbed(preview) && variant === "staging" ? (
        <p className="muted small" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
          Embedded iframe (if allowed) appears in <strong>Embedded preview</strong> below.
        </p>
      ) : null}
    </section>
  );
}

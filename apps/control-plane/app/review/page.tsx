import Link from "next/link";
import type { ProposalsResponse, ProposalRow } from "@/lib/api-types";
import { IdentityContextLinks } from "@/app/components/IdentityNavExtras";
import { identityOverviewPath } from "@/lib/identity-nav";
import {
  reviewActionBadgeClass,
  reviewActionShortLabel,
} from "@/lib/operator-attention";
import { buildProposalAuditHints } from "@/lib/review-publication-audit-read-model";
import { serverOriginFromHeaders } from "@/lib/server-origin";
import { StagingFactsCard } from "@/app/components/StagingFactsCard";

export const dynamic = "force-dynamic";

function pick(
  sp: Record<string, string | string[] | undefined>,
  k: string,
): string | undefined {
  const v = sp[k];
  if (Array.isArray(v)) return v[0];
  return v;
}

function formatWhen(iso: string | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function truncate(s: string, n: number) {
  const t = s.trim();
  return t.length > n ? `${t.slice(0, n)}…` : t;
}

function ProposalCard({ p }: { p: ProposalRow }) {
  const id = p.staging_snapshot_id;
  const href = `/review/staging/${encodeURIComponent(id)}`;
  const title = p.title ?? p.summary ?? id;
  const rr = p.review_readiness;
  const statusLine = rr?.staging_status ?? p.staging_status ?? "—";
  const action = p.review_action_state;
  const pubs = p.linked_publication_count ?? 0;
  const auditHints = buildProposalAuditHints(p);
  const hasCanon = pubs > 0;

  let canonLabel: string;
  if (hasCanon) {
    canonLabel = pubs === 1 ? "Canon linked" : `Canon linked (${pubs})`;
  } else if (statusLine === "rejected") {
    canonLabel = "no canon (rejected)";
  } else if (statusLine === "approved") {
    canonLabel = "awaiting publish";
  } else {
    canonLabel = "no canon yet";
  }

  return (
    <li className="op-card op-card--compact">
      <div className="review-proposal-card__top">
        <h2 className="op-card__title">
          <Link href={href}>{title}</Link>
        </h2>
        <span className="review-proposal-card__when">{formatWhen(p.created_at)}</span>
      </div>

      <div className="review-proposal-card__badges">
        <span className={reviewActionBadgeClass(action)} title={p.review_action_reason ?? ""}>
          {reviewActionShortLabel(action)}
        </span>
        {p.content_kind === "gallery_strip" || p.has_gallery_strip ? (
          <span className="op-badge op-badge--gallery" title="Staging payload includes ui_gallery_strip_v1">
            gallery strip
          </span>
        ) : null}
        <span className="op-badge op-badge--staging" title="Persisted staging_snapshot.status">
          {statusLine}
        </span>
        {hasCanon ? (
          <span className="op-badge op-badge--canon" title="Immutable publication snapshot(s) exist for this staging id">
            {canonLabel}
          </span>
        ) : (
          <span className="muted small">{canonLabel}</span>
        )}
      </div>

      {p.evaluation_summary ? (
        <p className="pub-eval-blurb" style={{ marginTop: 0 }}>
          {truncate(p.evaluation_summary, 320)}
        </p>
      ) : (
        <p className="muted small" style={{ margin: "0 0 0.5rem" }}>
          No evaluation summary on snapshot.
        </p>
      )}

      {p.review_action_reason ? (
        <p className="muted small" style={{ margin: "0 0 0.45rem" }}>
          {p.review_action_reason}
        </p>
      ) : null}

      {(auditHints.approvedBy || auditHints.approvedAt) && !hasCanon ? (
        <p className="muted small" style={{ margin: "0 0 0.45rem" }}>
          {auditHints.approvedBy ? <>Approved by {auditHints.approvedBy}</> : null}
          {auditHints.approvedBy && auditHints.approvedAt ? " · " : null}
          {auditHints.approvedAt ? <>{formatWhen(auditHints.approvedAt)}</> : null}
        </p>
      ) : null}

      <p className="review-proposal-card__identity">
        <span className="mono">{id}</span>
        {p.identity_id ? (
          <>
            {" "}
            ·{" "}
            <Link className="mono" href={identityOverviewPath(p.identity_id)} title="Identity overview">
              {p.identity_hint ?? p.identity_id}
            </Link>
            <span className="muted small"> · </span>
            <IdentityContextLinks identityId={p.identity_id} />
          </>
        ) : p.identity_hint ? (
          <>
            {" "}
            · <span className="mono">{p.identity_hint}</span>
          </>
        ) : null}
      </p>

      <StagingFactsCard
        variant="compact"
        facts={{
          staging_snapshot_id: id,
          status: statusLine,
          has_static_frontend: p.has_static_frontend,
          has_previewable_html: p.has_previewable_html,
          has_gallery_strip: p.has_gallery_strip,
          gallery_image_artifact_count: p.gallery_image_artifact_count,
        }}
      />

      <p className="op-card__foot" style={{ marginTop: "0.25rem" }}>
        <Link href={href}>Open staging review →</Link>
      </p>
    </li>
  );
}

function filterActiveSummary(args: {
  review_action_state: string;
  staging_status: string;
  has_publication: string;
  sort: string;
  identity_id: string;
  limitRaw: string;
}): { active: boolean; parts: string[] } {
  const parts: string[] = [];
  if (args.review_action_state)
    parts.push(`action=${args.review_action_state}`);
  if (args.staging_status) parts.push(`staging=${args.staging_status}`);
  if (args.has_publication) parts.push(`has_publication=${args.has_publication}`);
  if (args.sort) parts.push(`sort=${args.sort}`);
  if (args.identity_id.trim()) parts.push(`identity_id=${args.identity_id.trim()}`);
  if (args.limitRaw && args.limitRaw !== "20") parts.push(`limit=${args.limitRaw}`);
  return { active: parts.length > 0, parts };
}

export default async function ReviewPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const review_action_state = pick(searchParams, "review_action_state") ?? "";
  const staging_status = pick(searchParams, "staging_status") ?? "";
  const has_publication = pick(searchParams, "has_publication") ?? "";
  const sort = pick(searchParams, "sort") ?? "";
  const identity_id = pick(searchParams, "identity_id") ?? "";
  const limitRaw = pick(searchParams, "limit") ?? "20";

  const origin = serverOriginFromHeaders();
  const params = new URLSearchParams();
  if (review_action_state) params.set("review_action_state", review_action_state);
  if (staging_status) params.set("staging_status", staging_status);
  if (has_publication) params.set("has_publication", has_publication);
  if (sort) params.set("sort", sort);
  if (identity_id) params.set("identity_id", identity_id);
  if (limitRaw && limitRaw !== "20") params.set("limit", limitRaw);

  const url = `${origin}/api/proposals${params.toString() ? `?${params}` : ""}`;

  let body: ProposalsResponse | null = null;
  let httpError: string | null = null;
  try {
    const res = await fetch(url, { cache: "no-store" });
    const text = await res.text();
    try {
      body = JSON.parse(text) as ProposalsResponse;
    } catch {
      httpError = res.ok ? "Invalid JSON from /api/proposals" : text.slice(0, 200);
    }
    if (!res.ok && !httpError) {
      httpError =
        typeof body?.error === "string"
          ? body.error
          : `HTTP ${res.status} ${text.slice(0, 200)}`;
    }
  } catch (e) {
    httpError = e instanceof Error ? e.message : String(e);
  }

  const proposals = Array.isArray(body?.proposals) ? body.proposals : [];
  const count = body?.count ?? proposals.length;
  const backendUnimplemented = body?.backend_unimplemented === true;

  const { active: filtersActive, parts: filterParts } = filterActiveSummary({
    review_action_state,
    staging_status,
    has_publication,
    sort,
    identity_id,
    limitRaw,
  });

  return (
    <>
      <h1 className="pub-page-title">Review queue</h1>
      <p className="muted" style={{ marginTop: "-0.25rem", marginBottom: "1rem" }}>
        Persisted staging snapshots — what needs operator attention next, and what is already
        tied to canon. Follow the header <strong>Flow</strong> strip: Run → Review → Preview →
        Publish; each card below shows the same staging facts as run detail for quick image /
        static checks.
      </p>

      {backendUnimplemented ? (
        <p className="op-banner op-banner--warn" role="status">
          <strong>Review read API not available on this orchestrator build.</strong>{" "}
          {body?.message ??
            "Showing an empty queue until GET /orchestrator/proposals is available."}
        </p>
      ) : null}

      <p className="op-banner op-banner--staging">
        <strong>Queue</strong> — ordered by priority (review → publish → published → other),
        newest first within each tier. Filters only change which persisted rows are shown — not
        live graph state.{" "}
        <Link href="/publication">Publication</Link> is immutable canon after publish.
      </p>

      <div className="op-banner op-banner--neutral review-filter-context">
        <strong>Active filters.</strong>{" "}
        {filtersActive ? (
          <span className="mono small">{filterParts.join(" · ")}</span>
        ) : (
          <span className="muted">None — default queue (all proposals in scope).</span>
        )}
      </div>

      <form method="get" action="/review" className="debug-panel op-runs-filters">
        <h2 className="op-section-title">Narrow the queue</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Optional <code>identity_id</code> scopes to one identity (same as runs / publication).
          Invalid UUIDs return HTTP 400.
        </p>
        <div className="op-runs-filters__row">
          <label className="op-field">
            <span>Action</span>
            <select name="review_action_state" defaultValue={review_action_state}>
              <option value="">Any</option>
              <option value="ready_for_review">ready_for_review</option>
              <option value="ready_to_publish">ready_to_publish</option>
              <option value="published">published</option>
              <option value="not_actionable">not_actionable</option>
            </select>
          </label>
          <label className="op-field">
            <span>Staging status</span>
            <select name="staging_status" defaultValue={staging_status}>
              <option value="">Any</option>
              <option value="review_ready">review_ready</option>
              <option value="approved">approved</option>
            </select>
          </label>
          <label className="op-field">
            <span>Has publication</span>
            <select name="has_publication" defaultValue={has_publication}>
              <option value="">Any</option>
              <option value="true">yes</option>
              <option value="false">no</option>
            </select>
          </label>
          <label className="op-field">
            <span>Sort</span>
            <select name="sort" defaultValue={sort}>
              <option value="">default (tiers)</option>
              <option value="newest">newest</option>
              <option value="oldest">oldest</option>
            </select>
          </label>
          <label className="op-field">
            <span>identity_id</span>
            <input
              name="identity_id"
              type="text"
              defaultValue={identity_id}
              placeholder="UUID — optional"
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label className="op-field">
            <span>limit</span>
            <input name="limit" type="number" min={1} max={200} defaultValue={limitRaw || "20"} />
          </label>
          <div className="op-field op-field--filter-submit">
            <span>&nbsp;</span>
            <button type="submit" className="op-btn op-btn--primary">
              Apply
            </button>
          </div>
        </div>
        <p className="muted small">
          <Link href="/review">Clear filters</Link>
          {" · "}
          <Link href="/runs">Runs</Link>
          {" · "}
          <Link href="/publication">Publication</Link>
        </p>
      </form>

      {httpError ? (
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load proposals</p>
          <p className="pub-empty__body mono small">{httpError}</p>
        </div>
      ) : null}

      {!httpError && proposals.length === 0 ? (
        <div className="pub-empty">
          <p className="pub-empty__title">
            {filtersActive ? "No proposals match these filters" : "Nothing in the queue"}
          </p>
          <p className="pub-empty__body">
            {filtersActive
              ? "Try clearing filters or widening action / staging / publication criteria."
              : "When staging snapshots are ready for review or publish, they will appear here. Start a run from Runs or wait for the graph to produce staging rows."}
          </p>
        </div>
      ) : null}

      {!httpError && proposals.length > 0 ? (
        <>
          <p className="muted small" style={{ marginBottom: "0.75rem" }}>
            Showing <strong>{count}</strong> proposal{count === 1 ? "" : "s"}
            {filtersActive ? " (filtered)" : ""}.
          </p>
          <ul className="op-list op-list--compact">
            {proposals.map((p, idx) => (
              <ProposalCard key={p.staging_snapshot_id || `proposal-${idx}`} p={p} />
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

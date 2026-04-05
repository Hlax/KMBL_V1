import Link from "next/link";
import { notFound } from "next/navigation";
import { StagingFactsCard } from "@/app/components/StagingFactsCard";
import { IdentityContextLinks, IdentityNavExtras } from "@/app/components/IdentityNavExtras";
import type { GraphRunDetail, GraphRunSummaryBlock, StagingDetail } from "@/lib/api-types";
import { identityOverviewPath } from "@/lib/identity-nav";
import { scenarioBadgeLabel } from "@/lib/gallery-strip-visibility";
import { buildGeneratorRoutingView } from "@/lib/operator-routing-hints";
import { graphRunAttentionBannerClass } from "@/lib/operator-attention";
import { serverOriginFromHeaders } from "@/lib/server-origin";
import { MaterializeReviewSnapshotButton } from "@/app/components/MaterializeReviewSnapshotButton";
import { RunResumeActions } from "./RunResumeActions";

export const dynamic = "force-dynamic";

function formatWhen(iso: string | null | undefined) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function shortId(id: string) {
  const s = id.replace(/-/g, "");
  return s.length >= 8 ? `${s.slice(0, 8)}…` : id;
}

function yn(v: unknown): string {
  if (v === true) return "yes";
  if (v === false) return "no";
  return "—";
}

function countKey(
  counts: Record<string, number> | undefined,
  key: string,
): number {
  const n = counts?.[key];
  return typeof n === "number" && Number.isFinite(n) ? n : 0;
}

/**
 * Manifest-first / workspace ingest / evaluator preview grounding (orchestrator summary.run_observability).
 */
function RuntimeObservabilityCard({
  summary,
  lastMeaningful,
}: {
  summary: GraphRunSummaryBlock;
  lastMeaningful: GraphRunDetail["last_meaningful_event"];
}) {
  const obs = summary.run_observability;
  const counts = obs?.manifest_first_event_counts;
  const pr = obs?.last_evaluator_preview_resolution ?? null;
  const metType = lastMeaningful?.event_type ?? null;
  const signalBanner =
    metType === "manifest_first_violation" ||
    metType === "evaluator_grounding_unavailable";

  const src =
    typeof pr?.preview_url_source === "string" && pr.preview_url_source.trim()
      ? pr.preview_url_source
      : "—";

  return (
    <div className="op-card op-card--compact" style={{ marginBottom: "1rem" }}>
      <h2 className="op-section-title" style={{ marginBottom: "0.35rem" }}>
        Runtime observability
      </h2>
      <p className="muted small" style={{ marginTop: 0 }}>
        Manifest-first policy, workspace ingest, and evaluator preview grounding (from persisted{" "}
        <code className="mono small">graph_run_event</code> counts + last evaluator input snapshot).
      </p>

      {signalBanner ? (
        <div className="op-banner op-banner--warn" style={{ marginBottom: "0.65rem", marginTop: "0.5rem" }}>
          <strong>Operator signal</strong> — last meaningful event:{" "}
          <code className="mono small">{metType}</code>
          {metType === "manifest_first_violation" ? (
            <span className="small">
              {" "}
              — manifest-first policy conflict; see runtime path counts below.
            </span>
          ) : (
            <span className="small">
              {" "}
              — set <code className="mono small">KMBL_ORCHESTRATOR_PUBLIC_BASE_URL</code> or an absolute{" "}
              <code className="mono small">preview_url</code> on the candidate.
            </span>
          )}
        </div>
      ) : null}

      {!obs ? (
        <p className="muted small" style={{ marginBottom: 0 }}>
          No <code className="mono small">run_observability</code> on this summary (older orchestrator or empty read model).
        </p>
      ) : (
        <>
          <h3 className="op-subtitle" style={{ marginBottom: "0.35rem", marginTop: "0.35rem" }}>
            Runtime path
          </h3>
          <p className="muted small" style={{ marginBottom: "0.5rem" }}>
            <strong>Manifest-first activity</strong> —{" "}
            {countKey(counts, "manifest_first_violation") > 0 ||
            countKey(counts, "workspace_ingest_not_attempted") > 0 ||
            countKey(counts, "workspace_ingest_skipped_inline_html") > 0 ||
            countKey(counts, "workspace_ingest_started") > 0 ||
            countKey(counts, "workspace_ingest_completed") > 0
              ? "yes (see counts below)"
              : "no matching events in this run"}
          </p>
          <dl className="pub-lineage-dl" style={{ marginBottom: "0.65rem" }}>
            <dt>Workspace ingest not attempted</dt>
            <dd>{countKey(counts, "workspace_ingest_not_attempted")}</dd>
            <dt>Workspace ingest started</dt>
            <dd>{countKey(counts, "workspace_ingest_started")}</dd>
            <dt>Workspace ingest completed</dt>
            <dd>{countKey(counts, "workspace_ingest_completed")}</dd>
            <dt>Workspace ingest skipped (inline HTML)</dt>
            <dd>{countKey(counts, "workspace_ingest_skipped_inline_html")}</dd>
            <dt>Manifest-first violation</dt>
            <dd>{countKey(counts, "manifest_first_violation")}</dd>
          </dl>

          <h3 className="op-subtitle" style={{ marginBottom: "0.35rem" }}>
            Evaluator grounding
          </h3>
          {pr && typeof pr === "object" ? (
            <dl className="pub-lineage-dl" style={{ marginBottom: 0 }}>
              <dt>Preview URL source</dt>
              <dd className="mono small">{src}</dd>
              <dt>Preview URL is absolute</dt>
              <dd>{yn(pr.preview_url_is_absolute)}</dd>
              <dt>Orchestrator public base URL configured</dt>
              <dd>{yn(pr.orchestrator_public_base_url_configured)}</dd>
            </dl>
          ) : (
            <p className="muted small" style={{ marginBottom: 0 }}>
              No persisted evaluator <code className="mono small">preview_resolution</code> on this run (evaluator may not have run or input not stored).
            </p>
          )}
        </>
      )}
    </div>
  );
}

export default async function GraphRunDetailPage({
  params,
}: {
  params: { graphRunId: string };
}) {
  const { graphRunId } = params;
  const origin = serverOriginFromHeaders();
  const url = `${origin}/api/runs/${encodeURIComponent(graphRunId)}`;

  let res: Response;
  try {
    res = await fetch(url, { cache: "no-store" });
  } catch (e) {
    return (
      <>
        <p className="muted small cp-crumb-line">
          <Link href="/runs">← Runs</Link>
          {" · "}
          <Link href="/review">Review</Link>
        </p>
        <h1 className="pub-page-title">Graph run</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not reach the server</p>
          <p className="pub-empty__body">
            {e instanceof Error ? e.message : String(e)}
          </p>
        </div>
      </>
    );
  }

  const text = await res.text();
  let data: GraphRunDetail | null = null;
  try {
    data = JSON.parse(text) as GraphRunDetail;
  } catch {
    /* handled below */
  }

  if (res.status === 404) {
    notFound();
  }

  if (res.ok && data?.backend_unimplemented) {
    return (
      <>
        <p className="muted small cp-crumb-line">
          <Link href="/runs">← Runs</Link>
          {" · "}
          <Link href="/review">Review</Link>
        </p>
        <h1 className="pub-page-title">Graph run</h1>
        <div className="pub-empty" role="status">
          <p className="pub-empty__title">Run detail not available on this build</p>
          <p className="pub-empty__body">
            {data.message ??
              "Persisted run detail requires GET /orchestrator/runs/{id}/detail on the orchestrator."}
          </p>
        </div>
      </>
    );
  }

  if (!res.ok || !data?.summary) {
    const err =
      typeof (data as GraphRunDetail | null)?.error === "string"
        ? (data as GraphRunDetail).error
        : text.slice(0, 400);
    return (
      <>
        <p className="muted small" style={{ marginBottom: "0.75rem" }}>
          <Link href="/runs">← Runs</Link>
          {" · "}
          <Link href="/review">Review</Link>
        </p>
        <h1 className="pub-page-title">Graph run</h1>
        <div className="pub-empty" role="alert">
          <p className="pub-empty__title">Could not load this run</p>
          <p className="pub-empty__body mono small">
            HTTP {res.status}. {err}
          </p>
        </div>
      </>
    );
  }

  const s = data.summary;
  const out = data.associated_outputs ?? {};
  const sid = out.staging_snapshot_id;
  const timeline = data.timeline ?? [];
  const invocations = data.role_invocations ?? [];
  const operatorActions = data.operator_actions ?? [];
  const scen = scenarioBadgeLabel(data.scenario_badge);
  const routingView = buildGeneratorRoutingView(data.scenario_tag, invocations);

  const hasStagingSkippedTimeline = timeline.some(
    (t) =>
      t.kind === "staging_skipped" || t.event_type === "staging_snapshot_skipped",
  );
  const policyAwareNoSnapshot =
    !sid &&
    (s.attention_state === "completed_snapshot_skipped_by_policy" ||
      hasStagingSkippedTimeline);

  let stagingDetail: StagingDetail | null = null;
  let stagingFetchErr: string | null = null;
  if (sid) {
    const stUrl = `${origin}/api/staging/${encodeURIComponent(sid)}`;
    const stRes = await fetch(stUrl, { cache: "no-store" });
    if (stRes.ok) {
      try {
        stagingDetail = (await stRes.json()) as StagingDetail;
      } catch {
        stagingFetchErr = "Invalid JSON from staging API";
      }
    } else {
      stagingFetchErr = `HTTP ${stRes.status}`;
    }
  }

  return (
    <>
      <p className="muted small cp-crumb-line">
        <Link href="/runs">← Runs</Link>
        {" · "}
        <Link href="/review">Review</Link>
        {" · "}
        <Link href="/publication">Publication</Link>
        {s.identity_id ? (
          <>
            {" · "}
            <IdentityNavExtras identityId={s.identity_id} />
          </>
        ) : null}
      </p>

      <h1 className="pub-page-title">Graph run</h1>
      <p className="muted small" style={{ marginBottom: "0.25rem" }}>
        <strong>graph_run_id</strong> — this run (API / debugging)
      </p>
      <p className="pub-page-id mono">{s.graph_run_id}</p>
      <p className="muted small" style={{ marginTop: "0.75rem", marginBottom: "0.25rem" }}>
        <strong>thread_id</strong> — thread scope (live habitat, working staging, materialize snapshot)
      </p>
      <p className="pub-page-id mono">
        {s.thread_id}
        <span className="muted small" style={{ marginLeft: "0.5rem" }}>
          ·{" "}
          <Link href={`/habitat/live/${encodeURIComponent(s.thread_id)}`}>Open live habitat</Link>
        </span>
      </p>
      {s.working_staging_present === false ? (
        <p className="op-banner op-banner--warn" style={{ marginTop: "0.75rem", marginBottom: 0 }}>
          <strong>No working staging row</strong> for this thread yet.{" "}
          <Link href={`/habitat/live/${encodeURIComponent(s.thread_id)}`}>Live habitat</Link> will
          404 until a run reaches the staging step and persists mutable staging (failed runs often
          stop before that).
        </p>
      ) : null}
      {scen ? (
        <p className="muted small" style={{ marginTop: "-0.25rem", marginBottom: "0.5rem" }}>
          <span className={scen.className} title={data.scenario_tag ?? ""}>
            {scen.label}
          </span>
          {data.scenario_tag ? (
            <span className="mono small" style={{ marginLeft: "0.5rem" }}>
              {data.scenario_tag}
            </span>
          ) : null}
        </p>
      ) : null}

      <p className="op-banner op-banner--neutral">
        <strong>Persisted execution</strong> — one orchestrator pass as stored rows. Not a live
        stream; refresh to update. Review surface is staging; canon is publication.
      </p>

      {data.session_staging ? (
        <div className="op-card op-card--compact" style={{ marginBottom: "1rem" }}>
          <h2 className="op-section-title" style={{ marginBottom: "0.35rem" }}>
            Session staging (live)
          </h2>
          <p className="muted small" style={{ marginTop: 0 }}>
            Stable for this run: points at the <strong>current working staging</strong> for the
            thread (updates as generator iterations apply). Unlike snapshot review links, this does
            not change when new iterations land.
          </p>
          <p className="small" style={{ marginBottom: 0 }}>
            <Link href={data.session_staging.control_plane_live_habitat_path ?? `/habitat/live/${encodeURIComponent(s.thread_id)}`}>
              Open live habitat page
            </Link>
            <span className="muted small"> — human view of mutable working staging · </span>
            <a
              href={`/api/runs/${encodeURIComponent(graphRunId)}/staging-preview`}
              target="_blank"
              rel="noopener noreferrer"
            >
              raw HTML preview
            </a>
            <span className="muted small">
              {" "}
              · full payload:{" "}
              <code className="mono small" title="GET on orchestrator">
                {data.session_staging.orchestrator_working_staging_json_path}
              </code>
            </span>
          </p>
          <p className="small" style={{ marginTop: "0.65rem", marginBottom: 0 }}>
            <MaterializeReviewSnapshotButton threadId={s.thread_id} />
            <span className="muted small" style={{ marginLeft: "0.35rem" }}>
              Freeze current live working staging into an immutable review row (when policy skipped auto-snapshots).
            </span>
          </p>
        </div>
      ) : null}

      <RuntimeObservabilityCard summary={s} lastMeaningful={data.last_meaningful_event} />

      <section className="pub-hero">
        <div className="pub-hero__head">
          <h2 className="op-section-title" style={{ margin: 0 }}>
            Run at a glance
          </h2>
          <span className="pub-hero__timestamp">Started {formatWhen(s.started_at)}</span>
        </div>
        <div className="pub-hero__grid">
          <div>
            <span className="pub-hero__label">Status</span>
            <div className="pub-hero__value">
              <span className="op-badge op-badge--neutral">{s.status}</span>
            </div>
          </div>
          <div>
            <span className="pub-hero__label">Trigger</span>
            <div className="pub-hero__value">{s.trigger_type}</div>
          </div>
          <div>
            <span className="pub-hero__label">Iterations (max)</span>
            <div className="pub-hero__value">{s.max_iteration_index ?? "—"}</div>
          </div>
          <div>
            <span className="pub-hero__label">State hint</span>
            <div className="pub-hero__value">{s.run_state_hint || "—"}</div>
          </div>
          <div>
            <span className="pub-hero__label">Ended</span>
            <div className="pub-hero__value">{formatWhen(s.ended_at)}</div>
          </div>
          <div>
            <span className="pub-hero__label">Attention</span>
            <div className="pub-hero__value">
              <span className="mono small">{s.attention_state ?? "—"}</span>
            </div>
          </div>
          <div className="pub-hero__span-full">
            <span className="pub-hero__label">Identity</span>
            <div className="pub-hero__value">
              {s.identity_id ? (
                <>
                  <Link href={identityOverviewPath(s.identity_id)} title="Identity overview">
                    {s.identity_id}
                  </Link>
                  <span className="muted small"> · </span>
                  <IdentityContextLinks identityId={s.identity_id} />
                </>
              ) : (
                <span className="muted">No identity on thread</span>
              )}
            </div>
          </div>
        </div>
        <div
          className={graphRunAttentionBannerClass(s.attention_state)}
          style={{ marginTop: "0.85rem", marginBottom: 0 }}
        >
          <strong>Operator attention</strong> — {s.attention_reason ?? "—"}
        </div>
      </section>

      {sid ? (
        <StagingFactsCard
          staging={stagingDetail}
          error={stagingFetchErr}
          publicationSnapshotId={out.publication_snapshot_id ?? null}
        />
      ) : policyAwareNoSnapshot ? (
        <div className="op-banner op-banner--neutral" style={{ marginBottom: "0.85rem" }}>
          <p style={{ margin: "0 0 0.5rem" }}>
            <strong>No frozen review snapshot for this graph run id.</strong> The orchestrator recorded{" "}
            <code className="mono small">staging_snapshot_skipped</code> (automatic review rows follow{" "}
            <code className="mono small">staging_snapshot_policy</code>
            ). <strong>Live working staging</strong> may still contain the latest build — open{" "}
            <Link href={`/habitat/live/${encodeURIComponent(s.thread_id)}`}>live habitat</Link> to verify.
          </p>
          <p style={{ margin: 0 }} className="small">
            <MaterializeReviewSnapshotButton threadId={s.thread_id} />{" "}
            <span className="muted small">to create a review snapshot from the current live state.</span>
          </p>
        </div>
      ) : (
        <div className="op-banner op-banner--warn" style={{ marginBottom: "0.85rem" }}>
          <p style={{ margin: "0 0 0.5rem" }}>
            <strong>No staging snapshot linked to this run id.</strong> If the run should have produced one
            (policy <code className="mono small">always</code>), check the event timeline for{" "}
            <code className="mono small">staging_snapshot_blocked</code> or errors. Otherwise use{" "}
            <Link href={`/habitat/live/${encodeURIComponent(s.thread_id)}`}>live habitat</Link> and{" "}
            <MaterializeReviewSnapshotButton threadId={s.thread_id} label="materialize" /> if the live build is
            what you want to review.
          </p>
        </div>
      )}

      <div className="op-card op-card--compact" style={{ marginBottom: "1rem" }}>
        <h2 className="op-section-title" style={{ marginBottom: "0.35rem" }}>
          Generator routing (KMBL)
        </h2>
        <p className="muted small" style={{ marginTop: 0 }}>
          <span className="op-badge op-badge--neutral" title="Where routing hints came from">
            routing facts: {routingView.routingFactSource}
          </span>{" "}
          — This is <strong>diagnostic</strong>, not an error.{" "}
          <code>persisted</code> means the orchestrator saved routing metadata on the generator invocation
          (default <code>kmbl-generator</code> vs image agent when applicable). It does not mean the run failed.
        </p>
        {routingView.persistedRoutingLines.length > 0 ? (
          <>
            <h3 className="op-subtitle" style={{ marginBottom: "0.35rem" }}>
              Persisted routing metadata
            </h3>
            <ul className="cp-routing-hints">
              {routingView.persistedRoutingLines.map((line, i) => (
                <li key={`p-${i}`}>{line}</li>
              ))}
            </ul>
          </>
        ) : null}
        <h3 className="op-subtitle" style={{ marginBottom: "0.35rem", marginTop: "0.65rem" }}>
          OpenClaw provider config (persisted)
        </h3>
        <ul className="cp-routing-hints">
          {routingView.providerConfigLines.map((line, i) => (
            <li key={`c-${i}`}>{line}</li>
          ))}
        </ul>
        {routingView.heuristicScenarioLines.length > 0 ? (
          <>
            <h3 className="op-subtitle" style={{ marginBottom: "0.35rem", marginTop: "0.65rem" }}>
              Scenario tag (heuristic)
            </h3>
            <ul className="cp-routing-hints">
              {routingView.heuristicScenarioLines.map((line, i) => (
                <li key={`h-${i}`}>{line}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>

      <RunResumeActions
        graphRunId={graphRunId}
        resumeEligible={data.resume_eligible === true}
        resumeExplanation={data.resume_operator_explanation ?? null}
        retryDeferredNote={data.retry_deferred_note ?? null}
        runStatus={s.status}
        interruptRequestedAt={s.interrupt_requested_at}
      />

      <div className="op-card">
        <h2 className="op-section-title">Identifiers & checkpoints</h2>
        <dl className="pub-lineage-dl">
          <dt>graph_run_id</dt>
          <dd className="mono">{s.graph_run_id}</dd>
          <dt>thread_id</dt>
          <dd className="mono">{s.thread_id}</dd>
          <dt>latest_checkpoint_id</dt>
          <dd className="mono small">{s.latest_checkpoint_id ?? "—"}</dd>
          <dt>Resume count</dt>
          <dd>{s.resume_count ?? 0}</dd>
          <dt>Last resumed</dt>
          <dd>{formatWhen(s.last_resumed_at)}</dd>
        </dl>
      </div>

      <div className="op-card">
        <h2 className="op-section-title">Operator actions</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Persisted <code>graph_run_event</code> rows (resume, etc.). Not inferred from checkpoints.
        </p>
        {operatorActions.length === 0 ? (
          <p className="muted small">No operator-triggered events for this run.</p>
        ) : (
          <ul className="op-list op-list--compact">
            {operatorActions.map((a, i) => (
              <li key={`${a.kind}-${a.timestamp}-${i}`} className="op-card op-card--compact">
                <p className="op-card__title" style={{ marginBottom: "0.25rem" }}>
                  <span className="op-badge op-badge--operator">operator</span>{" "}
                  <span>{a.label}</span>
                </p>
                <p className="muted small">{formatWhen(a.timestamp)}</p>
                {a.details && Object.keys(a.details).length > 0 ? (
                  <details className="small" style={{ marginTop: "0.35rem" }}>
                    <summary className="muted">Details</summary>
                    <pre className="op-pre small-pre">{JSON.stringify(a.details)}</pre>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="op-card">
        <h2 className="op-section-title">Event timeline</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Stored graph_run_event rows only. <span className="op-badge op-badge--operator">operator</span>{" "}
          matches API-triggered mutations.
        </p>
        {timeline.length === 0 ? (
          <p className="muted small">No events recorded for this run.</p>
        ) : (
          <ul className="op-timeline runs-timeline-compact">
            {timeline.map((it, i) => (
              <li
                key={`${it.event_type}-${it.timestamp}-${i}`}
                className={it.operator_triggered ? "op-timeline__operator" : undefined}
              >
                {it.operator_triggered ? (
                  <span className="op-timeline__operator-badge op-badge op-badge--operator">
                    operator
                  </span>
                ) : null}
                <span className="op-timeline__label">{it.label}</span>
                <span className="op-timeline__at">{formatWhen(it.timestamp)}</span>
                {it.related_id ? (
                  <span className="op-timeline__at">
                    {it.kind === "staging_created" ||
                    it.kind === "staging_approved" ||
                    it.kind === "staging_unapproved" ||
                    it.kind === "staging_rejected" ? (
                      <Link href={`/review/staging/${encodeURIComponent(it.related_id)}`}>
                        staging {shortId(it.related_id)}
                      </Link>
                    ) : it.kind === "publication_created" ? (
                      <Link href={`/publication/${encodeURIComponent(it.related_id)}`}>
                        publication {shortId(it.related_id)}
                      </Link>
                    ) : (
                      <span className="mono small">{shortId(it.related_id)}</span>
                    )}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="op-card">
        <h2 className="op-section-title">Role invocations</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Execution order by <code>started_at</code>. No raw payloads.
        </p>
        {invocations.length === 0 ? (
          <p className="muted small">No role invocations recorded.</p>
        ) : (
          <div className="op-table-wrap">
            <table className="op-table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Iter</th>
                  <th>Provider</th>
                  <th>Config</th>
                  <th>Started</th>
                  <th>Ended</th>
                </tr>
              </thead>
              <tbody>
                {invocations.map((r) => (
                  <tr key={r.role_invocation_id}>
                    <td className="mono">{r.role_type}</td>
                    <td>
                      <span className="op-badge op-badge--neutral">{r.status}</span>
                    </td>
                    <td>{r.iteration_index}</td>
                    <td className="mono small">{r.provider}</td>
                    <td className="mono small">{r.provider_config_key}</td>
                    <td className="small">{formatWhen(r.started_at)}</td>
                    <td className="small">{formatWhen(r.ended_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="op-card">
        <h2 className="op-section-title">Associated outputs</h2>
        <p className="muted small" style={{ marginBottom: "0.65rem" }}>
          Linked build/eval rows and staging/publication when present. Publication appears only if a
          publication row references this <code>graph_run_id</code>.
        </p>
        <div className="run-detail-outputs">
          <dl className="pub-lineage-dl">
            <dt>build_spec_id</dt>
            <dd className="mono">{out.build_spec_id ?? "—"}</dd>
            <dt>build_candidate_id</dt>
            <dd className="mono">{out.build_candidate_id ?? "—"}</dd>
            <dt>evaluation_report_id</dt>
            <dd className="mono">{out.evaluation_report_id ?? "—"}</dd>
          </dl>
          <dl className="pub-lineage-dl">
            <dt>staging_snapshot_id</dt>
            <dd className="mono">
              {out.staging_snapshot_id ? (
                <Link href={`/review/staging/${encodeURIComponent(out.staging_snapshot_id)}`}>
                  {out.staging_snapshot_id}
                </Link>
              ) : (
                "—"
              )}
            </dd>
            <dt>publication_snapshot_id</dt>
            <dd className="mono">
              {out.publication_snapshot_id ? (
                <Link href={`/publication/${encodeURIComponent(out.publication_snapshot_id)}`}>
                  {out.publication_snapshot_id}
                </Link>
              ) : (
                "—"
              )}
            </dd>
          </dl>
        </div>
      </div>

      <details className="debug-panel" style={{ marginTop: "1.25rem" }}>
        <summary>Raw JSON (debug)</summary>
        <pre className="op-pre">{JSON.stringify(data, null, 2)}</pre>
      </details>
    </>
  );
}

import Link from "next/link";

import type {

  GraphRunListResponse,

  ProposalsResponse,

  PublicationDetail,

  PublicationListResponse,

} from "@/lib/api-types";

import {

  identityOverviewPath,

  publicationIndexWithIdentity,

  reviewIndexWithIdentity,

  runsIndexWithIdentity,

  parseIdentityUuidParam,

} from "@/lib/identity-nav";

import { graphRunAttentionBadgeClass } from "@/lib/operator-attention";

import { serverOriginFromHeaders } from "@/lib/server-origin";



export const dynamic = "force-dynamic";



const PREVIEW_LIMIT = 5;



function formatWhen(iso: string | null | undefined) {

  if (!iso) return "—";

  try {

    return new Date(iso).toLocaleString();

  } catch {

    return iso;

  }

}



export default async function IdentityOverviewPage({

  params,

}: {

  params: { identityId: string };

}) {

  const id = parseIdentityUuidParam(params.identityId);

  if (!id) {

    return (

      <>

        <h1>Identity</h1>

        <div className="debug-panel debug-panel--err" role="alert">

          <p>Invalid identity id. Use a canonical UUID in the path (same format as filters).</p>

        </div>

        <p className="muted small">

          <Link href="/runs">Runs</Link>

          {" · "}

          <Link href="/review">Review</Link>

          {" · "}

          <Link href="/publication">Publication</Link>

        </p>

      </>

    );

  }



  const origin = serverOriginFromHeaders();

  const qs = new URLSearchParams({ identity_id: id, limit: String(PREVIEW_LIMIT) });



  const runsUrl = `${origin}/api/runs?${qs}`;

  const proposalsUrl = `${origin}/api/proposals?${qs}`;

  const pubListUrl = `${origin}/api/publication?${qs}`;

  const pubCurrentUrl = `${origin}/api/publication/current?identity_id=${encodeURIComponent(id)}`;



  const [runsRes, proposalsRes, pubListRes, pubCurRes] = await Promise.all([

    fetch(runsUrl, { cache: "no-store" }),

    fetch(proposalsUrl, { cache: "no-store" }),

    fetch(pubListUrl, { cache: "no-store" }),

    fetch(pubCurrentUrl, { cache: "no-store" }),

  ]);



  async function parseJson<T>(res: Response): Promise<T | null> {

    const t = await res.text();

    try {

      return JSON.parse(t) as T;

    } catch {

      return null;

    }

  }



  const runsData = await parseJson<GraphRunListResponse>(runsRes);

  const proposalsData = await parseJson<ProposalsResponse>(proposalsRes);

  const pubListData = await parseJson<PublicationListResponse>(pubListRes);

  let currentPub: PublicationDetail | null = null;

  if (pubCurRes.ok) {

    currentPub = await parseJson<PublicationDetail>(pubCurRes);

  }



  const runsErr =

    !runsRes.ok || !runsData?.runs

      ? (typeof runsData?.error === "string" ? runsData.error : `HTTP ${runsRes.status}`)

      : null;

  const proposalsErr =

    !proposalsRes.ok || proposalsData?.proposals === undefined

      ? typeof proposalsData?.error === "string"

        ? proposalsData.error

        : `HTTP ${proposalsRes.status}`

      : null;

  const pubListErr =

    !pubListRes.ok || pubListData?.publications === undefined

      ? typeof pubListData?.error === "string"

        ? pubListData.error

        : `HTTP ${pubListRes.status}`

      : null;



  const runs = runsData?.runs ?? [];

  const proposals = proposalsData?.proposals ?? [];

  const publications = pubListData?.publications ?? [];



  return (

    <>

      <p className="muted">

        <Link href="/">Home</Link>

        {" · "}

        <Link href="/runs">Runs</Link>

        {" · "}

        <Link href="/review">Review</Link>

        {" · "}

        <Link href="/publication">Publication</Link>

      </p>



      <h1>Identity</h1>

      <div className="debug-panel">

        <h2 className="op-section-title">Summary</h2>

        <p className="muted small">

          Read-only snapshot composed from persisted runs, staging proposals, and publication

          rows for this <code>identity_id</code>. Not a live stream; refresh to reload. Narrow

          work on{" "}

          <Link href={runsIndexWithIdentity(id)}>runs</Link>,{" "}

          <Link href={reviewIndexWithIdentity(id)}>queue</Link>, or{" "}

          <Link href={publicationIndexWithIdentity(id)}>list</Link>.

        </p>

        <dl className="debug-kv">

          <dt>identity_id</dt>

          <dd className="mono">{id}</dd>

        </dl>

      </div>



      <div className="debug-panel op-banner op-banner--neutral">

        <h2 className="op-section-title">Runtime</h2>

        {runsErr ? (

          <p className="muted small" role="alert">

            Could not load runs: {runsErr}

          </p>

        ) : (

          <>

            <p className="muted small">

              Preview (up to {PREVIEW_LIMIT}). Full index:{" "}

              <Link href={runsIndexWithIdentity(id)}>runs</Link>.

            </p>

            {runs.length === 0 ? (

              <p className="muted">No runs in this window.</p>

            ) : (

              <ul className="op-list op-list--compact">

                {runs.map((r) => (

                  <li key={r.graph_run_id} className="op-card op-card--compact">

                    <p className="op-card__title">

                      <Link
                        href={`/runs/${encodeURIComponent(r.graph_run_id)}`}
                        title="Run detail"
                      >

                        {r.graph_run_id}

                      </Link>{" "}

                      <span className="op-badge op-badge--neutral">{r.status}</span>

                    </p>

                    <p className="muted small">

                      {r.trigger_type} · {formatWhen(r.started_at)}

                      {r.attention_state ? (

                        <>

                          {" "}

                          ·{" "}

                          <span

                            className={graphRunAttentionBadgeClass(r.attention_state)}

                            title={r.attention_reason ?? ""}

                          >

                            {r.attention_state}

                          </span>

                        </>

                      ) : null}

                    </p>

                  </li>

                ))}

              </ul>

            )}

          </>

        )}

      </div>



      <div className="debug-panel">

        <h2 className="op-section-title">Review queue</h2>

        {proposalsErr ? (

          <p className="muted small" role="alert">

            Could not load proposals: {proposalsErr}

          </p>

        ) : (

          <>

            <p className="muted small">

              Preview (up to {PREVIEW_LIMIT}). Full index:{" "}

              <Link href={reviewIndexWithIdentity(id)}>queue</Link>.

            </p>

            {proposals.length === 0 ? (

              <p className="muted">No staging rows in this window.</p>

            ) : (

              <ul className="op-list op-list--compact">

                {proposals.map((p) => (

                  <li key={p.staging_snapshot_id} className="op-card op-card--compact">

                    <p className="op-card__title">

                      <Link
                        href={`/review/staging/${encodeURIComponent(p.staging_snapshot_id)}`}
                        title="Staging detail"
                      >

                        {p.title ?? p.summary ?? p.staging_snapshot_id}

                      </Link>

                    </p>

                    <p className="muted small mono">{p.staging_snapshot_id}</p>

                  </li>

                ))}

              </ul>

            )}

          </>

        )}

      </div>



      <div className="debug-panel debug-panel--ok">

        <h2 className="op-section-title">Canon (publication)</h2>

        {pubListErr ? (

          <p className="muted small" role="alert">

            Could not load publications: {pubListErr}

          </p>

        ) : (

          <>

            <p className="muted small">

              Full index: <Link href={publicationIndexWithIdentity(id)}>list</Link>.

            </p>

            {pubCurRes.status === 404 || !currentPub?.publication_snapshot_id ? (

              <p className="muted">No current publication snapshot for this identity.</p>

            ) : (

              <div className="debug-panel" style={{ marginTop: "0.5rem" }}>

                <p className="muted small">Latest for this identity</p>

                <dl className="debug-kv">

                  <dt>publication_snapshot_id</dt>

                  <dd className="mono">

                    <Link
                      href={`/publication/${encodeURIComponent(currentPub.publication_snapshot_id)}`}
                      title="Publication detail"
                    >

                      {currentPub.publication_snapshot_id}

                    </Link>

                  </dd>

                  <dt>visibility</dt>

                  <dd>

                    <span className="op-badge op-badge--canon">{currentPub.visibility}</span>

                  </dd>

                  <dt>published_at</dt>

                  <dd>{formatWhen(currentPub.published_at)}</dd>

                </dl>

              </div>

            )}

            {publications.length === 0 ? (

              <p className="muted" style={{ marginTop: "0.75rem" }}>

                No publication rows in the recent list window.

              </p>

            ) : (

              <>

                <h3 className="op-subtitle" style={{ marginTop: "0.75rem" }}>

                  Recent (preview)

                </h3>

                <ul className="op-list op-list--compact">

                  {publications.map((p) => (

                    <li key={p.publication_snapshot_id} className="op-card op-card--compact">

                      <p className="op-card__title">

                        <Link
                          href={`/publication/${encodeURIComponent(p.publication_snapshot_id)}`}
                          title="Publication detail"
                        >

                          {p.publication_snapshot_id}

                        </Link>

                      </p>

                      <p className="muted small">

                        {p.visibility} · {formatWhen(p.published_at)}

                      </p>

                    </li>

                  ))}

                </ul>

              </>

            )}

          </>

        )}

      </div>



      <p className="muted small">

        This URL is shareable:{" "}

        <span className="mono">{identityOverviewPath(id)}</span>

      </p>

    </>

  );

}


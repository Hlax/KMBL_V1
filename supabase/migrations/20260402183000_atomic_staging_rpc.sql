-- Atomic multi-write paths for working staging (orchestrator Supabase RPC).
-- Phase 1: single-transaction checkpoint + working_staging + optional staging_snapshot (graph staging_node).
--          single-transaction staging_checkpoint + publication_snapshot + working_staging (operator approve).
-- Phase 2: pg_advisory_xact_lock per thread inside each RPC (multi-process safe for these writes).

ALTER TABLE public.working_staging
  ADD COLUMN IF NOT EXISTS last_alignment_score double precision;

COMMENT ON COLUMN public.working_staging.last_alignment_score IS
  'Latest graph alignment score mirrored from evaluator (trend / live read model).';

-- Deterministic 64-bit advisory lock key from thread UUID (avoids hashtext 32-bit collisions).
CREATE OR REPLACE FUNCTION public.kmbl_thread_advisory_xact_lock(p_thread_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  PERFORM pg_advisory_xact_lock(
    (('x' || substr(md5(p_thread_id::text), 1, 16))::bit(64)::bigint)
  );
END;
$$;

COMMENT ON FUNCTION public.kmbl_thread_advisory_xact_lock(uuid) IS
  'Transaction-scoped advisory lock for a thread. Used inside RPCs; safe with pooled connections.';

-- ---------------------------------------------------------------------------
-- Graph staging_node bundle: 0..N checkpoints + working_staging + optional staging_snapshot
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.kmbl_atomic_staging_node_persist(
  p_thread_id uuid,
  p_checkpoints jsonb,
  p_working_staging jsonb,
  p_staging_snapshot jsonb
)
RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  el jsonb;
  ws_id uuid;
BEGIN
  PERFORM public.kmbl_thread_advisory_xact_lock(p_thread_id);

  IF p_checkpoints IS NOT NULL AND jsonb_typeof(p_checkpoints) = 'array' THEN
    FOR el IN SELECT value FROM jsonb_array_elements(p_checkpoints)
    LOOP
      INSERT INTO public.staging_checkpoint (
        staging_checkpoint_id,
        working_staging_id,
        thread_id,
        payload_snapshot_json,
        revision_at_checkpoint,
        trigger,
        source_graph_run_id,
        created_at,
        reason_category,
        reason_explanation
      ) VALUES (
        (el->>'staging_checkpoint_id')::uuid,
        (el->>'working_staging_id')::uuid,
        (el->>'thread_id')::uuid,
        COALESCE(el->'payload_snapshot_json', '{}'::jsonb),
        COALESCE(NULLIF(el->>'revision_at_checkpoint', '')::int, 0),
        COALESCE(el->>'trigger', 'post_patch'),
        NULLIF(el->>'source_graph_run_id', '')::uuid,
        COALESCE((el->>'created_at')::timestamptz, now()),
        NULLIF(el->>'reason_category', ''),
        NULLIF(el->>'reason_explanation', '')
      )
      ON CONFLICT (staging_checkpoint_id) DO NOTHING;
    END LOOP;
  END IF;

  ws_id := (p_working_staging->>'working_staging_id')::uuid;

  INSERT INTO public.working_staging (
    working_staging_id,
    thread_id,
    identity_id,
    payload_json,
    last_update_mode,
    last_update_graph_run_id,
    last_update_build_candidate_id,
    current_checkpoint_id,
    revision,
    status,
    created_at,
    updated_at,
    last_rebuild_revision,
    stagnation_count,
    last_evaluator_issue_count,
    last_revision_summary_json,
    last_alignment_score
  ) VALUES (
    ws_id,
    (p_working_staging->>'thread_id')::uuid,
    NULLIF(p_working_staging->>'identity_id', '')::uuid,
    COALESCE(p_working_staging->'payload_json', '{}'::jsonb),
    COALESCE(p_working_staging->>'last_update_mode', 'init'),
    NULLIF(p_working_staging->>'last_update_graph_run_id', '')::uuid,
    NULLIF(p_working_staging->>'last_update_build_candidate_id', '')::uuid,
    NULLIF(p_working_staging->>'current_checkpoint_id', '')::uuid,
    COALESCE(NULLIF(p_working_staging->>'revision', '')::int, 0),
    COALESCE(p_working_staging->>'status', 'draft'),
    COALESCE((p_working_staging->>'created_at')::timestamptz, now()),
    COALESCE((p_working_staging->>'updated_at')::timestamptz, now()),
    NULLIF(p_working_staging->>'last_rebuild_revision', '')::int,
    COALESCE(NULLIF(p_working_staging->>'stagnation_count', '')::int, 0),
    COALESCE(NULLIF(p_working_staging->>'last_evaluator_issue_count', '')::int, 0),
    COALESCE(p_working_staging->'last_revision_summary_json', '{}'::jsonb),
    NULLIF(p_working_staging->>'last_alignment_score', '')::double precision
  )
  ON CONFLICT (working_staging_id) DO UPDATE SET
    thread_id = EXCLUDED.thread_id,
    identity_id = EXCLUDED.identity_id,
    payload_json = EXCLUDED.payload_json,
    last_update_mode = EXCLUDED.last_update_mode,
    last_update_graph_run_id = EXCLUDED.last_update_graph_run_id,
    last_update_build_candidate_id = EXCLUDED.last_update_build_candidate_id,
    current_checkpoint_id = EXCLUDED.current_checkpoint_id,
    revision = EXCLUDED.revision,
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at,
    last_rebuild_revision = EXCLUDED.last_rebuild_revision,
    stagnation_count = EXCLUDED.stagnation_count,
    last_evaluator_issue_count = EXCLUDED.last_evaluator_issue_count,
    last_revision_summary_json = EXCLUDED.last_revision_summary_json,
    last_alignment_score = EXCLUDED.last_alignment_score,
    created_at = working_staging.created_at;

  IF p_staging_snapshot IS NOT NULL
     AND jsonb_typeof(p_staging_snapshot) = 'object'
     AND p_staging_snapshot <> 'null'::jsonb
  THEN
    INSERT INTO public.staging_snapshot (
      staging_snapshot_id,
      thread_id,
      build_candidate_id,
      graph_run_id,
      identity_id,
      prior_staging_snapshot_id,
      snapshot_payload_json,
      preview_url,
      status,
      created_at,
      approved_by,
      approved_at,
      rejected_by,
      rejected_at,
      rejection_reason,
      marked_for_review,
      mark_reason,
      review_tags,
      user_rating,
      user_feedback,
      rated_at
    ) VALUES (
      (p_staging_snapshot->>'staging_snapshot_id')::uuid,
      (p_staging_snapshot->>'thread_id')::uuid,
      (p_staging_snapshot->>'build_candidate_id')::uuid,
      NULLIF(p_staging_snapshot->>'graph_run_id', '')::uuid,
      NULLIF(p_staging_snapshot->>'identity_id', '')::uuid,
      NULLIF(p_staging_snapshot->>'prior_staging_snapshot_id', '')::uuid,
      COALESCE(p_staging_snapshot->'snapshot_payload_json', '{}'::jsonb),
      NULLIF(p_staging_snapshot->>'preview_url', ''),
      COALESCE(p_staging_snapshot->>'status', 'review_ready'),
      COALESCE((p_staging_snapshot->>'created_at')::timestamptz, now()),
      NULLIF(p_staging_snapshot->>'approved_by', ''),
      NULLIF(p_staging_snapshot->>'approved_at', '')::timestamptz,
      NULLIF(p_staging_snapshot->>'rejected_by', ''),
      NULLIF(p_staging_snapshot->>'rejected_at', '')::timestamptz,
      NULLIF(p_staging_snapshot->>'rejection_reason', ''),
      COALESCE((p_staging_snapshot->>'marked_for_review')::boolean, false),
      NULLIF(p_staging_snapshot->>'mark_reason', ''),
      CASE
        WHEN p_staging_snapshot ? 'review_tags'
          AND jsonb_typeof(p_staging_snapshot->'review_tags') = 'array'
        THEN ARRAY(SELECT jsonb_array_elements_text(p_staging_snapshot->'review_tags'))
        ELSE ARRAY[]::text[]
      END,
      NULLIF(p_staging_snapshot->>'user_rating', '')::int,
      NULLIF(p_staging_snapshot->>'user_feedback', ''),
      NULLIF(p_staging_snapshot->>'rated_at', '')::timestamptz
    )
    ON CONFLICT (staging_snapshot_id) DO NOTHING;
  END IF;
END;
$$;

COMMENT ON FUNCTION public.kmbl_atomic_staging_node_persist(uuid, jsonb, jsonb, jsonb) IS
  'Atomically apply staging_node persistence: staging_checkpoint rows, working_staging upsert, optional staging_snapshot.';

-- ---------------------------------------------------------------------------
-- Operator approve working staging: checkpoint + publication + frozen working_staging
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.kmbl_atomic_working_staging_approve(
  p_thread_id uuid,
  p_checkpoint jsonb,
  p_publication jsonb,
  p_working_staging jsonb
)
RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  cp jsonb := p_checkpoint;
  pub jsonb := p_publication;
  ws jsonb := p_working_staging;
BEGIN
  PERFORM public.kmbl_thread_advisory_xact_lock(p_thread_id);

  INSERT INTO public.staging_checkpoint (
    staging_checkpoint_id,
    working_staging_id,
    thread_id,
    payload_snapshot_json,
    revision_at_checkpoint,
    trigger,
    source_graph_run_id,
    created_at,
    reason_category,
    reason_explanation
  ) VALUES (
    (cp->>'staging_checkpoint_id')::uuid,
    (cp->>'working_staging_id')::uuid,
    (cp->>'thread_id')::uuid,
    COALESCE(cp->'payload_snapshot_json', '{}'::jsonb),
    COALESCE(NULLIF(cp->>'revision_at_checkpoint', '')::int, 0),
    COALESCE(cp->>'trigger', 'pre_approval'),
    NULLIF(cp->>'source_graph_run_id', '')::uuid,
    COALESCE((cp->>'created_at')::timestamptz, now()),
    NULLIF(cp->>'reason_category', ''),
    NULLIF(cp->>'reason_explanation', '')
  )
  ON CONFLICT (staging_checkpoint_id) DO NOTHING;

  INSERT INTO public.publication_snapshot (
    publication_snapshot_id,
    source_staging_snapshot_id,
    thread_id,
    graph_run_id,
    identity_id,
    payload_json,
    visibility,
    published_by,
    parent_publication_snapshot_id,
    published_at
  ) VALUES (
    (pub->>'publication_snapshot_id')::uuid,
    (pub->>'source_staging_snapshot_id')::uuid,
    NULLIF(pub->>'thread_id', '')::uuid,
    NULLIF(pub->>'graph_run_id', '')::uuid,
    NULLIF(pub->>'identity_id', '')::uuid,
    COALESCE(pub->'payload_json', '{}'::jsonb),
    COALESCE(pub->>'visibility', 'private'),
    NULLIF(pub->>'published_by', ''),
    NULLIF(pub->>'parent_publication_snapshot_id', '')::uuid,
    COALESCE((pub->>'published_at')::timestamptz, now())
  )
  ON CONFLICT (publication_snapshot_id) DO NOTHING;

  INSERT INTO public.working_staging (
    working_staging_id,
    thread_id,
    identity_id,
    payload_json,
    last_update_mode,
    last_update_graph_run_id,
    last_update_build_candidate_id,
    current_checkpoint_id,
    revision,
    status,
    created_at,
    updated_at,
    last_rebuild_revision,
    stagnation_count,
    last_evaluator_issue_count,
    last_revision_summary_json,
    last_alignment_score
  ) VALUES (
    (ws->>'working_staging_id')::uuid,
    (ws->>'thread_id')::uuid,
    NULLIF(ws->>'identity_id', '')::uuid,
    COALESCE(ws->'payload_json', '{}'::jsonb),
    COALESCE(ws->>'last_update_mode', 'init'),
    NULLIF(ws->>'last_update_graph_run_id', '')::uuid,
    NULLIF(ws->>'last_update_build_candidate_id', '')::uuid,
    NULLIF(ws->>'current_checkpoint_id', '')::uuid,
    COALESCE(NULLIF(ws->>'revision', '')::int, 0),
    COALESCE(ws->>'status', 'draft'),
    COALESCE((ws->>'created_at')::timestamptz, now()),
    COALESCE((ws->>'updated_at')::timestamptz, now()),
    NULLIF(ws->>'last_rebuild_revision', '')::int,
    COALESCE(NULLIF(ws->>'stagnation_count', '')::int, 0),
    COALESCE(NULLIF(ws->>'last_evaluator_issue_count', '')::int, 0),
    COALESCE(ws->'last_revision_summary_json', '{}'::jsonb),
    NULLIF(ws->>'last_alignment_score', '')::double precision
  )
  ON CONFLICT (working_staging_id) DO UPDATE SET
    thread_id = EXCLUDED.thread_id,
    identity_id = EXCLUDED.identity_id,
    payload_json = EXCLUDED.payload_json,
    last_update_mode = EXCLUDED.last_update_mode,
    last_update_graph_run_id = EXCLUDED.last_update_graph_run_id,
    last_update_build_candidate_id = EXCLUDED.last_update_build_candidate_id,
    current_checkpoint_id = EXCLUDED.current_checkpoint_id,
    revision = EXCLUDED.revision,
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at,
    last_rebuild_revision = EXCLUDED.last_rebuild_revision,
    stagnation_count = EXCLUDED.stagnation_count,
    last_evaluator_issue_count = EXCLUDED.last_evaluator_issue_count,
    last_revision_summary_json = EXCLUDED.last_revision_summary_json,
    last_alignment_score = EXCLUDED.last_alignment_score,
    created_at = working_staging.created_at;
END;
$$;

COMMENT ON FUNCTION public.kmbl_atomic_working_staging_approve(uuid, jsonb, jsonb, jsonb) IS
  'Atomically persist pre-approval staging_checkpoint, publication_snapshot, and frozen working_staging.';

-- ---------------------------------------------------------------------------
-- Standalone working_staging upsert (operator rollback / fresh) under thread lock
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.kmbl_atomic_upsert_working_staging(
  p_thread_id uuid,
  p_working_staging jsonb
)
RETURNS void
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  ws jsonb := p_working_staging;
BEGIN
  PERFORM public.kmbl_thread_advisory_xact_lock(p_thread_id);

  INSERT INTO public.working_staging (
    working_staging_id,
    thread_id,
    identity_id,
    payload_json,
    last_update_mode,
    last_update_graph_run_id,
    last_update_build_candidate_id,
    current_checkpoint_id,
    revision,
    status,
    created_at,
    updated_at,
    last_rebuild_revision,
    stagnation_count,
    last_evaluator_issue_count,
    last_revision_summary_json,
    last_alignment_score
  ) VALUES (
    (ws->>'working_staging_id')::uuid,
    (ws->>'thread_id')::uuid,
    NULLIF(ws->>'identity_id', '')::uuid,
    COALESCE(ws->'payload_json', '{}'::jsonb),
    COALESCE(ws->>'last_update_mode', 'init'),
    NULLIF(ws->>'last_update_graph_run_id', '')::uuid,
    NULLIF(ws->>'last_update_build_candidate_id', '')::uuid,
    NULLIF(ws->>'current_checkpoint_id', '')::uuid,
    COALESCE(NULLIF(ws->>'revision', '')::int, 0),
    COALESCE(ws->>'status', 'draft'),
    COALESCE((ws->>'created_at')::timestamptz, now()),
    COALESCE((ws->>'updated_at')::timestamptz, now()),
    NULLIF(ws->>'last_rebuild_revision', '')::int,
    COALESCE(NULLIF(ws->>'stagnation_count', '')::int, 0),
    COALESCE(NULLIF(ws->>'last_evaluator_issue_count', '')::int, 0),
    COALESCE(ws->'last_revision_summary_json', '{}'::jsonb),
    NULLIF(ws->>'last_alignment_score', '')::double precision
  )
  ON CONFLICT (working_staging_id) DO UPDATE SET
    thread_id = EXCLUDED.thread_id,
    identity_id = EXCLUDED.identity_id,
    payload_json = EXCLUDED.payload_json,
    last_update_mode = EXCLUDED.last_update_mode,
    last_update_graph_run_id = EXCLUDED.last_update_graph_run_id,
    last_update_build_candidate_id = EXCLUDED.last_update_build_candidate_id,
    current_checkpoint_id = EXCLUDED.current_checkpoint_id,
    revision = EXCLUDED.revision,
    status = EXCLUDED.status,
    updated_at = EXCLUDED.updated_at,
    last_rebuild_revision = EXCLUDED.last_rebuild_revision,
    stagnation_count = EXCLUDED.stagnation_count,
    last_evaluator_issue_count = EXCLUDED.last_evaluator_issue_count,
    last_revision_summary_json = EXCLUDED.last_revision_summary_json,
    last_alignment_score = EXCLUDED.last_alignment_score,
    created_at = working_staging.created_at;
END;
$$;

COMMENT ON FUNCTION public.kmbl_atomic_upsert_working_staging(uuid, jsonb) IS
  'Upsert working_staging with thread advisory lock (operator rollback / other single-row writes).';

GRANT EXECUTE ON FUNCTION public.kmbl_thread_advisory_xact_lock(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.kmbl_atomic_staging_node_persist(uuid, jsonb, jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.kmbl_atomic_working_staging_approve(uuid, jsonb, jsonb, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.kmbl_atomic_upsert_working_staging(uuid, jsonb) TO service_role;

-- working_staging and staging_checkpoint tables
-- These support the mutable live surface and checkpoint system for threads

-- Working Staging: mutable live surface for a thread/identity
CREATE TABLE IF NOT EXISTS public.working_staging (
    working_staging_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL,
    identity_id UUID,
    
    payload_json JSONB NOT NULL DEFAULT '{}',
    
    last_update_mode TEXT NOT NULL DEFAULT 'init',
    last_update_graph_run_id UUID,
    last_update_build_candidate_id UUID,
    
    current_checkpoint_id UUID,
    
    revision INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    last_rebuild_revision INTEGER,
    stagnation_count INTEGER NOT NULL DEFAULT 0,
    last_evaluator_issue_count INTEGER NOT NULL DEFAULT 0,
    last_revision_summary_json JSONB NOT NULL DEFAULT '{}'
);

-- Index for lookups by thread
CREATE INDEX IF NOT EXISTS working_staging_thread_id_idx ON public.working_staging(thread_id);
CREATE INDEX IF NOT EXISTS working_staging_identity_id_idx ON public.working_staging(identity_id);

-- Staging Checkpoint: lightweight recovery points for working staging
CREATE TABLE IF NOT EXISTS public.staging_checkpoint (
    staging_checkpoint_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    working_staging_id UUID NOT NULL,
    thread_id UUID NOT NULL,
    
    payload_snapshot_json JSONB NOT NULL DEFAULT '{}',
    revision_at_checkpoint INTEGER NOT NULL DEFAULT 0,
    
    trigger TEXT NOT NULL DEFAULT 'post_patch',
    
    source_graph_run_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    reason_category TEXT,
    reason_explanation TEXT
);

-- Index for lookups by working_staging_id
CREATE INDEX IF NOT EXISTS staging_checkpoint_working_staging_id_idx ON public.staging_checkpoint(working_staging_id);
CREATE INDEX IF NOT EXISTS staging_checkpoint_thread_id_idx ON public.staging_checkpoint(thread_id);

-- Enable RLS
ALTER TABLE public.working_staging ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.staging_checkpoint ENABLE ROW LEVEL SECURITY;

-- Permissive policies (adjust as needed for your security model)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'working_staging_allow_all' AND tablename = 'working_staging') THEN
    CREATE POLICY working_staging_allow_all ON public.working_staging FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'staging_checkpoint_allow_all' AND tablename = 'staging_checkpoint') THEN
    CREATE POLICY staging_checkpoint_allow_all ON public.staging_checkpoint FOR ALL USING (true);
  END IF;
END $$;

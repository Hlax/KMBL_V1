-- Autonomous loop: tracks ongoing creative iteration for an identity
CREATE TABLE IF NOT EXISTS public.autonomous_loop (
    loop_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id UUID NOT NULL,
    identity_url TEXT NOT NULL,
    
    -- Loop state
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, paused, completed, failed
    phase TEXT NOT NULL DEFAULT 'identity_fetch',  -- identity_fetch, planning, generating, evaluating, proposing
    
    -- Iteration tracking
    iteration_count INTEGER NOT NULL DEFAULT 0,
    max_iterations INTEGER NOT NULL DEFAULT 50,
    
    -- Current work references
    current_thread_id UUID,
    current_graph_run_id UUID,
    last_staging_snapshot_id UUID,
    last_evaluator_status TEXT,
    last_evaluator_score REAL,
    
    -- Planner exploration state
    exploration_directions JSONB NOT NULL DEFAULT '[]',  -- planner's suggested next directions
    completed_directions JSONB NOT NULL DEFAULT '[]',    -- what we've already tried
    
    -- Auto-publication settings
    auto_publish_threshold REAL NOT NULL DEFAULT 0.85,  -- evaluator confidence to auto-publish
    proposed_staging_id UUID,  -- staging snapshot evaluator wants to propose
    proposed_at TIMESTAMPTZ,
    
    -- Lock for cron
    locked_at TIMESTAMPTZ,
    locked_by TEXT,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    
    -- Stats
    total_staging_count INTEGER NOT NULL DEFAULT 0,
    total_publication_count INTEGER NOT NULL DEFAULT 0,
    best_rating INTEGER,  -- highest user rating achieved
    
    CONSTRAINT valid_status CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed')),
    CONSTRAINT valid_phase CHECK (phase IN ('identity_fetch', 'planning', 'generating', 'evaluating', 'proposing', 'idle'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS autonomous_loop_status_idx ON public.autonomous_loop(status);
CREATE INDEX IF NOT EXISTS autonomous_loop_identity_id_idx ON public.autonomous_loop(identity_id);
CREATE INDEX IF NOT EXISTS autonomous_loop_locked_at_idx ON public.autonomous_loop(locked_at);

-- RLS
ALTER TABLE public.autonomous_loop ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'autonomous_loop_allow_all' AND tablename = 'autonomous_loop') THEN
    CREATE POLICY autonomous_loop_allow_all ON public.autonomous_loop FOR ALL USING (true);
  END IF;
END $$;

COMMENT ON TABLE public.autonomous_loop IS 'Tracks autonomous creative iteration loops for identities';
COMMENT ON COLUMN public.autonomous_loop.auto_publish_threshold IS 'Evaluator confidence score (0-1) required to auto-propose for publication';
COMMENT ON COLUMN public.autonomous_loop.exploration_directions IS 'Planner-suggested directions to explore next';

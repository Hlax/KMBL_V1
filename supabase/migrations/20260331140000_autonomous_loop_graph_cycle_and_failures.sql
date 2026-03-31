-- Replace obsolete phases (planning/generating/evaluating) with graph_cycle; add failure tracking.
ALTER TABLE public.autonomous_loop DROP CONSTRAINT IF EXISTS valid_phase;

UPDATE public.autonomous_loop
SET phase = 'graph_cycle'
WHERE phase IN ('planning', 'generating', 'evaluating');

ALTER TABLE public.autonomous_loop
ADD COLUMN IF NOT EXISTS last_error TEXT,
ADD COLUMN IF NOT EXISTS consecutive_graph_failures INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.autonomous_loop
ADD CONSTRAINT valid_phase CHECK (
    phase IN ('identity_fetch', 'graph_cycle', 'proposing', 'idle')
);

COMMENT ON COLUMN public.autonomous_loop.last_error IS 'Last graph or identity error message for operators';
COMMENT ON COLUMN public.autonomous_loop.consecutive_graph_failures IS 'Resets on successful graph tick; terminal fail when threshold exceeded';

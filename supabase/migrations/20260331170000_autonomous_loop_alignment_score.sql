-- Add last_alignment_score to autonomous_loop.
-- Tracks the most recent identity alignment score so the proposing phase can
-- compare against auto_publish_threshold using the real improvement signal.
-- Previously the loop used last_evaluator_score which was populated from agent-assigned
-- evaluator_confidence/overall_score fields (not comparable across runs).

ALTER TABLE autonomous_loop
    ADD COLUMN IF NOT EXISTS last_alignment_score double precision;

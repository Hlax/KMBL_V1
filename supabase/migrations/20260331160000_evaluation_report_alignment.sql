-- Add alignment scoring columns to evaluation_report.
-- These are populated by the orchestrator after every evaluator invocation when an
-- identity_brief is present. NULL means no identity context was available for the run.
--
-- alignment_score:         0.0–1.0 float; orchestrator-computed from evaluator alignment_report
--                          block or artifact content fallback. Drives auto_publish_threshold
--                          comparison and cross-run direction selection.
-- alignment_signals_json:  structured per-criterion breakdown (must_mention_hit_rate,
--                          palette_used, tone_reflected_rate, etc.)

ALTER TABLE evaluation_report
    ADD COLUMN IF NOT EXISTS alignment_score      double precision,
    ADD COLUMN IF NOT EXISTS alignment_signals_json jsonb NOT NULL DEFAULT '{}';

-- Index for efficient trend queries: latest alignment scores for a thread/identity
CREATE INDEX IF NOT EXISTS idx_evaluation_report_alignment_score
    ON evaluation_report (graph_run_id, alignment_score)
    WHERE alignment_score IS NOT NULL;

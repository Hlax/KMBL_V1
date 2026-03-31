-- Add mark_for_review fields to staging_snapshot
ALTER TABLE staging_snapshot 
  ADD COLUMN IF NOT EXISTS marked_for_review BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS mark_reason TEXT,
  ADD COLUMN IF NOT EXISTS review_tags TEXT[];

-- Index for filtering marked builds
CREATE INDEX IF NOT EXISTS staging_snapshot_marked_idx ON staging_snapshot(marked_for_review) WHERE marked_for_review = TRUE;

COMMENT ON COLUMN staging_snapshot.marked_for_review IS 'Evaluator flagged this build as worth human review';
COMMENT ON COLUMN staging_snapshot.mark_reason IS 'Why the evaluator marked it';
COMMENT ON COLUMN staging_snapshot.review_tags IS 'Tags like experimental, strong_typography, needs_polish';

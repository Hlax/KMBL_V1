-- Add user rating columns to staging_snapshot table
ALTER TABLE staging_snapshot 
  ADD COLUMN IF NOT EXISTS user_rating INTEGER CHECK (user_rating >= 1 AND user_rating <= 5),
  ADD COLUMN IF NOT EXISTS user_feedback TEXT,
  ADD COLUMN IF NOT EXISTS rated_at TIMESTAMPTZ;

-- Index for finding rated vs unrated snapshots
CREATE INDEX IF NOT EXISTS staging_snapshot_user_rating_idx ON staging_snapshot(user_rating);

COMMENT ON COLUMN staging_snapshot.user_rating IS '1-5 scale: 1=reject, 2=poor, 3=ok, 4=good, 5=excellent';
COMMENT ON COLUMN staging_snapshot.user_feedback IS 'Optional text feedback from user about what could be better';
COMMENT ON COLUMN staging_snapshot.rated_at IS 'When the rating was submitted';

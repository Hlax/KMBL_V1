-- Explicit amend chain: each new staging row can point at the previous snapshot on the same thread.
-- Supports review UX (open prior) and documents that artifact URLs (e.g. generated images) may repeat by design.

ALTER TABLE public.staging_snapshot
ADD COLUMN IF NOT EXISTS prior_staging_snapshot_id uuid
  REFERENCES public.staging_snapshot (staging_snapshot_id)
  ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS staging_snapshot_prior_staging_snapshot_id_idx
  ON public.staging_snapshot (prior_staging_snapshot_id);

COMMENT ON COLUMN public.staging_snapshot.prior_staging_snapshot_id IS
  'Previous staging_snapshot on the same thread (amend chain). Artifact refs may reuse image URLs across snapshots.';

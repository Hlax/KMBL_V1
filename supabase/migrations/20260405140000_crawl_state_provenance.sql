-- Add visit_provenance column to crawl_state for auditable crawl progression.
-- Records *why* each URL was marked visited (evidence tier + source).
ALTER TABLE public.crawl_state
    ADD COLUMN IF NOT EXISTS visit_provenance JSONB NOT NULL DEFAULT '{}'::jsonb;

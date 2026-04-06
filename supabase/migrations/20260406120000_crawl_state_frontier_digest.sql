-- Identity frontier: extracted/rejected URL lists + stable digest for planner grounding.
ALTER TABLE public.crawl_state
    ADD COLUMN IF NOT EXISTS extracted_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS rejected_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS extracted_fact_digest TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.crawl_state.extracted_urls IS
    'URLs with extracted identity/design facts (subset of visited).';
COMMENT ON COLUMN public.crawl_state.rejected_urls IS
    'URLs explicitly deprioritized or rejected from frontier selection.';
COMMENT ON COLUMN public.crawl_state.extracted_fact_digest IS
    'Short stable hash over page_summaries payload for stale detection.';

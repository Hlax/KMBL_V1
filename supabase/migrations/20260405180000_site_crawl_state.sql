-- Site-level crawl memory (reusable across identities sharing the same public site).
CREATE TABLE IF NOT EXISTS public.site_crawl_state (
    site_key              TEXT PRIMARY KEY,
    root_url              TEXT NOT NULL,
    visited_urls          JSONB NOT NULL DEFAULT '[]'::jsonb,
    unvisited_urls        JSONB NOT NULL DEFAULT '[]'::jsonb,
    page_summaries        JSONB NOT NULL DEFAULT '{}'::jsonb,
    visit_provenance      JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_status          TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (crawl_status IN ('in_progress', 'exhausted')),
    external_inspiration_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_pages_crawled   INT NOT NULL DEFAULT 0,
    last_crawled_at       TIMESTAMPTZ,
    site_memory_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_site_crawl_state_updated
    ON public.site_crawl_state (updated_at DESC);

-- Identity crawl row links to site-level memory (hybrid model).
ALTER TABLE public.crawl_state
    ADD COLUMN IF NOT EXISTS site_key TEXT;

ALTER TABLE public.crawl_state
    ADD COLUMN IF NOT EXISTS crawl_phase TEXT NOT NULL DEFAULT 'identity_grounding';

ALTER TABLE public.crawl_state
    ADD COLUMN IF NOT EXISTS has_reused_site_memory BOOLEAN NOT NULL DEFAULT false;

COMMENT ON TABLE public.site_crawl_state IS
    'Shared crawl frontier + page summaries for a canonical site key; reused across identities.';

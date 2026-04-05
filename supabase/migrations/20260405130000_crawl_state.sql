-- Durable crawl state per identity — tracks visited/unvisited URLs + page signals across sessions.
CREATE TABLE IF NOT EXISTS public.crawl_state (
    identity_id     UUID PRIMARY KEY,
    root_url        TEXT NOT NULL,
    visited_urls    JSONB NOT NULL DEFAULT '[]'::jsonb,
    unvisited_urls  JSONB NOT NULL DEFAULT '[]'::jsonb,
    page_summaries  JSONB NOT NULL DEFAULT '{}'::jsonb,
    crawl_status    TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (crawl_status IN ('in_progress', 'exhausted')),
    external_inspiration_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_pages_crawled INT NOT NULL DEFAULT 0,
    last_crawled_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast lookup by identity + updated_at for listing
CREATE INDEX IF NOT EXISTS idx_crawl_state_updated
    ON public.crawl_state (updated_at DESC);

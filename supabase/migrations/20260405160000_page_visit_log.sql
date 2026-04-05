-- Append-only log of browser-grounded page visits (local Playwright wrapper → orchestrator).
CREATE TABLE IF NOT EXISTS public.page_visit_log (
    page_visit_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id         UUID NOT NULL,
    thread_id           UUID,
    run_id              TEXT NOT NULL DEFAULT '',
    graph_run_id        UUID,
    role_invocation_id  UUID,
    requested_url       TEXT NOT NULL,
    resolved_url        TEXT,
    source_kind         TEXT NOT NULL DEFAULT 'portfolio_internal',
    status              TEXT NOT NULL DEFAULT 'pending',
    http_status         INT,
    page_title          TEXT,
    meta_description    TEXT,
    summary             TEXT,
    discovered_links    JSONB NOT NULL DEFAULT '[]'::jsonb,
    same_domain_links   JSONB NOT NULL DEFAULT '[]'::jsonb,
    traits_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_source     TEXT NOT NULL DEFAULT 'playwright_wrapper',
    timing_ms           INT,
    error                 TEXT,
    snapshot_path       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_page_visit_log_identity_created
    ON public.page_visit_log (identity_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_page_visit_log_graph_run
    ON public.page_visit_log (graph_run_id, created_at DESC)
    WHERE graph_run_id IS NOT NULL;

COMMENT ON TABLE public.page_visit_log IS
    'Browser-grounded crawl evidence from KMBL Playwright wrapper; append-only.';

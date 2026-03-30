-- Staging snapshot (product-facing review surface; docs/07 §1.11).

create table public.staging_snapshot (
  staging_snapshot_id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.thread (thread_id) on delete cascade,
  build_candidate_id uuid not null references public.build_candidate (build_candidate_id) on delete cascade,
  graph_run_id uuid references public.graph_run (graph_run_id) on delete set null,
  identity_id uuid,
  snapshot_payload_json jsonb not null default '{}'::jsonb,
  preview_url text,
  status text not null default 'review_ready',
  created_at timestamptz not null default now()
);

create index staging_snapshot_thread_id_idx on public.staging_snapshot (thread_id);
create index staging_snapshot_build_candidate_id_idx on public.staging_snapshot (build_candidate_id);
create index staging_snapshot_graph_run_id_idx on public.staging_snapshot (graph_run_id);

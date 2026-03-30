-- Immutable publication snapshots (canon) promoted from approved staging (Pass D).

create table public.publication_snapshot (
  publication_snapshot_id uuid primary key default gen_random_uuid(),
  source_staging_snapshot_id uuid not null references public.staging_snapshot (staging_snapshot_id),
  thread_id uuid references public.thread (thread_id) on delete set null,
  graph_run_id uuid references public.graph_run (graph_run_id) on delete set null,
  identity_id uuid,
  payload_json jsonb not null default '{}'::jsonb,
  visibility text not null default 'private',
  published_by text,
  parent_publication_snapshot_id uuid references public.publication_snapshot (publication_snapshot_id) on delete set null,
  published_at timestamptz not null default now(),
  constraint publication_snapshot_visibility_chk check (visibility in ('private', 'public'))
);

create index publication_snapshot_published_at_idx
  on public.publication_snapshot (published_at desc);
create index publication_snapshot_identity_idx
  on public.publication_snapshot (identity_id);
create index publication_snapshot_source_staging_idx
  on public.publication_snapshot (source_staging_snapshot_id);

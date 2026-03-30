-- Minimal identity spine: sources + profile (docs/07 §1.1–1.2) + graph_run.identity_id linkage.
-- Version: was 20260329210000 but collided with staging_snapshot_approval_audit in schema_migrations.

create table public.identity_source (
  identity_source_id uuid primary key default gen_random_uuid(),
  identity_id uuid not null,
  source_type text not null,
  source_uri text,
  raw_text text,
  metadata_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index identity_source_identity_id_idx on public.identity_source (identity_id);
create index identity_source_created_at_idx on public.identity_source (identity_id, created_at desc);

create table public.identity_profile (
  identity_id uuid primary key,
  profile_summary text,
  facets_json jsonb not null default '{}'::jsonb,
  open_questions_json jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.graph_run
  add column if not exists identity_id uuid;

create index if not exists graph_run_identity_id_idx on public.graph_run (identity_id);

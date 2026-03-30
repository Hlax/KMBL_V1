-- Pass F: audit fields for explicit staging approval (operator accountability).

alter table public.staging_snapshot
  add column if not exists approved_by text;

alter table public.staging_snapshot
  add column if not exists approved_at timestamptz;

comment on column public.staging_snapshot.approved_by is 'Operator identifier when status became approved (Pass F).';
comment on column public.staging_snapshot.approved_at is 'UTC timestamp when status became approved (Pass F).';

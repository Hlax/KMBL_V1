-- Rejection / unapprove audit columns (operator lifecycle).

alter table public.staging_snapshot
  add column if not exists rejected_at timestamptz null;

alter table public.staging_snapshot
  add column if not exists rejected_by text null;

alter table public.staging_snapshot
  add column if not exists rejection_reason text null;

comment on column public.staging_snapshot.rejected_at is 'UTC when status became rejected.';
comment on column public.staging_snapshot.rejected_by is 'Operator identifier when status became rejected.';
comment on column public.staging_snapshot.rejection_reason is 'Optional operator note when rejecting.';

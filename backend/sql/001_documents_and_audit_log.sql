create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  uploaded_by uuid,           -- Supabase auth user id
  status text not null default 'uploaded',
  created_at timestamptz not null default now()
);

create table if not exists audit_log (
  id bigint generated always as identity primary key,
  document_id uuid references documents(id),
  actor_id uuid,              -- Supabase auth user id
  actor_email text,
  action text not null,       -- e.g. 'upload','edit','approve','revoke_approval','process'
  detail jsonb,               -- action specifics, optional
  prev_hash text,             -- filled in by the hash-chain trigger, see 002
  entry_hash text,            -- filled in by the hash-chain trigger, see 002
  created_at timestamptz not null default now()
);

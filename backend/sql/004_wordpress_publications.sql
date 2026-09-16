-- Run this in the Supabase SQL editor for the project referenced by
-- SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in your .env.
--
-- Durable, append-only log of every real WordPress publish call. Unlike the
-- local per-document cache (wordpress-publication.json), this is never
-- wiped by document edits/re-approval, so the backend can always tell
-- whether a document was already published before -- even after the local
-- cache is gone -- and warn instead of silently creating a duplicate page.

create table if not exists wordpress_publications (
  id bigint generated always as identity primary key,
  document_id text not null,
  page_id bigint not null,
  status text not null check (status in ('draft', 'publish')),
  content_hash text not null,
  title text not null,
  edit_url text,
  preview_url text,
  published_at timestamptz not null,
  actor_id text,
  actor_email text,
  created_at timestamptz not null default now()
);

create index if not exists wordpress_publications_document_id_idx
  on wordpress_publications (document_id, published_at desc);

-- Service-role only (same pattern as audit_log / documents): the backend
-- reads/writes this with SUPABASE_SERVICE_ROLE_KEY, never exposed to the
-- frontend, so RLS can stay locked down with no public policies.
alter table wordpress_publications enable row level security;

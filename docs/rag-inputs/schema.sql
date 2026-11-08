-- Supabase schema for setups A and B (traditional RAG) and the evaluation results.
-- Run once in the Supabase SQL editor of a NEW project you own.
--
-- EMBEDDING SIZE: vector(1536) below must match the embedding model (2 places, marked ◆):
--   OpenAI text-embedding-3-small 1536 · Gemini gemini-embedding-001 1536 (or 768/3072) · Voyage 1024
-- Changing model later means: drop chunks, fix both sizes, re-run, re-ingest.

create extension if not exists vector;

-- One row per chunk from pipeline/chunk.py (same chunks LightRAG gets for setup C).
create table if not exists chunks (
  chunk_id     text primary key,               -- "report:rec-2", "act:s-77#2"
  doc_id       text not null,                  -- paper | report | act
  section_id   text not null,                  -- what the gold questions name
  heading_path text[] not null default '{}',
  content      text not null,
  metadata     jsonb not null default '{}',    -- doc_type, title, published, law_as_at, version
  embedding    vector(1536)                    -- ◆
);
create index if not exists chunks_doc on chunks (doc_id);
create index if not exists chunks_meta on chunks using gin (metadata);
alter table chunks enable row level security;  -- no policies: only the service key (n8n) can read or write

-- Setup A: match_chunks(query_embedding, k).  Setup B: the same, plus filters:
--   doc_ids       only these documents, e.g. '{report,act}'
--   law_as_of     only documents whose law is stated as at or before this date (law_as_at / published)
--   meta_filter   any other metadata match, e.g. '{"doc_type":"act"}'
create or replace function match_chunks(
  query_embedding vector(1536),                  -- ◆
  match_count     int default 5,
  doc_ids         text[] default null,
  law_as_of       date default null,
  meta_filter     jsonb default '{}'
) returns table (chunk_id text, section_id text, doc_id text, content text, metadata jsonb, similarity float)
language sql stable as $$
  select c.chunk_id, c.section_id, c.doc_id, c.content, c.metadata,
         1 - (c.embedding <=> query_embedding) as similarity
  from chunks c
  where (doc_ids is null or c.doc_id = any(doc_ids))
    and (law_as_of is null or coalesce(c.metadata->>'law_as_at', c.metadata->>'published')::date <= law_as_of)
    and c.metadata @> meta_filter
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

-- Evaluation: one row per (question, setup) run, the same shape eval/score.py reads.
create table if not exists eval_runs (
  id           bigint generated always as identity primary key,
  batch        text not null,                  -- e.g. "2026-11-03 first pass"
  question_id  text not null,
  setup        text not null,                  -- A | B | C-local | C-global | C-hybrid
  retrieved    text[] not null default '{}',   -- ranked section IDs
  answer       text,
  abstained    boolean not null default false,
  latency_ms   int,
  cost_usd     numeric(10,6),
  created_at   timestamptz not null default now()
);
create index if not exists eval_runs_batch on eval_runs (batch, setup);
alter table eval_runs enable row level security;

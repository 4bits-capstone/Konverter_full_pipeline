-- RAG storage: documents, chunks (with embeddings), cross-reference links, and match_chunks().
--
-- THIS FILE IS A TEMPLATE. The embedding size depends on the model you chose and is never
-- hard-coded: render it with
--     python -m app.rag sql            (uses RAG_EMBED_DIM from the environment)
--     python -m app.rag sql --dim <N>
-- and paste the output into the Supabase SQL editor. {{EMBEDDING_DIM}} appears in 4 places.
-- Changing the model to one with a different size later means: drop rag_chunks, render again
-- with the new size, re-ingest.
--
-- Idempotent (create ... if not exists / create or replace). Table names are prefixed rag_
-- because this project already has a `documents` table (001).

create extension if not exists vector;

-- One row per ingested document version.
create table if not exists rag_documents (
  doc_id          text not null,
  version         text not null default '',           -- '' = unversioned (reports, papers)
  doc_type        text not null,                      -- act | report | paper
  title           text,
  publisher       text,
  published       date,
  law_as_at       date,
  effective_from  date,
  effective_to    date,
  source_file     text,
  source_sha256   text,
  review_status   text not null default 'unreviewed', -- reviewed | unreviewed
  embedding_model text,
  embedding_dim   int,
  chunk_count     int,
  links_hash      text,
  updated_at      timestamptz not null default now(),
  primary key (doc_id, version)
);

-- One row per chunk. chunk_id: "act@038:s-77", "report:rec-2", "act@038:s-3#2" (part 2).
create table if not exists rag_chunks (
  chunk_id        text primary key,
  doc_id          text not null,
  version         text not null default '',
  doc_type        text not null,
  section_id      text not null,                      -- what citations and gold questions name: "act:s-77"
  heading_path    text[] not null default '{}',
  content         text not null,
  page_start      int,
  page_end        int,
  source_file     text,
  effective_from  date,                               -- in force from (inclusive)
  effective_to    date,                               -- in force until (exclusive); null = still in force
  content_hash    text not null,                      -- sha256 of heading path + text: what is embedded
  row_hash        text not null,                      -- sha256 of every non-embedding column
  metadata        jsonb not null default '{}',        -- title, publisher, review_status, contains, text_source, ...
  -- Nullable on purpose: a metadata-only update upserts a row without touching its embedding.
  embedding_model text,
  embedding_dim   int,
  embedding       vector({{EMBEDDING_DIM}}),
  updated_at      timestamptz not null default now()
);
create index if not exists rag_chunks_doc      on rag_chunks (doc_id, version);
create index if not exists rag_chunks_section  on rag_chunks (section_id);
create index if not exists rag_chunks_meta     on rag_chunks using gin (metadata jsonb_path_ops);

-- Approximate nearest-neighbour index, only where it is safe. match_chunks() filters by document and
-- date; before pgvector 0.8 a filtered HNSW scan can return fewer than k rows, so older servers use an
-- exact scan instead (fine at this size: about 1.4k chunks).
do $$
begin
  if string_to_array(split_part((select extversion from pg_extension where extname = 'vector'), '-', 1), '.')::int[]
       >= array[0, 8, 0] then
    create index if not exists rag_chunks_embedding on rag_chunks using hnsw (embedding vector_cosine_ops);
  else
    raise notice 'pgvector older than 0.8: no ANN index created; match_chunks() will scan exactly';
  end if;
end $$;

-- Cross-references extracted from the text (one hop at retrieval time).
create table if not exists rag_links (
  doc_id       text not null,                         -- the document the reference was found in
  version      text not null default '',
  from_section text not null,
  to_section   text not null,
  kind         text not null,                         -- refers_to | amends | responds_to
  evidence     text,
  primary key (doc_id, version, from_section, to_section, kind)
);
create index if not exists rag_links_from on rag_links (from_section);
create index if not exists rag_links_to   on rag_links (to_section);

-- match_chunks: filter by document / date / metadata first, then rank by cosine similarity.
--   k             rows to return
--   doc_ids       only these documents (null = all)
--   as_of_date    only chunks in force on that date: effective_from <= date and (effective_to is null or date < effective_to)
--   meta_filter   jsonb containment on rag_chunks.metadata, e.g. '{"review_status":"reviewed"}'
-- With pgvector >= 0.8, hnsw.iterative_scan keeps scanning until k filtered rows are found; older
-- servers have no such setting (the exception block ignores that) and have no ANN index either.
create or replace function match_chunks(
  query_embedding vector({{EMBEDDING_DIM}}),
  k               int     default 5,
  doc_ids         text[]  default null,
  as_of_date      date    default null,
  meta_filter     jsonb   default '{}'::jsonb
) returns table (
  chunk_id text, doc_id text, version text, doc_type text, section_id text, heading_path text[],
  content text, page_start int, page_end int, source_file text,
  effective_from date, effective_to date, metadata jsonb, similarity double precision
)
language plpgsql
as $$
begin
  begin
    perform set_config('hnsw.iterative_scan', 'relaxed_order', true);
  exception when others then
    null;   -- pgvector < 0.8
  end;
  return query
    with ranked as materialized (
      select c.chunk_id, c.doc_id, c.version, c.doc_type, c.section_id, c.heading_path,
             c.content, c.page_start, c.page_end, c.source_file,
             c.effective_from, c.effective_to, c.metadata,
             1 - (c.embedding <=> query_embedding) as similarity
      from rag_chunks c
      where c.embedding is not null
        and (doc_ids is null or c.doc_id = any(doc_ids))
        and (as_of_date is null
             or ((c.effective_from is null or c.effective_from <= as_of_date)
                 and (c.effective_to is null or as_of_date < c.effective_to)))
        and c.metadata @> coalesce(meta_filter, '{}'::jsonb)
      order by c.embedding <=> query_embedding
      limit greatest(k, 0)
    )
    select * from ranked order by ranked.similarity desc;   -- relaxed_order may return slightly unsorted rows
end;
$$;

-- Only the backend's service role (and n8n using that key) may read or write.
alter table rag_documents enable row level security;
alter table rag_chunks    enable row level security;
alter table rag_links     enable row level security;
revoke all on rag_documents, rag_chunks, rag_links from anon, authenticated;
revoke all on function match_chunks(vector({{EMBEDDING_DIM}}), int, text[], date, jsonb) from public, anon, authenticated;
grant execute on function match_chunks(vector({{EMBEDDING_DIM}}), int, text[], date, jsonb) to service_role;

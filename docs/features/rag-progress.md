# RAG extension: progress notes

Branch: `konverter-rag`. Running log of what was decided and built. Updated at the end of each phase.

## Brief in one paragraph

Extend Konverter into a RAG system: ingest -> chunk -> embed -> store -> retrieve -> answer with citations.
Traditional RAG with metadata filtering (no graph). Code in Python (tested, no network in tests);
question answering also runs in n8n. Embeddings behind one interface (default `voyage-law-2`, 1024 dims;
also OpenAI `text-embedding-3-small`). Generation by DeepSeek, JSON answer
`{answer, citations: [section_id], abstained}`, refusing with "not found in the provided documents".
Phases: 1 Plan, 2 Chunker, 3 SQL + embed + ingest, 4 Retrieval + answer + n8n Ask, 5 Eval + README.

## Decisions (approved at the end of Phase 1)

| # | Decision |
|---|---|
| Layout | Code in `backend/app/rag/`, tests in `backend/tests/rag/`, SQL as numbered migrations in `backend/sql/` (006 onward), n8n JSON in `rag/n8n/`, eval in `eval/`. Reason: CI only installs and tests `backend/`, and the repo already numbers its migrations. |
| Unreviewed docs | `ingest <folder>` converts headlessly and tags chunks `review_status`. `--from-store <id>` ingests approved documents. Production can filter with `meta_filter`; the benchmark includes unreviewed docs. |
| Dates | `effective_from` = explicit date, else `law_as_at`, else `published`. `effective_to` null unless given. A synthetic second Act version is used in the date-filter unit test; a real older version (v034) is added later for eval. |
| Footnotes | Not embedded in v1. |
| Fixtures | Trimmed `structured.json` excerpts only. PDFs and the CLME n8n template are not committed (`docs/rag-inputs/samples/` and the template are gitignored). |
| n8n ingest trigger | Out of scope this round. No Execute Command node. The CLI is enough; an authenticated backend route may come later. |
| Container | No new Dockerfile. Conversions run locally; the image ingests from stored `structured.json`. |
| Re-embed rule | Re-embed when `content_hash` OR the embedding model changes. |
| Abstain rule | Force abstain when the answer has no valid citations. |
| n8n base | `docs/rag-inputs/konverter-rag-ask.json`. Changes: Voyage and DeepSeek via Header Auth credentials, add the force-abstain rule, load the prompt from the shared prompt file (with a test that the two stay in sync). Keep its request/response shape; Python `ask` returns the same JSON. |
| Dependencies | None added so far. `httpx` and `supabase` are already dependencies. |

## What the converter produces (facts established in Phase 1)

- There is no markdown output. The outputs are `blocks.json`, `structured.json`, `accessible.html`, `schema.jsonld`
  (`backend/app/service.py`, `exporter.py`). The prototype `chunk.py` expected markdown, so the chunker reads `structured.json`.
- Kept: section ids, heading levels (H2-H5), page per block, tables, list markers, a paragraph `number` field
  (742 of 1,194 in the report), footnotes per section.
- Not kept: recommendation numbers as a field (the number is inside the text), effective dates and versions,
  footnote-to-paragraph links.
- `docs/rag-inputs/samples/` has only the three PDFs. The Act and the paper had never been converted before this work.

## Phase 2: built (commits `390bd55`, `820de9e`)

Files in `backend/app/rag/`:

- `models.py`: `DocumentInfo` (manifest entry), `Chunk` (with `embed_text` and `content_hash`), `Link`, `load_manifest`.
- `blocks.py`: flattens `structured.json` into typed lines (heading, para, item, table, caption) with page numbers.
- `chunking.py`: unit recognition, heading paths, splitting, de-duplication, warnings.
- `links.py`: cross-reference extraction.

Section IDs follow the benchmark: `act:s-N`, `act:schN-M` (schedule clause), `report:rec-N`, `report:para-X.Y`,
`paper:q-N`, `...:h-<slug>` for text before the first unit. `chunk_id` is `doc[@version]:sid[~n][#part]`
(for example `act@038:s-77`).

### Chunking rules

- Never merge units. Split long units (limit 2,500 chars) at subsection boundaries, then at line boundaries,
  then at sentences as a last resort. Every piece repeats the heading path (it is part of `embed_text`).
- Act: Part/Division/Subdivision/Schedule headings build the path. Section headings must keep climbing
  (a reset means a schedule or noise). A short paragraph shaped like a section heading is accepted too.
- Report: recommendations are detected inside the Recommendations chapter and must be sequential.
  Recommendations Docling laid out as a table (12-18) are rebuilt into items. Call-out copies in chapters
  are matched to the canonical recommendation and dropped as duplicates.
- Paper: a question is the "Question" label, then an `N text` item, plus its (a)/(b) sub-items. It closes at the first
  other line, so trailing footnotes and end matter do not leak in. The appendix copy of each question is dropped.
- Dropped: Act Table of Provisions, running page headers, everything from Endnotes, margin notes
  (kept in `metadata.history_notes`), call-out labels.
- Duplicate units with identical text (ignoring punctuation and a leading number) are dropped; different text keeps `~n`.

### Links

Regex extraction, fail closed. A target must exist in the known set. "section N" in the Act links only to the Act's own
sections (other statutes are skipped). In a report or paper it links only if the Cemeteries and Crematoria Act is named.
Report -> paper links (`responds_to`) need "Consultation Paper" nearby. Kinds so far: `refers_to`, `amends`, `responds_to`.

### Results on the real samples

| Document | Chunks | Units |
|---|---|---|
| Act v038 | 300 | 214 sections, 66 schedule clauses |
| Report | 836 | 25 recommendations, 742 numbered paragraphs, 60 heading units, 20 repeats dropped |
| Paper | 288 | 12 questions, 240 paragraphs, 10 repeats dropped |

All 20 gold section IDs in `questions.csv` exist as chunks. 121 links found across the corpus.
Backend suite: 401 tests pass (29 new RAG tests).

### Known gaps and limits

- Act sections 5, 7, 8, 29, 63, 83 have no heading in the converter output; their text sits in the previous section.
  Sections 181-185 appear repealed. The chunker warns instead of guessing.
- Docling flattens some Act subsections into one paragraph (s 77).
- Unnumbered paragraphs attach to the previous unit, so a stray footnote line can leak into a numbered paragraph.
- A "sections 135 to 141" range links only its two endpoints.
- The paper's appendix end matter still forms one stray `h-` chunk.
- The report was human-reviewed; the Act and paper were converted headlessly and are unreviewed.
- None of the gold cross-reference pairs (paper q-9 <-> rec-11/rec-6, q-11 <-> rec-24, q-12 <-> rec-25, rec-22 <-> s 77)
  has an explicit pointer in the converted text, so `--links` will not help those questions.

## Phase 2 follow-up (reviewer fixes)

- **Lost Act sections** (`chunking.py`, "recovering sections the converter lost"). Gaps in the section numbering are detected
  (including a `5A` with no `5` before it). Each missing section is first cut out of the converter's own atoms, using the PDF
  text layer (`pdftext.py`, pypdfium2) to find the heading and first body line. If that fails the affected span is rebuilt
  from the PDF text layer and tagged `metadata.text_source = "pdf-text-layer"`. If the PDF cannot resolve it either, every chunk of
  the preceding section carries `metadata.contains = ["act:s-4", "act:s-5"]`, so it is never cited as just s 4. Sections with no heading in
  the PDF either (181-185, repealed) are not invented. Without a PDF text layer (ingest from stored structured.json only) the
  preceding chunks are tagged `contains` conservatively. Found on the real Act: 5 recovered from converter atoms; 7, 8, 9, 12, 29, 40, 51,
  63, 83 rebuilt from the PDF. The earlier check had missed 9, 12, 40 and 51 because 9A, 12A, 40A and 51A exist. 16 chunks are PDF-sourced.
  Tests: `test_rag_recovery.py` (success, no-PDF, unrecoverable, repealed).
- **Paper end matter**: the stray `h-` chunk after the last appendix question is gone.
- **Q12 gold** (`docs/rag-inputs/questions.csv`): the report never cites s 77 in Recommendation 22. It cites it only in footnotes
  (fn 9 `s 77(1)(a)-(b)`, fn 10 `ss 77(1)(c)-(d)`, fn 12, fn 39) to paras 7.9, 7.10 and 7.33. Gold changed from `report:rec-22;act:s-77` to
  `report:para-7.9;act:s-77`; question text unchanged. Footnotes are not embedded in v1, so para 7.9 is found by topic, not by the "s 77" string.

## Phase 3: built

- `settings.py`: `RagSettings` from env (`RAG_EMBED_PROVIDER/MODEL/DIM/BATCH`, `RAG_CHUNK_MAX_CHARS`, `RAG_CACHE_DIR`, `VOYAGE_API_KEY`,
  `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`). Defaults live here only (voyage / voyage-law-2 / 1024). Secrets excluded from `repr`.
- `embeddings.py`: `Embedder` interface; `VoyageEmbedder`, `OpenAIEmbedder` (sends `dimensions` for the text-embedding-3 models), `HashEmbedder` (tests).
  Batching, retry with backoff on 429/5xx (honours Retry-After), errors carry status and a short message but never headers or keys. A response whose
  vector length differs from `RAG_EMBED_DIM` is an error.
- `store.py`: `SupabaseStore` over PostgREST (httpx; paging, merge-duplicates upserts, quoted deletes) and `MemoryStore` (same interface and
  the same `match_chunks` semantics as the SQL).
- `backend/sql/006_rag_chunks.sql`: template. Tables `rag_documents`, `rag_chunks`, `rag_links` (prefixed because 001 already has `documents`);
  `match_chunks(query_embedding, k, doc_ids, as_of_date, meta_filter)`; RLS on, grants to `service_role` only. The embedding size is the
  placeholder `{{EMBEDDING_DIM}}`, rendered by `python -m app.rag sql`. No provider or model names in SQL (a test enforces it).
  `effective_from` inclusive, `effective_to` exclusive.
- **pgvector version**: I cannot see the Supabase project (no credentials used), so the version is unchecked. The migration does not assume it:
  the HNSW index is created only if `pg_extension` says >= 0.8.0 (otherwise a notice and an exact scan), and `match_chunks` sets
  `hnsw.iterative_scan = relaxed_order` inside an exception block, so older servers simply ignore it. Check with
  `select extversion from pg_extension where extname = 'vector';`.
- `ingest.py`: planning (`plan_sync`) and `sync_document`. Re-embed when `content_hash` or the embedding fingerprint (provider:model:dim) changes;
  update rows whose other columns changed (`row_hash`) without touching the vector; delete vanished chunks last; links rewritten only when their hash
  changes. Sources: folder of PDFs plus manifest (uses `<stem>.structured.json` beside the PDF, else a sha256-keyed cache, else converts with the existing
  pipeline), `--from-store ID --as KEY`, `--from-structured FILE --as KEY [--pdf]`. Links resolve against the batch plus sections already stored.
- `cli.py` / `__main__.py`: `python -m app.rag sql [--dim N]`, `python -m app.rag ingest ...` (`--dry-run`, `--only`, `--reconvert`).
- `.env.example` has a RAG block.

### Results

Local end-to-end with `MemoryStore` and the fake embedder on the three real converted documents: 836 report + 287 paper + 308 Act chunks = 1,431
chunks; all 20 gold sections present; second run embeds 0 and writes 0. Links: 4 paper, 137 Act, 0 report. Backend suite: 475 passed, 1 skipped.

### Not verified (be aware)

- The SQL has not been executed: this machine has Postgres 14 but no pgvector. `test_match_chunks_in_a_real_postgres` is skipped unless
  `RAG_TEST_DATABASE_URL` points at a scratch Postgres with pgvector (it creates the rag_* tables, asserts that a `doc_ids`-filtered query returns k rows,
  and checks the date window). The filtered-k and date-window behaviour is tested against `MemoryStore`, which mirrors the SQL.
- The Voyage and OpenAI request shapes are tested against mocked transports, not live APIs.
- Links are computed against sections known at ingest time. After adding a document later, re-run ingest over all documents (it embeds nothing) to refresh cross-document links.

## Open questions

None blocking.

### Known limit: margin notes in converter-sourced Act chunks

The 16 PDF-rebuilt sections have their margin history notes stripped (they wrap over several lines in the text layer; the removed notes are kept in
`metadata.history_notes`). About 8 converter-sourced Act chunks (s-3, s-5, s-18B, s-43, s-84A, sch1-2) still contain fragments of such notes, mostly in
odd shapes inside tables. They are noise, not enacted text. Not fixed.

## Next: Phase 4

Python `ask` (retrieve with filters and the optional one-hop `--links`, build prompt, DeepSeek call, JSON validation, force-abstain rules),
shared prompt file, n8n Ask workflow adapted from `konverter-rag-ask.json`, tests with mocked embeddings and LLM.

## Phase 5 notes

- Add a "parent section" retrieval option as an eval setting: retrieve a paragraph, send its whole section to the LLM (median chunk is ~330 characters).
- Curated links must never be derived from `questions.csv`; any future links need an independent source.
- **Experiment: links from report footnotes.** The report body has 0 Act links, but its footnotes cite sections (fn 9 "Cemeteries and Crematoria Act 2003 (Vic)
  s 77(1)(a)-(b)" -> `act:s-77`). Extract them from the footnote text in `structured.json` (`sections[].footnotes`), resolve them with the existing rule (the
  Act must be named; the target must exist) and attach each link to the paragraph or section the footnote belongs to. The source is the document's own text,
  not `questions.csv`, so it is allowed under the curated-links rule. This is the only way `--links` can help cross-document questions such as Q12. Open
  detail: the converter does not record which paragraph a footnote is attached to; the marker numbers in the text are the only clue (footnote ids look like
  `footnote-9-7`: number 9, page/chapter 7). Evaluate with and without. Q12 is marked `footnote-dependent` in the `notes` column so the report can group it.

## Test fixtures

`backend/tests/rag/fixtures/` holds trimmed real converter output (and PDF text-layer pages for the recovery tests); how it was cut is in `backend/tests/rag/README.md`.

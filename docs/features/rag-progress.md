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
- **Q12 gold** (`eval/questions.csv`, moved from `docs/rag-inputs/`): the report never cites s 77 in Recommendation 22. It cites it only in footnotes
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

## Phase 4: retrieval, ask, eval, n8n (done, for review)

pgvector 0.8 test (`test_rag_sql.py`, 11 tests including the real-Postgres one) passed on `pgvector/pgvector:pg16` before this started.

- `retrieve.py`: embeds the question as a *query*, calls `match_chunks(k, doc_ids, as_of_date, meta_filter)`. With `links=True`, calls
  `expand_links` for the sections found and appends up to 3 linked sections after the vector results (one hop, both directions, never one already retrieved);
  they carry `via_link` and no similarity.
- **`expand_links` SQL** (new in `006_rag_chunks.sql`): applies the same doc / date / metadata filters as `match_chunks` in one place, so a linked section cannot
  leak in from a version that is not in force; picks the newest version that passes the filters; orders by the rank of the seed result, outgoing before incoming.
  Mirrored by `MemoryStore.expand_links`. **The real-Postgres test was extended (seven `expand_links` assertions); it has not been run: please rerun it.**
- `ask.py`, `answer.py`: `ask()` = retrieve + `answer_question`. Link rows bypass the similarity floor (they have no score). The result adds `ranked`
  (pre-floor) next to `retrieved`/`scores` (what the model saw).
- `evalrun.py`: `python -m app.rag eval` writes one JSON line per question: `question_id, setup, category, retrieved[]` (ranked sections BEFORE the floor, what
  score.py reads), `used[]` (what the model saw), `answer, citations, abstained, abstain_reason, latency_ms, top_similarity` (for calibrating the floor).
  `eval/questions.csv` and `eval/score.py` were moved from `docs/rag-inputs/` unchanged apart from Q12. Scoring tables, floor calibration and the README are Phase 5.
- `cli.py`: `ask "<q>" [--doc ID[,ID]] [--as-of YYYY-MM-DD] [--links] [-k N] [--meta K=V] [--json]` (prints the answer, citations and every retrieved chunk,
  marking those below the floor), `eval ...`, `n8n-export`.
- **n8n** (`rag/n8n/`): template + generated export + README. Changes from the base workflow: RPC parameters `k` / `as_of_date` (and optional `meta_filter` in the
  request); chunk columns (`heading_path`, `version`, pages) instead of `metadata.*`; Voyage and DeepSeek on Header Auth credentials, Supabase on its credential, all
  as `REPLACE_ME` placeholders; embedding provider/model/dimension in the Config node (voyage or openai); force-abstain on no valid citation; `contains` handling;
  `abstain_reason` and `ranked` in the response; system prompt generated from `prompts/answer_system.txt` by `python -m app.rag n8n-export`.
- **Sync tests** (`test_rag_n8n.py`): the committed export equals the generator's output; its prompt equals the shared file; `match_chunks` is called with exactly the SQL
  function's parameter names (and the Python store sends the same names, also for `expand_links`); no `$env`, no keys; Config defaults equal the Python defaults. With `node`
  installed (it is on GitHub's runners) the workflow's own Build prompt / Parse answer / Not found / Normalise request code is executed on the same inputs as the Python
  and compared: identical prompts, and identical answers for 11 model outputs (valid, invented citations, `contains`, forced abstain, model abstain, code fences, junk).
- n8n has no link expansion; its `retrieved` is Python's `retrieved`. Its retrieval equals `ask` without `--links`.

Not verified: the workflow has not been imported into a running n8n (node versions and credential wiring are the likely snags), and nothing has been run against live Voyage,
DeepSeek or Supabase.

## Ingest resilience (after the first real run failed with a Supabase WriteTimeout)

Cause: `ingest` embedded every chunk first and wrote afterwards, and each upsert request carried 100 rows of 1024 floats written with 17 digits (about
2 MB) against a flat 60 s timeout with no retry. A late failure threw away all the embedding spend.

- **Write as you go**: each embedding batch is upserted as soon as it is embedded. On the next run those chunks are "unchanged" (same `content_hash`, same model,
  same `row_hash`) and are neither embedded nor paid for again. A failure reports how many new chunks were stored and says to re-run the same command.
- **Delete last**: chunks of vanished sections are removed only after every embedding, chunk write and links write has succeeded; the document row is written after that.
  Tests fail the embedder (429) and the store (timeout, links write) in the middle and check nothing is deleted until a clean run.
- **Store**: explicit `httpx.Timeout(connect 10 s, read/write RAG_DB_TIMEOUT, pool 10 s)`; retries with backoff (2, 4, 8 ... capped at 60 s, Retry-After honoured)
  on timeouts, connection errors, 408/429/5xx and Cloudflare 52x; 4xx are not retried. Batch size `RAG_DB_BATCH` (default 50). Link inserts are now upserts so a
  repeated request cannot fail on the primary key. Vectors are sent with 8 significant digits (float32 round-trips), about half the bytes.
- **Voyage/OpenAI**: batches are cut by count (`RAG_EMBED_BATCH`) and estimated tokens (`RAG_EMBED_BATCH_TOKENS`, 3 characters per token, deliberately generous; an oversize text
  goes alone). Up to `RAG_EMBED_MAX_RETRIES` (8) attempts: Retry-After if the server sends it (capped at 5 minutes), else 5, 10, 20, 40, 60 s after a 429 and 2, 4, 8 ... after
  other errors. Timeouts and connection resets are retried too. The provider's token count is accumulated in `embedder.tokens`.
- Each batch logs `embedded and stored batch i/n`.

## Decisions on links and eval (after Phase 3 review)

- **History notes are never read as links.** Margin notes such as "S. 6A inserted by No. 61/2009 s. 9." cite sections of the AMENDING Act. `links.py`
  strips them (whole notes, and any `No. N/YYYY s. ...` citation tail, including the fragments still left in ~8 converter-sourced chunks and notes wrapped
  over several lines) before looking for "section N"; `metadata.history_notes` and `metadata.contains` are never read. Tests: the exact example gives no link
  to `act:s-9`, seven shapes of note give none, genuine references next to a note are still linked, and no real-Act link has an amending-act citation as evidence.
  The Act's link count is unchanged (137), so nothing legitimate was lost.
- **Eval metrics are measured in two places.**
  1. *Retrieval* (recall@k, hit@k, MRR) is measured BEFORE the similarity floor, on the ranked `match_chunks` results, because that is what compares setups
     (plain vector, filters, `--links`, parent-section). `answer_question` returns it as `ranked` (chunk, section, similarity, pre-floor); the eval's
     `retrieved[]` is `ranked_sections(result)`. `retrieved` / `scores` in the answer JSON stay what the model saw (after the floor), as in the n8n workflow.
  2. *End to end* is reported AFTER the floor: answered correctly (answerable questions) and correctly abstained (unanswerable).
  3. The floor (`RAG_MIN_SIMILARITY`, default 0.3, a placeholder) is calibrated separately, on the unanswerable questions (Q15, Q16) and with a check that it
     does not suppress answerable ones. It is not tuned against retrieval recall. Report the similarity of the top hit for each unanswerable question.

## Footnote-links experiment: feasibility check (not built)

Question: does paragraph text keep footnote reference numbers? **Yes.** Para 7.9 reads "...a right of interment.8 What is actually purchased ... memorial at the
plot. 9 In addition ... from the plot, 10 or endorse ... to exhume a body. 11" and 7.10 ends "...memorialisation.13". Numbers restart in each chapter. So footnotes
can be mapped to paragraphs by number within the chapter; they are not tied to a sentence, only to the paragraph that contains the reference.

Details that matter when building it:

- The footnote's number is the leading digits of its text ("10 Cemeteries and Crematoria Act ..."), not the id (`footnote-10-7`): ids and text numbers
  disagree in some chapters, and about 10% of footnotes (for example `footnote-9-7`, the s 77 one) have no leading number, so the id number is the fallback.
- The converter loses some footnotes: chapter 6 has 210 footnote entries but numbers up to 236 (about 26 missing, with gaps such as 5, 14, 37).
- A strict "next number follows the previous" scan matched 503 of 693 footnotes (73%): 90% or more in 7 of 9 chapters, but only 51 of 210 in chapter 6, where
  one missing footnote desynchronises the scan. A per-number lookup within the chapter (the number must follow a letter or punctuation, and match in increasing
  paragraph order) is the right design: every one of the 172 distinct chapter-6 numbers has an inline reference somewhere in the chapter.
- False hits ("aged 18 years" for footnote 18) are limited by requiring monotonic paragraph order and the number to follow a word or punctuation directly.
- Decision for the experiment: map at paragraph level where the number resolves uniquely; attach to the section (chapter heading unit) where it does not.

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

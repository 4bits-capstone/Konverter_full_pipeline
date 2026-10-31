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

## Open questions

1. Add a curated `links.csv` for the cross-document gold pairs? (Default: no.)
2. HNSW cosine index (default) or IVFFlat?

## Next: Phase 3

SQL migrations with a `{{EMBEDDING_DIM}}` placeholder rendered by `python -m app.rag sql`; `Embedder` interface (Voyage, OpenAI);
Supabase store over PostgREST; idempotent ingest (skip unchanged, re-embed on hash or model change, delete vanished sections);
CLI `ingest`, with a conversion cache keyed by PDF sha256.

## Test fixtures

`backend/tests/rag/fixtures/` holds trimmed real converter output; how it was cut is in `backend/tests/rag/README.md`.

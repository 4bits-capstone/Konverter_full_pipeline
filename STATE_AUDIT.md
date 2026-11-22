# State audit

Inventory of this tree on 22 Nov 2026, branch `Fix/repo-audit-fix` (`62082ee`). No source files were changed to produce it. `git log -n 30 --stat` is mostly finished work: footnote and rich-text review (8–22 Nov), then a RAG CLI (31 Oct). The latest commit only adds `ARCHITECTURE.md`.

On this machine, earlier the same day: `npm test` 138 passed, `npm run lint` and `npm run build` passed, `pytest` in `backend/` 627 passed and 1 skipped. Those commands were not re-run for this file. There is no failing suite in that run. The gaps below are missing coverage, dead leftovers, and failures that the code swallows.

## 1. Working and wired features

| Flow | Path | Persistence |
| --- | --- | --- |
| Sign in and list own documents | `src/components/AuthGate.tsx` → `src/lib/supabaseClient.ts` → `src/services/fastApi.ts` `listDocuments` → `GET /api/documents` in `backend/app/main.py` → `backend/app/auth.py` | Supabase Auth session in the browser. Document list is `record.json` files via `backend/app/storage.py`. |
| Upload PDF | `src/pages/UploadPage.tsx` → `POST /api/documents` | `source.pdf` and `record.json`. `backend/app/audit.py` upserts Supabase `documents` and inserts `audit_log`. |
| Process | `src/state/KonverterContext.tsx` `startProcessing` → `POST /api/documents/{id}/process` → `ProcessingManager` in `backend/app/service.py` → `KonverterPipeline.process` in `backend/app/pipeline.py` → `docling_runner.py` | `blocks.json`, `review_items.json`, `metadata.json`, `docling.json`, `doc_confidence.json`, `warnings.json`. UI polls `POST .../processing-state`. |
| Review edits, including bold/italic | `src/pages/ReviewPage.tsx`, `src/components/StyledTextEditor.tsx`, `src/lib/richText.ts` → `PATCH /api/documents/{id}/review-items/{item}` → `WorkflowService` | `review_items.json` and `blocks.json`. Generated HTML/JSON is deleted so an old export cannot linger. Tests: `src/pages/ReviewPage.test.tsx`, `backend/tests/test_footnote_style_edit.py`, `backend/tests/test_text_style_export.py`. `src/lib/footnoteMarkup.ts` was removed in `6572414` and replaced by `richText.ts`. |
| Metadata, approve, preview | `src/pages/MetadataPage.tsx`, `src/pages/PreviewPage.tsx` → `PUT .../metadata`, `POST .../approval` → `exporter.py` `build_publication` and `preview_html.py` `build_accessible_html` | `metadata.json`, then `publication.json`, `schema.jsonld`, `structured.json`, `accessible.html`, `approved_at` on the record. |
| WordPress publish | `src/components/WordPressPublishControl.tsx` → `src/services/fastApi.ts` `publishToWordPress` → `backend/app/wordpress.py` and `wordpress_registry.py` | Local `wordpress-publication.json` plus Supabase `wordpress_publications` (`backend/sql/004_wordpress_publications.sql`). |
| In-app chat and TTS | `src/components/DocumentChat.tsx` → `POST /api/documents/{id}/chat` and `POST /api/tts` → `backend/app/chat.py` | No transcript store. Context is the current review artifacts, or the approved export after approval. OpenAI is called only when `OPENAI_API_KEY` is set. |
| Public widget chat | `src/widget/embed.ts` built to `backend/app/static/widget/konverter-chat-widget.js` → `POST /api/public/documents/{id}/chat` | Approved `structured.json` and `schema.jsonld` only. Rate limits in `backend/app/rate_limit.py`. |
| Admin audit log | `src/pages/AuditLogPage.tsx` → `GET /api/audit-log` with `require_admin` | Supabase `audit_log`, hash-chained by `backend/sql/002_audit_log_hash_chain.sql`. |
| RAG ask / ingest | `python -m app.rag` (`backend/app/rag/cli.py`, `ingest.py`, `retrieve.py`, `answer.py`) and `rag/n8n/konverter-rag-ask.json` | Supabase `rag_documents`, `rag_chunks`, `rag_links` from rendered `backend/sql/006_rag_chunks.sql`. Not mounted on FastAPI. Parity tests live in `backend/tests/rag/`. |

`/approval` and `/export` in `src/ConverterApp.tsx` redirect to `/metadata` and `/preview`. The landing-page ask box in `src/pages/LandingPage.tsx` is a local FAQ timer. It does not call the document chat API, and the page copy says so.

## 2. Half-finished and disconnected code

| Item | Evidence | What is missing |
| --- | --- | --- |
| Key recommendations | `preview_html._recommendation_snippets` is defined and never called. Tests in `backend/tests/test_exporter_updates.py` assert the class `key-recommendations` is absent. CSS for it remains in `preview_html.py`, `src/styles/converter.css`, `src/styles/preview.css`, and `backend/app/static/report/report.css`. `docs/FIXME.md` says the section was removed on purpose. | The feature is gone. The helper and CSS are not. |
| Supabase `documents.status` | `audit.record_document` always writes `status: "uploaded"` (`backend/app/audit.py`). No later call updates it. | The column does not track processing, review, or approval. `record.json` does. |
| Figure and cover embedding | `preview_html._data_uri` still base64-inlines images into `accessible.html`. | A 1 Sep stash switched those to sibling files. That change is not in the live renderer. |
| Old RAG prototype | `docs/rag-inputs/chunk.py` documents `python3 pipeline/chunk.py` and `data/chunks.jsonl`. `docs/rag-inputs/schema.sql` creates `chunks.embedding vector(1536)`. Neither is imported. The live schema is `006_rag_chunks.sql`, rendered for `RAG_EMBED_DIM`. | Two schemas for the same idea. Applying `schema.sql` would not match the CLI. |
| Old n8n copy | `docs/features/rag-progress.md` still points at `docs/rag-inputs/konverter-rag-ask.json`. The CLI and tests use `rag/n8n/`. | The docs copy is not the file `n8n-export` regenerates. |
| Local Docker Compose | `docker-compose.yml` comments out the backend service and falls back to `https://jxklmut6ta4ya8-8000.proxy.runpod.net/api`. | `docker compose up` does not run the API in this repo. |
| Confidence threshold | `docs/FIXME.md` still says 0.60 has no decided target. `KONVERTER_MEDIUM_CONFIDENCE` defaults to 0.60 in `backend/app/config.py`. | Product decision, not a stub route. |
| `NotImplementedError` | `backend/app/rag/embeddings.py` `_payload` on the base embedder. | Abstract method. `Voyage` and `OpenAI` subclasses implement it. Not a stub route. |

No FastAPI handler returns a placeholder body. Auth, upload, process, review, metadata, approve, WordPress, and chat all call a real function.

## 3. Dead code and duplication

| Item | Evidence |
| --- | --- |
| Unused recommendation extractor | `preview_html._recommendation_snippets` has no callers. |
| Copied slug helpers | `_slug` and `_project_slug` exist in both `backend/app/exporter.py` and `backend/app/preview_html.py`. The exporter lowercases and falls back to `"section"`. The HTML renderer uses `casefold()` and falls back to `"publication"`. |
| Copied date parsing | `preview_html._parse_published_date` / `_format_published_date` and `src/lib/publicationFormatting.ts` both turn a publication date into display text. |
| Superseded RAG scripts | `docs/rag-inputs/chunk.py`, `docs/rag-inputs/schema.sql`, `docs/rag-inputs/documents.json`, `docs/rag-inputs/konverter-rag-ask.json`. The live code is `backend/app/rag/` and `rag/n8n/`. |
| Git stashes, not in the tree | `stash@{0}` on `86bf9d8` (8 Sep, 20 files, +2618/−876). `stash@{1}` on `766bbec` (1 Sep, landing page, chat refs, Vite dev-tunnel host, relative image URLs, ~929 lines of `public.css`). Both parents are ancestors of `HEAD`. Neither patch applies or reverses cleanly. Landing-page routing and the chat refs are already in the current files. |

`footnoteMarkup.ts` is not an orphan. Commit `6572414` deleted it. Nothing in `src/` or `backend/app/` imports it.

## 4. Broken and untested critical paths

The typecheck and both test suites passed in the baseline run. This table is what that run does not protect.

| Path | What happens | Test gap |
| --- | --- | --- |
| Chat and TTS upstream errors | `backend/app/main.py` starts `StreamingResponse` with status 200, then the generator catches `OpenAIRequestError`, logs it, and stops. The client has already been told the call succeeded. | `backend/tests/test_chat.py` covers 503 when the key is missing, and rate limits. It does not cover a provider failure after the stream has started. |
| Audit and WordPress duplicate guard | `audit._post` logs and returns on any Supabase error. Without `SUPABASE_SERVICE_ROLE_KEY`, a second WordPress publish is not blocked. | `backend/tests/test_security.py` expects the unconfigured case to skip, not to fail the request. |
| Remote Docling | `pipeline.py` calls `storage_bucket.py` and `runpod_client.py` only when `KONVERTER_DOCLING_MODE=remote`. | `backend/tests/test_runpod_client.py` covers the client. `storage_bucket.py` has no direct test. |
| RAG against a real database | `tests/rag/test_rag_sql.py` `test_match_chunks_in_a_real_postgres` skips unless `RAG_TEST_DATABASE_URL` and `psql` are set. That was the one skip in the baseline run. | The rendered SQL is unit-tested. Applying it to Postgres is not. |
| Upload, history, sign-in, rich-text editor UI | Server upload rules are tested via `backend/tests/test_api.py`. | No test file for `src/pages/UploadPage.tsx`, `src/pages/HistoryPage.tsx`, `src/pages/LandingPage.tsx`, `src/components/AuthGate.tsx`, or `src/components/StyledTextEditor.tsx`. `ReportPage` is only mounted as a route inside `src/pages/PreviewPage.test.tsx`. |
| Render crash | `src/main.tsx` has `Suspense` and no React error boundary. | A throw in a stage page unmounts the tree. No test covers that. |
| Rate limits and token cache | `auth.py` caches a bearer token for 5 seconds. `rate_limit.py` keeps counters in the process. Both reset on restart and are not shared by a second process. | `test_chat.py` covers a single process. |
| Slug drift | The two `_slug` copies can emit different ids for the same title. | No test compares exporter ids with preview HTML ids. |

Upload validation itself is present: extension, `%PDF-` magic, 200 MB, page count, and `KONVERTER_MAX_PAGES`, mapped to 400, 413, 415, and 422. `httpClient.ts` maps those statuses to `ApiError`.

## Cleanup order

1. Leave the two git stashes unapplied. Confirm anything still wanted from them (the relative image URLs are the only behavior not already in `HEAD`), then drop them. Do not run `docs/rag-inputs/schema.sql`.
2. Delete the unused recommendation helper and its CSS, and delete or clearly archive `docs/rag-inputs/chunk.py`, `schema.sql`, and the old n8n JSON so the live RAG path is only `backend/app/rag` plus `rag/n8n`.
3. Make one slug helper and one publication-date helper, and use them from both the exporter and the preview. The current copies already disagree.
4. Stop hiding failures on the paths a reviewer trusts: surface an OpenAI error on chat and TTS instead of ending a 200 stream, and decide whether a missed audit write or a missed WordPress duplicate check should fail the request. Either update `documents.status` through the workflow or stop treating that column as state.
5. Add tests for sign-in, upload, and the rich-text editor, plus one test that exporter ids and preview HTML ids stay the same. Leave the 0.60 confidence default in place until someone picks a replacement. `docs/FIXME.md` is still waiting on that decision.

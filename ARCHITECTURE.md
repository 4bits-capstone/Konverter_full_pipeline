# Architecture

Konverter turns PDF reports into accessible HTML and JSON-LD through a human review workflow: upload, Docling parse, review flagged items, edit metadata, approve, preview or export, and optionally publish a draft or live page to WordPress. There is no GraphQL API and no cron scheduler in this repository.

## 1. System overview and tech stack

| Layer | Choice |
| --- | --- |
| Frontend | React 19, TypeScript, Vite 6, React Router 7, TanStack Query, Zod, react-hook-form. Tailwind 4 is a Vite plugin. Tests are Vitest + Testing Library. |
| Backend | FastAPI 0.2.0 (`backend/app/main.py`), Pydantic v2, Uvicorn. Python `>=3.11,<3.14`. CI pins 3.12. |
| PDF parse | Docling, in-process when `KONVERTER_DOCLING_MODE=local` (default), or a separate RunPod serverless GPU worker (`docling_worker/`) when `remote`. |
| Document store | Files on disk. Default directory is `backend/runtime/` (`KONVERTER_DATA_DIR`). Not a database. |
| Postgres | Supabase Postgres, used only for auth users, an audit log, a WordPress publication registry, a thin `documents` mirror, and the optional RAG corpus (pgvector). |
| Auth | Supabase Auth. The browser uses the anon key. The API checks the bearer token against `GET {SUPABASE_URL}/auth/v1/user`. |
| Other services | OpenAI (document chat and TTS), optional Anthropic (`CLAUDE_API_KEY`, diagram grouping only), WordPress Nam Builder, Voyage or OpenAI embeddings plus DeepSeek for the RAG CLI, n8n workflow JSON under `rag/n8n/`. |
| Build and CI | npm scripts; Hatchling for the Python package; hash-locked `backend/requirements.lock` and `backend/requirements-dev.lock`. GitHub Actions (`.github/workflows/ci.yml`) tests, builds images, and on `main` publishes the backend to Docker Hub / RunPod and the frontend to GHCR / Lightsail. |

Frontend production build: `tsc -b && vite build`. The chat widget is a separate esbuild bundle (`npm run build:widget`) and is not part of `npm run build`. `npm run lint` is `tsc --noEmit`. There is no ESLint, Ruff, or mypy config, and no Makefile.

## 2. Directory map

| Path | Role |
| --- | --- |
| `src/` | Reviewer UI. Routes in `ConverterApp.tsx`. API access only through `src/services/` (`contracts.ts`, `fastApi.ts`, `httpClient.ts`). Stage unlock state in `src/state/KonverterContext.tsx`. |
| `src/widget/embed.ts` | Dependency-free chat widget embedded in exported HTML. |
| `backend/app/` | API, pipeline, export, auth, audit, chat, WordPress. This is the core business logic. |
| `backend/app/pipeline.py` | Long chain of heuristic passes over Docling JSON (furniture, footnotes, pictures, columns, captions). Helpers: `visual_structure.py`, `toc_hierarchy.py`, `metadata_rules.py`, `footnote_numbering.py`, `text_styles.py`. |
| `backend/app/service.py` | `ProcessingManager` (thread pool) and `WorkflowService` (review edits, metadata, approve/revoke). |
| `backend/app/exporter.py`, `preview_html.py` | Publication payload and accessible HTML. |
| `backend/app/rag/` | Separate CLI (`python -m app.rag`) for chunk, embed, retrieve, and answer. Not mounted on the FastAPI app. |
| `backend/sql/` | Supabase SQL, applied by hand in the SQL editor. See `backend/sql/README.md`. |
| `backend/tests/` | Pytest. Pipeline tests build small synthetic Docling dicts. |
| `docling_worker/` | GPU worker image. Copies `docling_runner.py`, which must stay free of `backend.app` imports. |
| `deploy/` | nginx template, Lightsail deploy script, backend container entrypoint. |
| `rag/n8n/` | Exported n8n "ask" workflow. |
| `eval/` | RAG question CSV and `score.py`. |
| `docs/` | Ops handover, audits, feature notes. Not loaded by the app. |
| `public/` | Static assets (logo). |

Boilerplate and tooling sit at the root: `package.json`, `vite.config.ts`, `vitest.config.ts`, `tsconfig*.json`, `index.html`, Dockerfiles, `docker-compose.yml`, `.github/`. `dist/` and `backend/runtime/` are generated and gitignored.

## 3. Data model and state

**Document content is files, one directory per id** under `{data_dir}/documents/<id>/` (`LocalDocumentStore` in `backend/app/storage.py`). Ids are `uuid4().hex`. A process-wide `RLock` guards reads and writes. Typical files:

- `source.pdf`, `record.json` (title, owner, page count, job state, `approved_at`, `metadata_confirmed`)
- `docling.json`, `blocks.json`, `review_items.json`, `metadata.json`, `doc_confidence.json`
- `publication.json`, `schema.jsonld`, `structured.json`, `accessible.html` (written on approve)
- `cover.png`, `figure-*.png`, evidence PNGs, `uploads/` for reviewer-supplied images
- `wordpress-publication.json` (local cache; discarded when generated artifacts are discarded)
- `{data_dir}/processing_metrics.json` for runtime estimates

Review edits update `review_items.json` and `blocks.json` and delete generated publication files, so an approved export cannot drift from the review queue. Approval runs the exporter and sets `approved_at`.

**Supabase tables** (service role only; RLS in `005_enable_rls.sql`):

| Table | SQL | What the app uses it for |
| --- | --- | --- |
| `documents` | `001_documents_and_audit_log.sql` | FK target only. `audit.record_document` upserts `id`, `filename`, `uploaded_by`, `status`. The comment in `audit.py` states this is not the document store. |
| `audit_log` | `001`, hash chain in `002`, insert-only in `003` | Append-only actions (`upload`, `edit`, `approve`, and others). `prev_hash` / `entry_hash` are filled by a trigger. `verify_audit_log_chain.sql` is a read-only check. |
| `wordpress_publications` | `004` | Durable record of each successful WordPress create, so a second publish can warn. `document_id` is text, not a UUID FK. |
| `rag_documents`, `rag_chunks`, `rag_links` | `006_rag_chunks.sql` is a template | Render with `python -m app.rag sql` so `vector({{EMBEDDING_DIM}})` matches `RAG_EMBED_DIM`. HNSW is optional (`python -m app.rag index`). |

**Caches, all in-process:**

- Validated Supabase tokens, 5 seconds (`backend/app/auth.py`).
- Public chat and TTS sliding windows (`backend/app/rate_limit.py`). A limit of 0 disables a window. Counters reset on restart and are not shared across processes.
- Docling converter instances (`docling_runner.py`), one per `(ocr, table structure, device)`.
- TanStack Query on the client, `staleTime` 30 seconds (`src/main.tsx`).
- Stage unlock flags in React context, not on the server.

If `SUPABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` is missing, audit writes and the WordPress duplicate guard are skipped and logged. They do not fail the user action.

## 4. Entry points and boundaries

**HTTP.** FastAPI app in `backend/app/main.py`. CORS from `KONVERTER_CORS_ORIGINS`. An HTTP middleware sets `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy`. `/docs`, `/redoc`, and `/openapi.json` exist only when `KONVERTER_API_DOCS` is true. `/static` serves the chat widget.

Auth dependencies: `get_current_user` (401), `require_admin` (403 unless `app_metadata.role == "admin"`), `get_current_user_optional` (anonymous only when no `Authorization` header is sent; a bad token is still 401). Owner checks compare `record.uploaded_by` to the Supabase user id. Admins see every document only through the admin list endpoints.

| Auth | Routes |
| --- | --- |
| None | `GET /api/health`. `GET /api/documents/{id}/exports/accessible.html`, `schema.jsonld`, and `structured.json` once `approved_at` is set (409 otherwise). `POST /api/public/documents/{id}/chat` for an approved document, rate-limited per IP and globally. |
| Optional user | `GET .../source`, `.../figures/{image_key}.png`, `.../cover`. Anonymous callers are allowed only when the document is approved; otherwise the owner is required. |
| Signed-in owner | Upload (`POST /api/documents`, max 5 PDFs, 200 MB each), list own documents, process / stop / status, review-item read and patch, metadata, approve and revoke, publication payload, WordPress publish, raw `docling.json`, authenticated chat, TTS. |
| Admin | `GET /api/documents/all`, `GET /api/audit-log`, `GET /api/audit-log/count`. `GET /api/audit-log/mine` is any signed-in user. |

**Background work.** `ProcessingManager` uses a `ThreadPoolExecutor` of size `KONVERTER_WORKERS` (default 1). `POST .../process` submits `KonverterPipeline.process`. Startup calls `recover_interrupted_jobs()`, which marks leftover `"running"` jobs as failed. That recovery assumes one server process per data directory. There is no separate queue and no cron.

**Remote parse.** `docling_runner.py` either converts locally or, in remote mode, uploads the PDF through Supabase Storage (`storage_bucket.py`) and polls RunPod (`runpod_client.py`). `diagram_vlm.py` may call Claude to group text Docling already extracted. It does not replace document text, and a failure falls through to human review.

**RAG and n8n** are offline tools: `python -m app.rag` commands `sql`, `ingest`, `ask`, `index`, `n8n-export`, `eval`.

**Browser.** `src/main.tsx` mounts the router and `KonverterProvider`. `AuthGate` shows `LandingPage` at `/` when signed out, a password form on every other path, and the app once Supabase has a session. `httpClient.ts` attaches the access token. Routes in `ConverterApp.tsx`: `/upload`, `/review`, `/metadata`, `/preview` (review, metadata, and preview sit behind `ProtectedStage`), `/history`, `/report/:documentId`, and admin `/admin/overview`, `/admin/documents`, `/admin/audit-log` behind `RequireAdmin`. `/approval` and `/export` redirect. There is no React error boundary.

## 5. Local development and operations

Requirements: Node 20+ (CI uses 20), Python 3.11–3.13. From the repo root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "./backend[docling,dev]"
npm ci
cp .env.example .env
```

CI installs the hash-locked file instead: `pip install --require-hashes -r backend/requirements-dev.lock` then `pip install --no-deps -e ./backend`.

```bash
uvicorn app.main:app --app-dir backend --env-file .env   # API :8000
npm run dev                                              # UI :5173
npm test                                                 # vitest run
npm run lint                                             # tsc --noEmit
npm run build                                            # tsc -b && vite build
npm run build:widget                                     # widget JS; CI fails if the committed file differs
pytest backend                                           # or: cd backend && python -m pytest
```

`config.py` reloads the root `.env` with `override=True` unless pytest is already imported, so tests do not read a developer `.env`.

**Env vars** (names only; see `.env.example`):

- UI: `VITE_API_BASE_URL`, `VITE_API_TIMEOUT_MS`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`. The image publish job refuses to run if the API URL and both Supabase vars are empty.
- API auth and data: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `KONVERTER_DATA_DIR`, `KONVERTER_CORS_ORIGINS`, `KONVERTER_API_DOCS`, `KONVERTER_LOG_LEVEL`.
- Parse: `KONVERTER_DO_OCR`, `KONVERTER_DO_TABLE_STRUCTURE`, `KONVERTER_DOCLING_DEVICE`, `KONVERTER_DOCLING_MODE`, `KONVERTER_DOCLING_ENDPOINT_URL`, `KONVERTER_RUNPOD_API_KEY`, `KONVERTER_STORAGE_BUCKET`, `KONVERTER_SIGNED_URL_TTL`, `KONVERTER_RUNPOD_JOB_TIMEOUT_SECONDS`, `KONVERTER_WORKERS`, `KONVERTER_MAX_PAGES`, confidence and baseline timing vars.
- Chat and TTS: `OPENAI_API_KEY`, `KONVERTER_PUBLIC_CHAT_PER_IP_PER_MINUTE`, `KONVERTER_PUBLIC_CHAT_GLOBAL_PER_HOUR`, `KONVERTER_TTS_PER_IP_PER_MINUTE`, `KONVERTER_PUBLIC_API_URL` (also the origin baked into the widget).
- Optional: `CLAUDE_API_KEY`. WordPress: `KONVERTER_WORDPRESS_PUBLISH_URL`, `KONVERTER_WORDPRESS_BEARER_TOKEN`, `KONVERTER_WORDPRESS_TIMEOUT_SECONDS`.
- RAG CLI: `RAG_EMBED_PROVIDER`, `RAG_EMBED_MODEL`, `RAG_EMBED_DIM`, `VOYAGE_API_KEY`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `RAG_LLM_MODEL`, `RAG_TOP_K`, `RAG_MIN_SIMILARITY`. Live SQL test only: `RAG_TEST_DATABASE_URL`.

`docker compose up --build frontend` builds the UI against a live backend. The compose file's fallback `VITE_API_BASE_URL` is a specific RunPod proxy URL. Deploy secrets (`RUNPOD_API_KEY`, `DOCKERHUB_*`, Lightsail SSH) live in GitHub environments, not in the app.

## 6. Architectural risks and debt

- **One disk, one process.** Review state, exports, and the PDF live under `KONVERTER_DATA_DIR`. A second API process, or a pod without that volume, cannot see the same documents. Job recovery treats every `"running"` record as dead on startup. `KONVERTER_WORKERS` sizes the parse thread pool; it does not make the store safe for multiple processes.
- **Two notions of "document".** `LocalDocumentStore` is authoritative. The Supabase `documents` row is an audit foreign key and is not updated as review status changes. `wordpress_publications.document_id` is plain text. RAG tables are a third corpus, loaded by the CLI, not by the review API.
- **Approved exports are unauthenticated.** Anyone who has the 32-character id can fetch `accessible.html`, `schema.jsonld`, and `structured.json`, and can call the public chat endpoint, after approval. The id is an unguessable UUID, but it is also embedded in exported HTML and widget URLs.
- **Audit and duplicate-publish protection fail open.** `record_audit` logs and swallows Supabase errors. Without the service role key, a second WordPress publish is not blocked.
- **Rate limits and token cache are memory-local.** They do not survive a restart and do not coordinate across instances. The rate-limiter comment describes this as acceptable because production is a single Uvicorn process.
- **Chat and TTS hide upstream failures inside the stream.** On `OpenAIRequestError` the generator logs and stops. The HTTP response has already started as `200` with `text/plain` or `audio/mpeg`.
- **Pipeline concentration.** Post-parse behavior is a sequence of heuristics in `pipeline.py` and a few helpers. Docling text is treated as authoritative; models may only group it. New passes need fixture tests in `backend/tests/test_pipeline.py` because small label changes move review items and export HTML.
- **No UI error boundary.** A render exception in a stage page takes down the React tree. Loading states use `Suspense` only.
- **Hardcoded deploy default.** `docker-compose.yml` falls back to `https://jxklmut6ta4ya8-8000.proxy.runpod.net/api` when `VITE_API_BASE_URL` is unset. That URL is an environment address, not a secret, and it will rot when the pod changes.
- **Schema is not migrated by the app.** SQL files are idempotent scripts for the Supabase editor. `006_rag_chunks.sql` still contains `{{EMBEDDING_DIM}}` until `python -m app.rag sql` renders it. Applying the template as-is will not create a valid `vector` column.

No hardcoded live API keys showed up in application source. Test files use obvious fake keys (`sk-test-key`). Secrets belong in `.env` or CI secrets; `.env` is not part of the app source.

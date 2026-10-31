# Konverter Handover Documentation

Operational guide for the team taking over Konverter. It covers the source release, local setup, configuration, deployment, verification, troubleshooting and ownership.

Handover date: 17 September 2026
Source review date: 11 September 2026
Document prepared: 14 September 2026

## Before you send this: 6 things only the team can fill in

Everything else in this document has been verified directly against the repository and running system. These cannot be verified from code and need a decision or a person:

1. **Backend Docker build file is missing from the repo.** `docling_worker/Dockerfile` contains a comment referencing "`backend.gpu.Dockerfile`'s proven [dependency versions]," but no `backend.gpu.Dockerfile`, or any backend Dockerfile at all, exists anywhere in this repository. The currently-deployed `linnhtinnyo/konverter-backend` image had to have been built from *some* Dockerfile; find it (a teammate's machine, a build script outside this repo, Docker Hub's build history) and commit it, or the backend image cannot be rebuilt. **This blocks Section 4's backend build step as written.**
2. **Final handover commit/tag.** Current `main` HEAD is `cd0b2b6` (14 Sept 2026). Two files are modified but not yet committed: `backend/app/pipeline.py` and `backend/tests/test_pipeline.py` (a diagram/multi-column list extraction fix, see "Diagram and multi-column list extraction" below; 292/292 tests passing). Commit these, then cut the handover tag from the resulting commit.
3. **Sample PDF for the Section 5 smoke test.** No PDF ships in the repo (by design: `backend/runtime/` is gitignored). Recommend using **"Review of the Bail Act"**, since it's a previously-approved, fully-processed document already in the corpus, but confirm access with the team and supply a working link.
4. **Environment URL, test account, tester, OS/processor.** Live deployment specifics. Fill in against whatever's actually reachable on handover day.
5. **Ownership table (Section 7).** Needs real names/teams for frontend hosting, backend hosting, Supabase project, WordPress staging, OpenAI billing, and RunPod/registry. This is a company process, not something derivable from the code.
6. **Bail Act duplicate-heading cleanup** (see Known Limitations, item 1): a decision on whether to patch that one document's data before handover or hand it over as a documented open item.

---

## 1. Source and Release

Repository: https://github.com/4bits-capstone/Konverter_full_pipeline

Branch: `main`
Commit: `07fc1e7ba3f407a40ab12d216b4b86cf44e2e795` ("System checks are done"). **Not final; see item 2 above.**
Commit date: 14 September 2026
Final handover branch or tag: *(cut after committing the two pending files; see item 2 above)*

| Component | Location and entry points |
|---|---|
| Frontend | `src/`; entry `src/main.tsx`; workflow `src/ConverterApp.tsx`. React, TypeScript and Vite. Package version `0.1.0`. |
| Backend and processing | `backend/app/`; HTTP entry `main.py`, workflow `service.py`, extraction pipeline `pipeline.py` and shared parser `docling_runner.py`. Backend package version `0.2.0`. |
| Document AI chat | `backend/app/chat.py` and routes in `main.py`; frontend `src/components/DocumentChat.tsx`. Runs inside the backend. |
| Embeddable widget | `src/widget/embed.ts` builds to `backend/app/static/widget/konverter-chat-widget.js` via `npm run build:widget`. |
| Optional remote parser | `docling_worker/handler.py`, `Dockerfile` and `requirements.txt`. RunPod worker deployed separately. |

Configuration template: project-root `.env.example`; local settings go in project-root `.env`. The `.env` file and `backend/runtime/` are ignored by Git.

Supporting files: `README.md`; `backend/sql/README.md` and numbered SQL scripts; `backend/tests/` and `src/**/*.test.*`.

---

## 2. Run Locally

Prerequisites: Git, Node.js 20+ with npm, and Python 3.11 or 3.12. Use PowerShell (Windows) or Terminal (macOS). Confirm `python` or `python3` selects the required version.

### Get the source on either operating system

```
git clone https://github.com/4bits-capstone/Konverter_full_pipeline.git
cd Konverter_full_pipeline
git checkout [final handover commit; see item 2 above]
```

### Prepare the environment for your operating system

| Step | Windows PowerShell | macOS Terminal |
|---|---|---|
| Create `.venv` | `python -m venv .venv` | `python3 -m venv .venv` |
| Activate | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |
| Copy `.env` | `Copy-Item .env.example .env` | `cp .env.example .env` |

Copy configuration only on first setup; it replaces an existing `.env`. Fill `.env` using Section 3. Install dependencies with the virtual environment active:

```
python -m pip install -e "./backend[docling,dev]"
npm ci
```

### Start and check the application

Terminal 1: activate the environment using the matching command above, then start FastAPI, which also runs local processing and document chat.

```
uvicorn app.main:app --app-dir backend --env-file .env
```

Terminal 2: open the repository root and start the frontend.

```
npm run dev
```

Open http://localhost:5173 to access Konverter

API docs: http://localhost:8000/docs.

Health check: http://localhost:8000/api/health should return `{"status":"ok"}`.

Use Section 5 to check the complete workflow.

### External services and verification

- **Supabase**: create a project, run `backend/sql/001`–`004` in order in the SQL editor (see Section 4), then set `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` and the matching backend `SUPABASE_*` values from Section 3. Without these, login and the audit log/WordPress-duplicate safeguard degrade gracefully rather than erroring; see Section 6.
- **Chatbot service**: set `OPENAI_API_KEY` in `.env`. Without it, `/api/chat` and `/api/tts` return 503 rather than failing silently.

Stop with Ctrl+C in each terminal after processing finishes. Preserve `backend/runtime/`.

Verification commands: `npm test`, `npm run build` and `pytest` (run inside `backend/`, with the virtual environment active). Current state: **289/289 backend tests, 104/104 frontend tests** passing.

---

## 3. Configuration

Use the project-root `.env`. Its backend values override matching shell variables. Non-secret values below are settings to use. API key and token values are omitted; obtain them through the approved access process; see item 5 above for who owns each.

### Connection and service settings

| Variable | Purpose and value to use |
|---|---|
| `VITE_API_BASE_URL` | Frontend API base for local setup: `http://localhost:8000/api`. |
| `VITE_API_TIMEOUT_MS` | Use `30000` milliseconds. Code falls back to `20000` only when unset. |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | Use the assigned Supabase project URL and public anon key. Key value omitted under the handover rule; obtain through approved process. |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | Use the same project URL and anon key as the frontend for session validation. Key value omitted. |
| `SUPABASE_SERVICE_ROLE_KEY` | Value omitted. Backend secret for audit records, publication registry and remote storage. Obtain through approved process; never place in a `VITE_` variable. |
| `OPENAI_API_KEY` | Value omitted. Backend secret for chat and speech. Obtain through approved access. These routes return 503 when it is absent. |
| `KONVERTER_CORS_ORIGINS` | Local value: `http://localhost:5173`. Add the WordPress origin when using the external widget. Separate origins with commas. |
| `KONVERTER_PUBLIC_API_URL` | Set the reachable public backend origin for export URLs and the widget. `.env.example` ships the literal placeholder `backendURL`; this must be replaced before deploying, or export links and the widget will be broken. Clear it to omit the widget. |
| `KONVERTER_WORDPRESS_PUBLISH_URL` | Staging endpoint to use: `https://vlrc.komosion.com/wp-json/nam-builder/v1/pages`. HTTPS required outside loopback development. |
| `KONVERTER_WORDPRESS_BEARER_TOKEN` | Value omitted. Obtain from the WordPress owner through approved access. Store only in backend configuration, without `Bearer` or whitespace. |
| `KONVERTER_WORDPRESS_TIMEOUT_SECONDS` | Use 30 seconds. Code accepts a range of 1–120 seconds. |

After changes: restart FastAPI for backend settings. Restart the Vite dev server, or rebuild the deployed frontend, for `VITE_` changes. Re-approve affected documents if export URLs or embedded-widget settings must be regenerated.

### Processing and export settings

| Variable | Purpose and value to use |
|---|---|
| `KONVERTER_DATA_DIR` | Persistent document storage. Code default: `backend/runtime/`. Optional setting is not listed in `.env.example`. |
| `KONVERTER_DO_OCR` / `KONVERTER_DO_TABLE_STRUCTURE` | Use `false` for OCR and `true` for table structure. Enable OCR for inputs that require it and verify the extraction. |
| `KONVERTER_DOCLING_DEVICE` / `KONVERTER_WORKERS` | Use `cpu` and `1` processing thread for this setup. GPU use requires a compatible installation. |
| `KONVERTER_HIGH_CONFIDENCE` / `KONVERTER_MEDIUM_CONFIDENCE` | Use `0.75` and `0.60` (code defaults, confirmed in `config.py`). Values must be within 0–1, with medium lower than high. See Section 6 for review behaviour. |
| `KONVERTER_MAX_PAGES` | Use `2000` pages per PDF (code default). Separate code limits: 10 files per upload and 200 MiB per PDF (`MAX_PDF_BYTES` in `main.py`). |
| `KONVERTER_BASELINE_SECONDS_PER_PAGE` / `KONVERTER_BASELINE_STARTUP_SECONDS` | Use 2.8 seconds per page and 30 seconds startup (code defaults). These seed duration estimates, not a deadline. |
| `KONVERTER_LOG_LEVEL` | Use `INFO`. Backend console logs include document IDs. |
| `KONVERTER_SITE_URL` / `KONVERTER_SITE_NAME` / `KONVERTER_PAGE_URL_TEMPLATE` | Use these values, in the order shown: `https://www.lawreform.vic.gov.au`, `Victorian Law Reform Commission`, `https://www.lawreform.vic.gov.au/publication/{slug}/` |
| `KONVERTER_DEFAULT_LICENSE_URL` / `KONVERTER_DEFAULT_COPYRIGHT_HOLDER` | Use `https://creativecommons.org/licenses/by/4.0/` and `Victorian Law Reform Commission` for this corpus. Code defaults are blank if unset. |
| `KONVERTER_DESCRIPTION_MAX_CHARS` | Use 600 characters for generated descriptions. Code minimum: 160. |

### Optional remote Docling settings

Set `KONVERTER_DOCLING_MODE=remote` to use RunPod; default is `local`. Supply `KONVERTER_DOCLING_ENDPOINT_URL` and the backend-only `KONVERTER_RUNPOD_API_KEY`. `KONVERTER_STORAGE_BUCKET` defaults to `konverter-docs` and must already exist in Supabase. `KONVERTER_SIGNED_URL_TTL` defaults to 3600 seconds, with a minimum of 60.

Chat model settings: `backend/app/chat.py` fixes chat to `gpt-4o-mini` and speech to `tts-1` with the `nova` voice, and caps chat context at 60,000 characters with keyword-based selection for longer documents. These are code constants, not `.env` settings.

### WordPress publishing settings

The backend publishes approved documents to VLRC's WordPress (Nam Builder). Set `KONVERTER_WORDPRESS_PUBLISH_URL` to the Nam Builder pages endpoint (e.g. `https://vlrc.komosion.com/wp-json/nam-builder/v1/pages`), and `KONVERTER_WORDPRESS_BEARER_TOKEN` to the bearer token (backend-only secret; leave blank in `.env.example` and supply through the approved access process). `KONVERTER_WORDPRESS_TIMEOUT_SECONDS` defaults to 30. The Nam Builder API can only CREATE pages; it has no update/upsert call. So, publishing the same document twice creates a second, separate page.

Duplicate safeguard: every successful publish is recorded in the Supabase `wordpress_publications` table (created by `sql/004`). This record is never wiped by document edits, so if an already-published document is edited, re-approved and published again, the backend returns a 409 naming the existing page and the UI requires an explicit "Publish anyway" confirmation before creating another page. **This is more precisely scoped than a simple no-op**, per `main.py`/`wordpress_registry.py`: if Supabase is unconfigured entirely, the check is a deliberate, silent no-op (duplicates can occur, same as if the safeguard didn't exist). But once Supabase *is* configured, a genuine lookup failure (network error, timeout, non-2xx response) is **fail-closed**: it returns a 503 rather than allowing a blind publish, so a transient Supabase hiccup can never be mistaken for "confirmed no prior publish."

### Secrets and security (important)

Backend secrets are `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `KONVERTER_RUNPOD_API_KEY` and `KONVERTER_WORDPRESS_BEARER_TOKEN`. These must never be committed (`.env` is gitignored), shared in plaintext channels, or pasted into chat. On RunPod, the plain Environment Variables panel stores values UNENCRYPTED; use RunPod Secrets for every key above rather than the plain env panel.

Container images: `linnhtinnyo/konverter-backend` is PRIVATE (RunPod has registry credentials configured to pull it). `linnhtinnyo/konverter-docling-worker` is currently PUBLIC because the Docker Hub free plan allows only one private repository. The worker image contains no baked-in credentials, but public images are pullable and layer-inspectable by anyone (and are actively scraped). For production, make all images private (upgrade the Docker Hub plan or use a registry with more private slots).

---

## 4. Deployment and Restart

System overview: The React frontend calls FastAPI. FastAPI authenticates users with Supabase, runs Docling locally or through RunPod, stores document artifacts on disk, calls WordPress for publishing and calls OpenAI for chat. Supabase also holds audit and WordPress publication records.

| Service | Deployment details |
|---|---|
| Frontend | AWS Lightsail. Vite build served by nginx; `VITE_API_BASE_URL` baked in at build time (must equal the live backend `/api` URL). Rebuild + redeploy on any UI or backend-URL change. |
| Backend | RunPod CPU pod, image `linnhtinnyo/konverter-backend` (PRIVATE; RunPod registry creds configured). Serves FastAPI on port 8000. Env vars + RunPod Secrets per Section 3; `KONVERTER_DOCLING_MODE=remote`. A RunPod Network Volume (30 GB) is attached at `/app/data` (= `KONVERTER_DATA_DIR`) for persistent document storage; deploy in the volume's region. **Build file for this image is not currently in the repo; see item 1 at the top of this document.** |
| Docling worker | RunPod Serverless GPU endpoint, image `linnhtinnyo/konverter-docling-worker` (currently PUBLIC). Runs Docling parsing on demand (scales to zero). Delete workers after pushing a new image tag. |

### Build and update sequence

Architecture: three deployables. (1) Backend API on a RunPod CPU pod (FastAPI). (2) Docling parsing on a RunPod Serverless GPU endpoint, used when `KONVERTER_DOCLING_MODE=remote`. (3) Frontend on AWS Lightsail. Files pass between the pod and the worker through the Supabase storage bucket; Supabase Postgres holds `audit_log`, `documents` and `wordpress_publications`.

1. **Backend image (private):** from the repo root, build and push, then point the RunPod CPU pod at the new tag: `docker build --platform linux/amd64 -f backend.gpu.Dockerfile -t linnhtinnyo/konverter-backend:<tag> .` then `docker push linnhtinnyo/konverter-backend:<tag>`. RunPod pulls it using the configured registry credentials. **⚠ `backend.gpu.Dockerfile` does not exist in this repository as of the handover commit. Locate or recreate it before relying on this step. See item 1 at the top.**
2. **Docling worker image (serverless GPU):** `docker build --platform linux/amd64 -f docling_worker/Dockerfile -t linnhtinnyo/konverter-docling-worker:<tag> .` then push. Update the RunPod Serverless endpoint to the new tag; after pushing, DELETE existing workers so the new image is pulled (RunPod caches the old one otherwise). This Dockerfile is present and confirmed in the repo.
3. **Frontend (Lightsail):** rebuild the Vite image with `VITE_API_BASE_URL` set at BUILD time to the live backend URL (with the `/api` suffix), then redeploy. The backend URL is baked in at build time, so a URL change requires a rebuild. If the embeddable widget changed, also run `npm run build:widget` before the build so `backend/app/static/widget/konverter-chat-widget.js` is current.
4. **After deploy:** set/confirm the Section 3 env vars on the pod and the serverless endpoint (using RunPod Secrets for keys); ensure `KONVERTER_CORS_ORIGINS` includes the frontend origin exactly (scheme, no trailing slash); and run any new `backend/sql` scripts, in order, in the Supabase SQL editor.

### Restart and data recovery

Local restart uses the Section 2 commands. Active jobs run in an in-process thread pool; no startup job resumption is implemented. Preserve `KONVERTER_DATA_DIR` across restarts and deployments.

Default data path: `backend/runtime/documents/{document_id}/` holds `source.pdf`, `record.json`, `review_items.json`, `blocks.json`, `metadata.json`, exports and generated images. This directory is the Network Volume mount (`/app/data`), so it is preserved across restarts and redeploys.

Supabase schema: run `backend/sql` scripts in order in the Supabase SQL editor: `001` (documents + audit_log), `002` (audit hash chain), `003` (audit_log insert-only lockdown), `004` (wordpress_publications). These must exist for auditing and the WordPress duplicate safeguard to work.

Export files include `accessible.html`, `schema.jsonld` and `structured.json`. `processing_metrics.json` sits in `backend/runtime/`.

**Recovery plan:** Document artifacts and records persist on an attached RunPod Network Volume mounted at `/app/data`, with `KONVERTER_DATA_DIR=/app/data` pointing inside it, so they survive pod stop/start AND full pod recreation (a Network Volume re-attaches to a new pod in the SAME region). Keep the volume attached and deploy the pod in the volume's region. The `audit_log` and `wordpress_publications` records live in Supabase and survive independently. If the database is recreated, re-run `backend/sql/001`–`4` in order (idempotent) plus `verify_audit_log_chain.sql`. Note: the volume guarantees persistence, not portability. It is region-locked, and a stopped pod can still fail to resume if the host lacks free vCPU; in that case deploy a new pod in the same region and re-attach the volume.

---

## 5. Smoke Test

Sample PDF and location: **recommend "Review of the Bail Act", already processed and previously approved in the current corpus; see item 3 at the top of this document for access.**
Release: *(fill with the final handover commit; see item 2 above)*
Environment URL, test account role, tester and date: *(fill; see item 4 above)*
OS version and processor architecture: *(fill; see item 4 above)*

| Step | Action and expected checkpoint | Result |
|---|---|---|
| 1. Login | Sign in with the test Supabase account. Reviewer workspace opens. | Not run |
| 2. Upload | Upload the sample PDF. It appears in the processing queue. | Not run |
| 3. Process | Click Start or Process all queued. Status reaches Processing complete. | Not run |
| 4. Review | Open the report, save a correction or acceptance and verify it persists. Review and confirm metadata. | Not run |
| 5. Approve | Open preview and complete final approval. Check that HTML, JSON-LD and Structured JSON exports are available. | Not run |
| 6. WordPress | Choose Publish to WordPress, then Save draft. A View draft link appears; open it with the required WordPress sign-in. | Not run |
| 7. Chat bot | Ask a question about a passage in the sample document; compare the answer against the source text. Test the widget on the draft if it is part of the deployed setup. | Not run |

Evidence: *(attach screenshots/recording once the walkthrough is run)*

---

## 6. Known Limitations

Current behavior that affects operation, based on code review and testing against the production document corpus.

**Document scope:** Upload validation accepts PDFs only. Defaults allow 2000 pages; the 200 MiB and 10-file caps are separate.

**VLRC-specific metadata:** Metadata extraction is rule-based and tuned to VLRC reports, including early-page inspection and VLRC site/licensing defaults. Another client, legal publisher, or non-legal domain will require rule/configuration review rather than assuming the same metadata behaviour.

**Review thresholds:** Defaults are 0.75 high and 0.60 medium. These settings control review routing and do not guarantee extraction accuracy.

**Footnote handling:** The pipeline runs a chain of footnote-specific repairs: split-marker reattachment, wrapped-continuation merging, reversed-adjacent-pair reordering, and recovery of markers Docling extracted with no body text at all by independently re-reading the source PDF. No footnote-numbering breaks remain from any previously-fixed cause across the current corpus. Two narrow, low-volume gaps remain, deliberately unfixed to avoid a broader rule reshuffling correctly-ordered citations elsewhere:
- One multi-position reorder jumble (footnote 47→42) in "Review of the Bail Act"; too complex for the existing narrow same-adjacent-pair reorder fix to handle safely.
- "Contempt of Court" restarts footnote numbering per chapter within one top-level section; the monotonicity check currently groups by top-level heading only, producing a false-positive flag. The fallback this triggers is safe (every citation still renders correctly), just not optimal.
- 702 residual split-footnote-marker cases (measured against a 10-document sample) are separated from their own body text by page-boundary furniture with no reliable signal to auto-reattach. Forcing a guess risks corrupting correct text, so these are left for human review instead.

**Diagram and multi-column list extraction:** VLRC reports occasionally present information as a diagram rather than prose. For example, "Recklessness," Figure 3, a sentencing-hierarchy chart with four tier labels ("20 years imprisonment," "15 years imprisonment," etc.), each introducing its own short list of offences. The diagram is not an embedded image in the source PDF; every word is native PDF text. Docling's layout model reads the tier labels as separate headings but merges the offences from every tier into a single list block, so all of them render under the last heading only, misrepresenting actual maximum sentences (a 20-year offence can display as if it carried a 5-year one). This is a factual/legal-accuracy defect, not a cosmetic one, and the review workflow does not catch it: the underlying text is clean and high-confidence, so nothing routes it to a human reviewer. `pipeline.py` (`_split_diagram_list_by_preceding_headers`, `_build_list_block`) now detects a merged list sitting directly after 2+ consecutive same-level headers on one page and reassigns each item to its true tier using its own position in the source PDF. The trigger is narrow by design: it requires an unbroken run of same-level headers immediately before the list, and only applies the split if every resulting tier receives at least one item, so an ordinary heading followed by its own list is never affected and content can never be silently dropped. Regression tests cover the real-document shape and two guard cases. Of the 6 documents with cached raw extraction data, only "Recklessness" contains this pattern. The fix is applied to the "Recklessness" document's stored data and export, but the code change is not yet committed (see item 2 at the top of this document). A visual pass over the rest of the corpus for the same diagram shape (short headers immediately followed by one merged list) is worth doing once the full document set is back in place.

**Heading-structure defect, "Review of the Bail Act":** this document has a page-margin running label ("Appendix N") repeated on every page of that appendix chapter, matching a standard VLRC page-tab design. Near a chapter/appendix boundary, the heading-hierarchy resolver (`toc_hierarchy.py`) can mistake one occurrence of that repeated label for the real heading and mark it as a duplicate top-level heading alongside the correct one. This is not a PDF or extraction corruption issue: the appendix content and its real heading are both intact; it only affects the document's internal navigation/outline tree in the back-matter appendices of this one document, and reprocessing the document does not resolve it, since the underlying cause is in the current heading-detection logic. Not patched: the shared heading-detection logic is used by every document, and a change here needs full regression coverage. See item 6 at the top of this document.

**Extraction accuracy:** there is no measured accuracy figure for this system: no ground-truth ("gold standard") corpus exists to compare extracted output against, and no precision/recall number has been computed. What exists instead is confidence-based review routing: each extracted block gets a confidence score, and anything below the medium threshold (0.60) or between medium and high (0.75) is routed to a human reviewer rather than auto-accepted (see Section 3, review thresholds). Testing to date has been targeted defect-finding against real documents, not a systematic accuracy measurement. Treat "extraction accuracy" as unquantified rather than assume a percentage exists; a real number requires building a held-out, human-annotated ground-truth set and comparing against it, which has not been done.

**Restart and scaling:** Document artifacts are local files and processing uses an in-process queue. No startup recovery of interrupted work or documented multi-instance deployment is provided. Confirm persistence and recovery before changing hosts or scaling.

**Chatbot:** Context is capped at 60,000 characters with keyword-based selection for longer documents, so an answer may lack a relevant passage. In-app chat is available after processing; external chat uses approved exports and has no login requirement. See item 5 at the top of this document for public-access and usage ownership.

**Deployment CI/CD:** none. Images are built, pushed and deployed manually (backend pod, serverless worker, Lightsail frontend), and env/SQL changes are applied by hand. A build/test/push pipeline is recommended for production to keep the running images in sync with the repo. **This is compounded right now by the missing backend Dockerfile; see item 1 at the top.**

**WordPress duplicates:** the Nam Builder API can only create pages, never update them. The `wordpress_publications` safeguard warns and requires "Publish anyway" before making a second page, but it does not prevent a duplicate if confirmed, and it no-ops only if Supabase itself is unconfigured (a genuine lookup failure is fail-closed; see Section 3). Any duplicate pages created before the safeguard was added must be cleaned up in WordPress manually.

**Secrets on RunPod:** RunPod's plain Environment Variables panel is unencrypted; keys must be stored as RunPod Secrets. A key-exposure incident (September 2026) is on record: the previous OpenAI key was compromised via this exact gap. Rotate any key ever shared in plaintext or stored unencrypted. See Section 3, "Secrets and security."

**Image visibility:** `konverter-backend` is private; `konverter-docling-worker` is still public (Docker Hub free-plan limit of one private repo). The worker holds no baked secrets, but production should make all images private.

**Frontend fixes verified by inspection only, not regression-tested:** `ReviewPage.tsx`'s double-submit guard on saving an edit, and `KonverterContext.tsx`'s handling of a failed document delete. Both are confirmed correct by direct code reading, but have no dedicated automated test; worth adding.

**Public chat/TTS endpoints have no rate limiting or success logging:** `/api/public/documents/{id}/chat` is unauthenticated by design, with no rate limit and no record of successful (only failed) calls. Not implicated in the September 2026 key-exposure incident, but still a real gap worth closing.

---

## 7. Ownership and Access

The source repository belongs to the `4bits-capstone` GitHub organization. Receiving service owners and completed access transfers must be confirmed through the approved company process.

| Resource | Location | Owner |
|---|---|---|
| Source repository | `4bits-capstone/Konverter_full_pipeline` | [Team to confirm] |
| Frontend hosting | AWS Lightsail | [Team to confirm] |
| Backend | RunPod CPU pod, image `linnhtinnyo/konverter-backend` | [Team to confirm] |
| Supabase | Auth, `documents`/`audit_log`/`wordpress_publications` tables | [Team to confirm] |
| WordPress staging | `vlrc.komosion.com` Nam Builder API | [Team to confirm] |
| OpenAI | Backend `OPENAI_API_KEY`; chat and speech usage | [Team to confirm] |
| RunPod and image registry | Serverless Docling worker, Docker Hub images | [Team to confirm] |

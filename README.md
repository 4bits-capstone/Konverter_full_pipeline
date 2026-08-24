## Requirements

- Node.js 20+
- Python 3.11 or 3.12

## Setup

Run from the project root (PowerShell shown; use `source .venv/bin/activate` on macOS/Linux):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e "./backend[docling,dev]"
npm ci
Copy-Item .env.example .env
```

## Run

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --app-dir backend --env-file .env
```

Optional GPU support:

```powershell
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

Then set `KONVERTER_DOCLING_DEVICE=cuda` in `.env` and restart the backend.

Frontend:

```powershell
npm run dev
```

Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`.

## Confidence settings

```dotenv
KONVERTER_HIGH_CONFIDENCE=0.75
KONVERTER_MEDIUM_CONFIDENCE=0.60
```
## Other settings

```dotenv
KONVERTER_DO_OCR=false            # keep off for text-based PDFs
KONVERTER_DO_TABLE_STRUCTURE=true
KONVERTER_DOCLING_DEVICE=cpu      # cpu | cuda | auto
KONVERTER_WORKERS=1
KONVERTER_MAX_PAGES=2000          # reject larger uploads
KONVERTER_SITE_URL=               # optional, hosting site, e.g. https://www.lawreform.vic.gov.au
KONVERTER_SITE_NAME=              # optional, hosting site name
KONVERTER_PAGE_URL_TEMPLATE=      # optional, e.g. https://…/publication/{slug}/
KONVERTER_PUBLIC_API_URL=         # optional public origin for absolute cover/source/HTML URLs;
                                   # also the backend origin the embeddable chat widget baked
                                   # into exported HTML (see "Embeddable chat widget" below) uses
KONVERTER_DEFAULT_LICENSE_URL=    # explicit corpus default; clear when rights differ
KONVERTER_DEFAULT_COPYRIGHT_HOLDER=
KONVERTER_DESCRIPTION_MAX_CHARS=600
KONVERTER_LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
```

## Auth settings

```dotenv
VITE_SUPABASE_URL=                # Supabase project URL
VITE_SUPABASE_ANON_KEY=           # Supabase anon public key
SUPABASE_URL=                     # same as VITE_SUPABASE_URL
SUPABASE_ANON_KEY=                # same as VITE_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY=        # backend only, never exposed to the frontend
```

## Document chat assistant

The Preview page includes a chat/voice assistant that answers questions about
the approved document using its `schema.jsonld` and `structured.json`
exports as context.

```dotenv
OPENAI_API_KEY=                   # backend only, never exposed to the frontend
```

Without this key set, `/api/chat` and `/api/tts` return 503.

## Embeddable chat widget

Every approved document's exported `accessible.html` can carry its own
floating chat widget, so the same Q&A works once the export is published on
an external site (e.g. pasted into a WordPress page) — not just inside the
Konverter reviewer app. It talks to `/api/public/documents/{id}/chat`, an
unauthenticated counterpart to the in-app chat endpoint (no Supabase login
available on an external page), gated so it only ever answers for approved
documents and only reads their finished export.

It's off by default: the widget is only baked into an export when
`KONVERTER_PUBLIC_API_URL` is set to the backend's real, publicly-reachable
origin (the same setting already used for absolute cover/source URLs — see
above). Without it, there's no reliable absolute URL to point the widget at
from a page hosted elsewhere, so it's omitted rather than baked in broken.

The widget itself (`src/widget/embed.ts`) is a small, dependency-free
standalone script — no React, so it doesn't inflate every exported HTML file
with a full app bundle. Build it before deploying:

```powershell
npm run build:widget
```

This compiles to `backend/app/static/widget/konverter-chat-widget.js`, which
the backend serves directly (`/static/widget/...`). Re-run it any time
`src/widget/embed.ts` changes — it isn't part of the regular `npm run build`.

Also add the site that will host the export to CORS:

```dotenv
KONVERTER_CORS_ORIGINS=http://localhost:5173,https://your-wordpress-site.example
```

## Verify

```powershell
npm test
npm run build
pytest backend
```

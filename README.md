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
KONVERTER_MEDIUM_CONFIDENCE=0.55
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
KONVERTER_PUBLIC_API_URL=         # optional public origin for absolute cover/source/HTML URLs
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

## Verify

```powershell
npm test
npm run build
pytest backend
```

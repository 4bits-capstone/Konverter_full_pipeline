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

## Heading hierarchy and visual structure

The Docling install also includes
[`docling-hierarchical-pdf`](https://github.com/krrome/docling-hierarchical-pdf).
Konverter runs its bookmark/numbering/style resolver before building review
blocks, then maps the resolved structure into the application contract:

- `Title`: one document title
- `Chapter title`: the top-level preview/accessible-HTML section
- `H1`–`H5`: headings within that section
- `Callout`: shaded case studies, information panels, and recommendation boxes

The included postprocessor is a patched 0.1.8-compatible implementation. It
limits numbered list-item promotion to short heading candidates, reconstructs
the parent tree in one pass, and keeps headers/footers outside the content tree.
Large, low-contrast, rotated, or repeated decorative PDF text is filtered before
review and export so chapter-number watermarks are not treated as content.

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
KONVERTER_LOG_LEVEL=INFO          # DEBUG | INFO | WARNING | ERROR
```

Pipeline logging (processing start/stage/completion, JSON-LD generation) uses
only the Python standard library, so no extra install step is needed — it's
covered by the base backend install above.

## Verify

```powershell
npm test
npm run build
pytest backend
```

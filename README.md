# Konverter

Turns legal and government PDFs into reviewed, accessible web content.
Upload a PDF → Docling extracts the structure → a human reviews flagged
items and metadata → approval generates WCAG 2.1 accessible HTML,
Schema.org JSON-LD and structured JSON.

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

## Workflow

1. **Upload** — up to 5 PDFs (200 MB each). Documents process independently;
   drop more PDFs onto the queue at any time. Reloading the page picks up
   documents already stored on the backend.
2. **Review flags** — items below the high-confidence threshold are queued.
   Accept, edit (including changing the structure label, which converts the
   content), or remove each one. Compare against the rendered PDF evidence.
3. **Metadata** — confirm title, publisher, date, jurisdiction and citations.
   Approval stays blocked until this step is completed.
4. **Approval** — system checks plus a short reviewer checklist that only
   lists checks relevant to the document. Approving generates the output;
   revoking (or editing anything afterwards) discards it again.
5. **Preview & export** — landing-page preview with live accessibility
   checks, plus exports: accessible HTML, `schema.jsonld`, `structured.json`.

## Confidence settings

```dotenv
KONVERTER_HIGH_CONFIDENCE=0.75
KONVERTER_MEDIUM_CONFIDENCE=0.55
```

Scores come from the Docling layout model. At or above **high** the item is
accepted automatically. Between the two thresholds it is flagged **Medium**
(usually fine — quick check). Below **medium** it is flagged **Low** (most
real errors live here — check these first). The defaults were tuned against
reviewer decisions on the VLRC corpus; raise `HIGH` for stricter review,
lower it to shrink the queue.

Metadata fields have their own rule-based confidence: each extraction rule
carries a prior (an explicit "Published by …" line scores higher than a
filename guess) which is then adjusted by corroboration, e.g. how often the
jurisdiction or publisher recurs and how many citations were found.

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
```

The exported JSON-LD is a schema.org `@graph` (Report + WebPage +
Organization, plus WebSite and breadcrumbs when the site values are set).
Node ids are page-specific; with `KONVERTER_PAGE_URL_TEMPLATE` they become
absolute URLs. The WebSite describes the *hosting* site — the document's
publisher is only linked as its owner when the names match. Accessibility
claims, series/report number, ISBN identifiers and citations are derived
from the reviewed document; unknown values are omitted rather than guessed.

## Verify

```powershell
npm test
npm run build
pytest backend
```

`backend/tests/test_security.py` holds the security regression tests
(path traversal, upload validation, XSS escaping, size limits, headers).

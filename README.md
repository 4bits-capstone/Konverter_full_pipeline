## Requirements

- Node.js 20+
- Python 3.11 or 3.12

## Setup

Run from the project root in PowerShell:

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
Optional to enable GPU
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126

Frontend:

```powershell
npm run dev
```

Open `http://localhost:5173`. API documentation is at
`http://localhost:8000/docs`.

## Settings

```dotenv
KONVERTER_HIGH_CONFIDENCE=0.85
KONVERTER_MEDIUM_CONFIDENCE=0.65
KONVERTER_DO_OCR=false
KONVERTER_DO_TABLE_STRUCTURE=true
KONVERTER_DOCLING_DEVICE=cpu
KONVERTER_WORKERS=1
```

High-confidence structure is accepted automatically. Medium- and low-confidence
items enter the review queue. Keep OCR off for text-based PDFs.

Set `KONVERTER_DOCLING_DEVICE=cuda` to use an NVIDIA GPU with a CUDA-enabled
PyTorch installation. Use `auto` to let Docling choose, or keep `cpu` for the
most predictable memory use. Restart the backend after changing the device.


## Verify

```powershell
npm test
npm run build
pytest backend
```

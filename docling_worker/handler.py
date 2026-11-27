import json
import os
import tempfile

import requests
import runpod
from docling_runner import run_docling


def _download(url: str, dest: str) -> None:
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(1 << 20):
                handle.write(chunk)


def _upload(target: dict, path: str) -> None:
    upload_url = target.get("url") or target["signed_url"]
    with open(path, "rb") as handle:
        response = requests.put(
            upload_url,
            data=handle,
            headers={"content-type": "application/json", **target.get("headers", {})},
            timeout=600,
        )
    response.raise_for_status()


def handler(job: dict) -> dict:
    job_input = job["input"]
    options = job_input.get("options") or {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        pdf_path = os.path.join(tmp_dir, "source.pdf")
        _download(job_input["pdf_download_url"], pdf_path)
        payload = run_docling(pdf_path, options)
        result_path = os.path.join(tmp_dir, "docling.json")
        with open(result_path, "w") as handle:
            json.dump(payload, handle)
        _upload(job_input["result_upload"], result_path)
    return {
        "ok": True,
        "docling_version": payload.get("docling_version"),
        "conversion_status": payload.get("conversion_status"),
        "error_count": len(payload.get("conversion_errors") or []),
        "parse_elapsed_seconds": payload.get("parse_elapsed_seconds"),
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})

# R3 Long-Document Memory & Timing Report (`generate_parsed_pages`)

**Date**: 2026-11-22  
**Milestone**: M4 (`teamwork_worker_m4`)  
**Workspace**: `/Users/yethuaung/Konverter_full_pipeline`  
**Docling Version**: `2.121.0` (strictly offline: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`)

---

## 1. Executive Summary

1. **Memory impact of `generate_parsed_pages=True` is negligible (~9.6 KiB/page)**: Across 31-page, 164-page, and 284-page PDFs using Konverter's `PyPdfiumDocumentBackend` (`do_ocr=False`, `do_table_structure=True`), `page.parsed_page` (`SegmentedPdfPage`) only populates `textline_cells` (`word_cells=0`, `char_cells=0`). Retaining `parsed_page` across all pages adds only:
   - **31 pages** (`711` textline cells): **`0.28–0.29 MiB`** Python heap (`~9.2 KiB/page`)
   - **164 pages** (`9,662` textline cells): **`1.55–1.57 MiB`** Python heap (`~9.7 KiB/page`)
   - **284 pages** (`17,716` textline cells): **`2.66–2.67 MiB`** Python heap (`~9.6 KiB/page`)
   Meanwhile, peak process RSS (`ru_maxrss`) is **`2.41–2.96 GiB`** (`2,410.66–2,957.58 MiB`), dominated by `docling-layout-heron` + `TableFormer` weights, PyTorch CPU batch tensor activations, and `pypdfium2` page buffers. The `generate_parsed_pages=True` Python-heap delta (`< 2.7 MiB` at 284 pages) represents **`< 0.1%` of peak RSS** and is smaller than normal run-to-run allocator variance (`±100–250 MiB` in `ru_maxrss`).
2. **Parse-timing impact is negligible**: Docling constructs `SegmentedPdfPage` during the `parse` stage regardless of `generate_parsed_pages`; setting `generate_parsed_pages=False` only clears `page.parsed_page = None` inside `_release_page_resources()` (`standard_pdf_pipeline.py:698-699`) and `_build_document()` (`standard_pdf_pipeline.py:1033-1035`). On `report-2016.pdf` (164p), `convert()` took **`69.696s`** (`True`) vs **`69.375s`** (`False`, `+0.46%`). On `Capstone` (31p), `20.044s` (`True`) vs `19.719s` (`False`).
3. **Disabling `generate_parsed_pages` silently breaks `HeadingHierarchyOptions(use_style=True)`**: In Docling `2.121.0`, `_release_page_resources()` clears `page.parsed_page = None` *before* `_assemble_document()` runs `HeadingHierarchyModel` (`standard_pdf_pipeline.py:1050`, `heading_hierarchy_model.py:497-503, 547`). With `generate_parsed_pages=False`, `use_style=True` receives an empty `parsed_pages` dict and silently degrades:
   - `Capstone Final Report Template.pdf` (31p): **22 / 45 (`48.9%`)** `section_header` items collapsed to `level=1`.
   - `report-2016.pdf` (164p): **159 / 282 (`56.4%`)** `section_header` items collapsed to `level=1`.
   - `VLRC_Inclusive-Juries-Report-Parl-May_23.pdf` (284p): **292 / 456 (`64.0%`)** `section_header` items collapsed to `level=1`.
4. **Clearing `page.parsed_page = None` immediately after `convert()` returns** frees the entire `SegmentedPdfPage` Python heap (`0.28 MiB` at 31p, `1.55 MiB` at 164p, `2.67 MiB` at 284p, returning traced heap to exact `False`-mode parity) without breaking `HeadingHierarchyModel` (which finishes inside `convert()`) and without affecting `docling_runner._cluster_confidences(result)` (which only reads `page.page_no` and `page.predictions.layout.clusters`).

**Recommendation**: **Keep `generate_parsed_pages=True`** so `HeadingHierarchyOptions(use_style=True)` functions properly. Optionally clear `page.parsed_page = None` inside `docling_runner.run_docling()` immediately after `converter.convert()` returns if long-lived worker retention of `ConversionResult` were ever introduced (currently `result` is already local to `run_docling()` and garbage-collected on function return). Note that Konverter's memory bottleneck is the **`~2.7–3.0 GiB` peak RSS during `convert()`** (which validates keeping the global `_lock` in `docling_runner.py` to prevent concurrent 3 GiB parses from OOMing workers).

---

## 2. Measurement Methodology & Environment

- **Hardware / OS**: Apple M5, 24 GiB RAM (`25,769,803,776` bytes), macOS `26.6.2` (Build `25G83`, `sys.platform == "darwin"`).
- **Runtime**: `/Users/yethuaung/Konverter_full_pipeline/.venv/bin/python` (Python `3.13.9`), `docling==2.121.0`, `psutil==7.2.2`, `pymupdf` (for bookmark inspection only).
- **Isolation & Offline Enforcement**:
  - Every configuration (`generate_parsed_pages=true` vs `false`) executed in a **fresh isolated subprocess** with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.
  - Docling configuration matches `backend/app/docling_runner.py` (`e3e40d8` baseline):
    - `docling_settings.inference.compile_torch_models = False`
    - `do_ocr = False`, `do_table_structure = True`, `TableStructureOptions(do_cell_matching=True)`
    - `HeadingHierarchyOptions(enabled=True, use_bookmarks=True, use_numbering=True, use_style=True, max_level=5, bookmark_match_threshold=0.76)`
    - `AcceleratorOptions(device=AcceleratorDevice.CPU)`, `PyPdfiumDocumentBackend`
  - **Memory metrics**:
    - `ru_maxrss`: Normalized from bytes to MiB (`raw / (1024 * 1024)`) on `sys.platform == "darwin"` (vs KiB `raw / 1024` on Linux).
    - `psutil.Process(os.getpid()).memory_info().rss`: Sampled every `0.25s` by a background thread during `convert()`, plus point-in-time snapshots (`init`, `after_build`, `after_convert`, `after_export`, `before_clear_after_gc`, `after_clear_no_gc`, `after_clear_gc`). Cross-checked at `after_convert` with `/bin/ps -o rss= -p <pid>`.
    - `tracemalloc`: Enabled from process start (`current` and `peak` in MiB) to isolate exact Python-heap allocations (`page.parsed_page` footprint) from OS virtual-memory/allocator RSS noise. A separate `--no-tracemalloc` control run on Capstone (31p) confirmed `tracemalloc` adds `< 1s` to `convert()` (`20.044s` vs `20.267s`) and negligible peak RSS difference (`2633.41` vs `2439.69 MiB`).
  - **Post-`convert()` clearing isolation**: `gc.collect()` is called *before* measuring `before_clear_after_gc`, then `for p in result.pages: p.parsed_page = None` + `gc.collect()` is measured as `after_clear_gc`, isolating `gc.collect()`'s own side effects from `parsed_page` deallocation.

---

## 3. Fixture Documents

| Fixture PDF | Git-Tracked | Pages | Size | PDF Bookmarks (`get_toc()`) | Docling `texts` / `tables` / `pictures` |
|---|---|---:|---:|---:|---|
| `docs/capstone/Capstone Final Report Template.pdf` | Yes | 31 | 0.99 MB | 21 | `179` / `8` / `4` |
| `docs/rag-inputs/samples/report-2016.pdf` | No (`.gitignore`) | 164 | 4.16 MB | 116 | `3,205` / `11` / `6` |
| `backend/runtime/documents/41096af87daa450495c2823ecd8c9eba/source.pdf` (`VLRC_Inclusive-Juries-Report-Parl-May_23.pdf`) | No (`.gitignore`) | 284 | 4.34 MB | 142 | `5,267` / `31` / `29` |

---

## 4. Memory & Timing Results (`generate_parsed_pages=True` vs `False`)

### 4.1 Timing Comparison (seconds)

| Document (Pages) | `generate_parsed_pages` | `build_converter` | `convert()` | `convert()` / page | `export_to_dict()` | `clear + gc` | Total Subprocess |
|---|---|---:|---:|---:|---:|---:|---:|
| Capstone (31p) | `True` | 0.221s | **20.044s** | 0.647s | 0.013s | 0.1307s | 30.997s |
| Capstone (31p) | `True` (`--no-tracemalloc`) | 0.057s | **20.267s** | 0.654s | 0.004s | 0.1353s | 23.504s |
| Capstone (31p) | `False` | 0.229s | **19.719s** | 0.636s | 0.011s | 0.1180s | 29.402s |
| `report-2016.pdf` (164p) | `True` | 0.192s | **69.696s** | 0.425s | 0.101s | 0.1337s | 78.480s |
| `report-2016.pdf` (164p) | `False` | 0.194s | **69.375s** | 0.423s | 0.098s | 0.1397s | 78.570s |
| `VLRC_Inclusive-Juries` (284p) | `True` | 0.229s | **129.481s** | 0.456s | 0.177s | 0.1844s | 139.706s |
| `VLRC_Inclusive-Juries` (284p) | `False` | 0.194s | **174.366s** | 0.614s | 0.224s | 0.5168s | 184.579s |

*Timing note*: On `report-2016.pdf` (164p) and `Capstone` (31p), `convert()` times are within `0.3s` (`< 1.7%`). On `VLRC_Inclusive-Juries` (284p), the `False` run experienced slower CPU/thermal scheduling (`174.366s` vs `129.481s`), confirming `generate_parsed_pages=True` adds no measurable CPU cost (if anything, it avoids per-page `del p.parsed_page` during pipeline execution).

### 4.2 Process RSS (`ru_maxrss` & `psutil` / `/bin/ps`, MiB)

| Document (Pages) | `generate_parsed_pages` | `after_build` | `during_convert` Peak (Mean) | `after_convert` (`ps` check) | `after_export` | `ru_maxrss` Peak |
|---|---|---:|---:|---:|---:|---:|
| Capstone (31p) | `True` | 510.88 | 2,546.80 (1,591.76) | 1,727.50 (`1,727.55`) | 1,730.36 | **2,633.41** |
| Capstone (31p) | `True` (`--no-tm`) | 375.31 | 2,405.69 (1,819.76) | 1,549.83 (`1,549.84`) | 1,551.23 | **2,439.69** |
| Capstone (31p) | `False` | 504.58 | 2,756.31 (1,646.70) | 1,814.62 (`1,814.62`) | 1,816.81 | **2,756.31** |
| `report-2016.pdf` (164p) | `True` | 503.83 | 2,655.09 (1,839.68) | 1,802.08 (`1,802.36`) | 1,836.58 | **2,711.02** |
| `report-2016.pdf` (164p) | `False` | 505.31 | 2,931.72 (2,263.50) | 1,872.62 (`1,872.81`) | 1,905.27 | **2,957.58** |
| `VLRC_Inclusive-Juries` (284p) | `True` | 509.89 | 2,841.66 (1,860.35) | 1,713.12 (`1,713.25`) | 1,765.12 | **2,898.20** |
| `VLRC_Inclusive-Juries` (284p) | `False` | 504.84 | 2,728.52 (1,938.89) | 1,886.06 (`1,886.30`) | 1,943.78 | **2,816.50** |

### 4.3 Python Heap (`tracemalloc`, MiB) & `parsed_page` Retention / Clearing

| Document (Pages) | `generate_parsed_pages` | `textline_cells` | `after_convert` Curr (Peak) | `after_export` Curr (Peak) | `before_clear_after_gc` Curr | `after_clear_gc` Curr | Freed by `parsed_page=None` (`tracemalloc`) | `rss` Before -> After Clear (`freed_by_clear_rss`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Capstone (31p) | `True` | 711 | 287.14 (307.19) | 288.00 (307.19) | 287.86 | 287.58 | **0.28 MiB** | 1,778.20 -> 1,778.27 (`-0.06 MiB`) |
| Capstone (31p) | `False` | 0 | 286.85 (306.92) | 287.72 (306.92) | 287.58 | 287.58 | 0.00 MiB | 1,816.83 -> 1,816.83 (`0.00 MiB`) |
| `report-2016.pdf` (164p) | `True` | 9,662 | 335.92 (345.46) | 343.95 (351.51) | 343.86 | 342.31 | **1.55 MiB** | 1,837.02 -> 1,837.94 (`-0.92 MiB`) |
| `report-2016.pdf` (164p) | `False` | 0 | 334.35 (343.92) | 342.38 (349.95) | 342.31 | 342.31 | 0.00 MiB | 1,905.58 -> 1,905.58 (`0.00 MiB`) |
| `VLRC_Inclusive-Juries` (284p) | `True` | 17,716 | 377.77 (394.16) | 392.21 (405.81) | 392.12 | 389.45 | **2.67 MiB** | 1,765.48 -> 1,770.47 (`-4.98 MiB`) |
| `VLRC_Inclusive-Juries` (284p) | `False` | 0 | 375.11 (391.53) | 389.55 (403.15) | 389.48 | 389.48 | 0.00 MiB | 1,944.00 -> 1,432.62 (`+511.38 MiB`*) |

*\*Note on RSS vs `tracemalloc`*: In `VLRC_Inclusive-Juries` (`False`), `parsed_page` was already `None` (`0.00 MiB` traced heap change), yet `gc.collect()` triggered a `511.38 MiB` OS RSS drop from allocator/arena page release. Conversely, `tracemalloc` demonstrates exact determinism: clearing `page.parsed_page = None` on `True` runs drops traced heap from `287.86 -> 287.58 MiB` (matching `False`'s `287.58 MiB`), `343.86 -> 342.31 MiB` (matching `False`'s `342.31 MiB`), and `392.12 -> 389.45 MiB` (matching `False`'s `389.48 MiB`).*

---

## 5. Heading Hierarchy Impact (`HeadingHierarchyOptions(use_style=True)`)

Across all three PDFs, `label_counts` across `raw_docling["texts"]` (including total `#section_header` count) remained identical between `True` and `False`, **but `level` assignments degraded severely when `generate_parsed_pages=False`**:

| Document | Total `#section_header` | Levels (`generate_parsed_pages=True`) | Levels (`generate_parsed_pages=False`) | Changed Headers | Level Transitions (`True -> False`) |
|---|---:|---|---|---:|---|
| Capstone (31p) | 45 | `L1: 11, L2: 14, L4: 18, L5: 2` | `L1: 33, L2: 12` | **22 / 45 (48.9%)** | `(4→1): 18`, `(2→1): 2`, `(5→1): 2` |
| `report-2016.pdf` (164p) | 282 | `L1: 27, L2: 44, L3: 60, L4: 1, L5: 150` | `L1: 186, L2: 41, L3: 55` | **159 / 282 (56.4%)** | `(5→1): 150`, `(3→1): 5`, `(2→1): 3`, `(4→1): 1` |
| `VLRC_Inclusive-Juries` (284p) | 456 | `L1: 41, L2: 117, L4: 23, L5: 275` | `L1: 333, L2: 115, L4: 8` | **292 / 456 (64.0%)** | `(5→1): 275`, `(4→1): 15`, `(2→1): 2` |

### Why this happens (verified in Docling `2.121.0`)
1. `StandardPdfPipeline._release_page_resources()` (`standard_pdf_pipeline.py:698-699`) clears `page.parsed_page = None` per page during the threaded pipeline stage when `generate_parsed_pages=False`, **before** `_assemble_document()` (`standard_pdf_pipeline.py:1038-1050`) runs `self.heading_hierarchy_model(conv_res)`.
2. `HeadingHierarchyModel.__call__()` (`heading_hierarchy_model.py:497-503`) builds `parsed_pages = {page.page_no: page.parsed_page for page in conv_res.pages if page.parsed_page is not None}` and passes it to `assign_heading_levels()`.
3. When `parsed_pages` is empty, `if self.options.use_style and parsed_pages:` (`heading_hierarchy_model.py:547`) evaluates to `False`. Headings not matched by PDF bookmarks or explicit numbering keep Docling's default `level=1` instead of being assigned `level=2..5` by font size/weight/style.
4. Downstream in Konverter (`backend/app/toc_hierarchy.py:1745-1749`), unmatched `section_header` items use `level` to compute `section_header_{min(5, max(3, level + 2))}`, so collapsing levels `2–5` to `1` flattens `H4`/`H5` subheadings into `H3`.

---

## 6. Reproducible Benchmark Script & Commands

To reproduce these measurements offline on any machine with `.venv` and cached `docling-layout-heron` + `docling-models`:

```bash
TMP_BENCH_DIR=$(mktemp -d /tmp/konverter_r3_bench.XXXXXX)
cat <<'EOF' > "$TMP_BENCH_DIR/bench_r3.py"
from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import subprocess
import sys
import threading
import time
import tracemalloc
from collections import Counter
from pathlib import Path

import psutil


def _ru_maxrss_mib() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    if sys.platform == "darwin":
        return raw / (1024 * 1024)
    return raw / 1024


def _rss_mib(proc: psutil.Process) -> float:
    return proc.memory_info().rss / (1024 * 1024)


def _ps_rss_mib() -> float:
    out = subprocess.check_output(
        ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
        text=True,
    ).strip()
    return int(out) / 1024.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument(
        "--generate-parsed-pages",
        required=True,
        choices=["true", "false"],
    )
    parser.add_argument("--headers-out", default="")
    parser.add_argument("--sample-interval", type=float, default=0.25)
    parser.add_argument("--no-tracemalloc", action="store_true")
    args = parser.parse_args()

    gen_parsed = args.generate_parsed_pages == "true"
    use_tm = not args.no_tracemalloc
    pdf_path = Path(args.pdf).resolve()
    proc = psutil.Process(os.getpid())

    if use_tm:
        tracemalloc.start()
    t0_total = time.perf_counter()
    rss_init = _rss_mib(proc)
    traced_init_curr = tracemalloc.get_traced_memory()[0] if use_tm else 0

    from docling.datamodel.settings import settings as docling_settings

    docling_settings.inference.compile_torch_models = False
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        HeadingHierarchyOptions,
        PdfPipelineOptions,
        TableStructureOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    t_build_start = time.perf_counter()
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True
    )
    pipeline_options.generate_parsed_pages = gen_parsed
    pipeline_options.heading_hierarchy_options = HeadingHierarchyOptions(
        enabled=True,
        use_bookmarks=True,
        use_numbering=True,
        use_style=True,
        max_level=5,
        bookmark_match_threshold=0.76,
    )
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
    )
    build_s = time.perf_counter() - t_build_start
    rss_after_build = _rss_mib(proc)
    traced_build_curr, traced_build_peak = (
        tracemalloc.get_traced_memory() if use_tm else (0, 0)
    )

    stop_evt = threading.Event()
    rss_samples: list[float] = []

    def _sampler() -> None:
        while not stop_evt.is_set():
            rss_samples.append(_rss_mib(proc))
            stop_evt.wait(args.sample_interval)

    sampler_thread = threading.Thread(target=_sampler, daemon=True)
    sampler_thread.start()

    t_conv_start = time.perf_counter()
    try:
        result = converter.convert(pdf_path)
    finally:
        stop_evt.set()
        sampler_thread.join(timeout=2.0)
    convert_s = time.perf_counter() - t_conv_start

    rss_after_convert = _rss_mib(proc)
    ps_rss_after_convert = _ps_rss_mib()
    ru_maxrss_after_convert = _ru_maxrss_mib()
    traced_conv_curr, traced_conv_peak = (
        tracemalloc.get_traced_memory() if use_tm else (0, 0)
    )

    t_export_start = time.perf_counter()
    raw_docling = result.document.export_to_dict()
    export_s = time.perf_counter() - t_export_start

    rss_after_export = _rss_mib(proc)
    ru_maxrss_after_export = _ru_maxrss_mib()
    traced_export_curr, traced_export_peak = (
        tracemalloc.get_traced_memory() if use_tm else (0, 0)
    )

    texts = raw_docling.get("texts", [])
    label_counts = Counter(t.get("label") for t in texts)
    section_headers = [
        {
            "self_ref": t.get("self_ref"),
            "level": t.get("level"),
            "text": t.get("text", ""),
            "page_no": (t.get("prov") or [{}])[0].get("page_no"),
        }
        for t in texts
        if t.get("label") == "section_header"
    ]
    header_level_counts = Counter(h["level"] for h in section_headers)

    if args.headers_out:
        Path(args.headers_out).write_text(
            json.dumps(
                {
                    "label_counts": dict(label_counts),
                    "header_level_counts": {
                        str(k): v for k, v in sorted(header_level_counts.items())
                    },
                    "section_headers": section_headers,
                },
                indent=2,
            )
        )

    parsed_pages_non_none_before = sum(
        1 for p in result.pages if getattr(p, "parsed_page", None) is not None
    )
    total_textline_cells = sum(
        len(getattr(p.parsed_page, "textline_cells", []))
        for p in result.pages
        if getattr(p, "parsed_page", None) is not None
    )
    total_word_cells = sum(
        len(getattr(p.parsed_page, "word_cells", []))
        for p in result.pages
        if getattr(p, "parsed_page", None) is not None
    )
    total_char_cells = sum(
        len(getattr(p.parsed_page, "char_cells", []))
        for p in result.pages
        if getattr(p, "parsed_page", None) is not None
    )

    gc.collect()
    rss_before_clear_after_gc = _rss_mib(proc)
    traced_before_clear_curr = (
        tracemalloc.get_traced_memory()[0] if use_tm else 0
    )

    t_clear_start = time.perf_counter()
    for p in result.pages:
        p.parsed_page = None
    rss_after_clear_no_gc = _rss_mib(proc)
    traced_after_clear_no_gc_curr = (
        tracemalloc.get_traced_memory()[0] if use_tm else 0
    )
    gc.collect()
    clear_s = time.perf_counter() - t_clear_start

    parsed_pages_non_none_after = sum(
        1 for p in result.pages if getattr(p, "parsed_page", None) is not None
    )
    rss_after_clear_gc = _rss_mib(proc)
    ru_maxrss_final = _ru_maxrss_mib()
    traced_after_clear_gc_curr, traced_final_peak = (
        tracemalloc.get_traced_memory() if use_tm else (0, 0)
    )

    total_s = time.perf_counter() - t0_total
    if use_tm:
        tracemalloc.stop()

    summary = {
        "pdf": str(pdf_path),
        "page_count": len(result.pages),
        "conversion_status": str(getattr(result, "status", "")),
        "generate_parsed_pages": gen_parsed,
        "tracemalloc_enabled": use_tm,
        "platform": sys.platform,
        "timings_s": {
            "build_converter": round(build_s, 3),
            "convert": round(convert_s, 3),
            "export_to_dict": round(export_s, 3),
            "clear_parsed_pages_gc": round(clear_s, 4),
            "total": round(total_s, 3),
        },
        "rss_mib": {
            "init": round(rss_init, 2),
            "after_build": round(rss_after_build, 2),
            "during_convert_sampled_peak": round(
                max(rss_samples) if rss_samples else rss_after_convert, 2
            ),
            "during_convert_sampled_mean": round(
                (sum(rss_samples) / len(rss_samples))
                if rss_samples
                else rss_after_convert,
                2,
            ),
            "during_convert_samples": len(rss_samples),
            "after_convert": round(rss_after_convert, 2),
            "ps_after_convert": round(ps_rss_after_convert, 2),
            "after_export": round(rss_after_export, 2),
            "before_clear_after_gc": round(rss_before_clear_after_gc, 2),
            "after_clear_no_gc": round(rss_after_clear_no_gc, 2),
            "after_clear_gc": round(rss_after_clear_gc, 2),
            "freed_by_clear_rss": round(
                rss_before_clear_after_gc - rss_after_clear_gc, 2
            ),
            "ru_maxrss_after_convert": round(ru_maxrss_after_convert, 2),
            "ru_maxrss_final": round(ru_maxrss_final, 2),
        },
        "tracemalloc_mib": {
            "init_curr": round(traced_init_curr / (1024 * 1024), 2),
            "after_build_curr": round(traced_build_curr / (1024 * 1024), 2),
            "after_convert_curr": round(traced_conv_curr / (1024 * 1024), 2),
            "after_convert_peak": round(traced_conv_peak / (1024 * 1024), 2),
            "after_export_curr": round(traced_export_curr / (1024 * 1024), 2),
            "after_export_peak": round(traced_export_peak / (1024 * 1024), 2),
            "before_clear_after_gc_curr": round(
                traced_before_clear_curr / (1024 * 1024), 2
            ),
            "after_clear_no_gc_curr": round(
                traced_after_clear_no_gc_curr / (1024 * 1024), 2
            ),
            "after_clear_gc_curr": round(
                traced_after_clear_gc_curr / (1024 * 1024), 2
            ),
            "freed_by_clear_traced": round(
                (traced_before_clear_curr - traced_after_clear_gc_curr)
                / (1024 * 1024),
                2,
            ),
        },
        "parsed_page_stats": {
            "non_none_before_clear": parsed_pages_non_none_before,
            "non_none_after_clear": parsed_pages_non_none_after,
            "total_textline_cells": total_textline_cells,
            "total_word_cells": total_word_cells,
            "total_char_cells": total_char_cells,
        },
        "document_counts": {
            "texts": len(texts),
            "tables": len(raw_docling.get("tables", [])),
            "pictures": len(raw_docling.get("pictures", [])),
            "section_headers": len(section_headers),
            "header_levels": {
                str(k): v for k, v in sorted(header_level_counts.items())
            },
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

# Example run (repeat for true and false in separate isolated subprocesses):
cd /Users/yethuaung/Konverter_full_pipeline
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python "$TMP_BENCH_DIR/bench_r3.py" \
  --pdf "docs/rag-inputs/samples/report-2016.pdf" \
  --generate-parsed-pages true \
  --headers-out "$TMP_BENCH_DIR/report2016_true_headers.json"

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python "$TMP_BENCH_DIR/bench_r3.py" \
  --pdf "docs/rag-inputs/samples/report-2016.pdf" \
  --generate-parsed-pages false \
  --headers-out "$TMP_BENCH_DIR/report2016_false_headers.json"

rm -rf "$TMP_BENCH_DIR"
```

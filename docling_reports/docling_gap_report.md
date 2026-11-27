# Docling gap report

Branch `Fix/docling` at `e3e40d8`. Read-only review. No files were changed.

**Scope:** [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) (`_run_docling`, `_run_docling_remote`, and the label and confidence mapping), [runpod_client.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/runpod_client.py), [storage_bucket.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/storage_bucket.py), [docling_worker/](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/handler.py), [toc_hierarchy.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/toc_hierarchy.py) `label_for`, [media.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/media.py), the CI workflow, and the installed Docling 2.121.0 source in `.venv`. I checked the Docling API claims against that installed source.

## Summary

| # | Gap | Area | Severity |
|---|-----|------|----------|
| 1 | `ConversionStatus.PARTIAL_SUCCESS` is accepted silently, so pages can go missing | Robustness | **High** |
| 2 | Local, worker and CI Docling versions differ, and the version is never recorded | Parity | **High** |
| 3 | No real-Docling test anywhere. CI never installs Docling | Testing | **High** |
| 4 | `docling.json` is saved *after* in-place heuristic changes, so it is not raw output | Debuggability | Medium |
| 5 | No `document_timeout`, and Stop cannot interrupt a local conversion | Robustness | Medium |
| 6 | A global lock runs only one conversion at a time, so `KONVERTER_WORKERS>1` does not parse in parallel | Throughput | Medium |
| 7 | Unlocked `pdfium.PdfDocument` at `pipeline.py:2867` can race Docling's pdfium use | Stability | Medium (only when workers > 1) |
| 8 | Remote PDFs and results are never deleted from Supabase Storage | Privacy/cost | Medium |
| 9 | The worker image skips OCR model pre-download | Remote cold start | Medium (only when OCR is on) |
| 10 | Docling features left unused while the pipeline uses heuristics or an LLM for the same job | Quality | Medium |
| 11 | The remote result is not validated, and remote mode hard-codes `device="cuda"` | Parity | Low |
| 12 | `mean_grade` is saved as `"QualityGrade.GOOD"` instead of `"good"` | Data | Low |
| 13 | Checkbox state is lost, and `code`/`reference`/`handwritten_text` fall back to `text` | Mapping | Low |
| 14 | The signed upload URL TTL setting is ignored | Remote | Low |

---

## 1. Partial conversions are accepted silently — High

[docling_runner.py:24-28](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py#L22-L28) calls `converter.convert()` and goes straight to `export_to_dict()`. Docling's `convert()` only raises when the status is **not** `SUCCESS` or `PARTIAL_SUCCESS` (`document_converter.py:582`). So when a page fails, or once a timeout exists (#5), the run returns a document with pages missing. Nothing checks `result.status` or `result.errors`, nothing writes to `warnings.json`, and the reviewer has no sign that content was dropped.

## 2. Version drift between local, worker and CI — High

| Where | Docling version |
|---|---|
| [pyproject.toml](file:///Users/yethuaung/Konverter_full_pipeline/backend/pyproject.toml) `[docling]` extra | `>=2.118.1,<3` (floating) |
| Local `.venv` | **2.121.0** |
| [docling_worker/requirements.txt](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/requirements.txt) | **==2.119.0** |
| `requirements.lock` / `requirements-dev.lock` | not present |

`ARCHITECTURE.md` says the worker parses "identically to local mode". It only shares the runner *code*, not the model or library version. The heuristic passes in `pipeline.py` (about 30) were tuned against whatever Docling produced at the time, so a change in layout labels shifts review items and exported HTML. `run_docling` returns `docling_version`, but `_run_docling` drops it ([pipeline.py:1781-1783](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L1781-L1783)). It is not saved in `doc_confidence.json`, `docling.json` or the record, so you cannot tell which version produced a given output.

## 3. No end-to-end Docling test — High

- CI ([ci.yml:49-53](file:///Users/yethuaung/Konverter_full_pipeline/.github/workflows/ci.yml#L49-L53)) installs only `requirements-dev.lock`, which has no Docling. All pipeline tests use synthetic Docling dicts.
- No tests exist for `docling_runner.run_docling`, `_run_docling_remote`, `storage_bucket.py` or `docling_worker/handler.py`. Only `runpod_client` is tested.
- Result: a Docling upgrade, or a wrong option name (for example `HeadingHierarchyOptions` fields), would only show up at runtime.

## 4. `docling.json` is not the raw Docling output — Medium

`raw_document` is changed in place before it is saved ([pipeline.py:1786-1795](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L1786-L1795)):
- labels are rewritten (`_relabel_misclassified_page_furniture`, page-edge numbers)
- pictures are added (`_synthesize_missing_pictures`, `_recover_page_number_pictures`)
- `meta.konverter_exclude_from_output` flags are set

It is then saved as `docling.json` ([service.py:685](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/service.py#L685)) and served through the "raw `docling.json`" endpoint. So you cannot compare against what Docling actually returned, which makes it harder to debug heuristics or check upgrades.

## 5. No timeout, and Stop does not interrupt a local conversion — Medium

- `PdfPipelineOptions.document_timeout` is not set. The default is `None`, so there is no limit, and a bad PDF can hold the conversion lock forever in local mode.
- In remote mode, cancelling is handled through `on_progress` in `poll`. Local mode has no equivalent, so Stop only takes effect after `convert()` returns.
- Remote mode only has the 1800 s RunPod timeout. A Docling-side `document_timeout` would return partial results with a timeout error instead of losing the whole job, which depends on fixing #1 first.

## 6. Global lock runs one conversion at a time — Medium

[docling_runner.py:23](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py#L23) wraps `convert()` in a single module-wide `_lock`, shared across all converter cache keys. Even with `KONVERTER_WORKERS>1`, local parsing runs one document at a time, and the ETA (`baseline_seconds_per_page`) does not count queue time. This may be deliberate (memory, thread-safety), but it is not documented.

## 7. pdfium thread-safety — Medium (only when workers > 1)

Docling's `PyPdfiumDocumentBackend` uses `docling.utils.locks.pypdfium2_lock` around pdfium calls. `media.py` uses that same lock. However, [pipeline.py:2867](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L2867) (`_build_review_items`) opens and reads `pdfium.PdfDocument` **without** it. With more than one worker, document A building review items can run pdfium calls at the same time as document B in Docling conversion. pdfium is not thread-safe, so this can segfault. The pymupdf calls are a separate library and are not affected.

## 8. Remote storage leak — Medium

`_run_docling_remote` uploads `{document_id}/source.pdf` and gets back `{document_id}/docling.json` ([pipeline.py:1836-1864](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L1836-L1864)). No code deletes either object: not after a successful download, not on failure or cancel, and not when the document is deleted. Every processed PDF stays in the bucket indefinitely.

## 9. Worker cold start when OCR is on — Medium (conditional)

The [Dockerfile](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/Dockerfile) pre-downloads only `layout tableformer`. If `KONVERTER_DO_OCR=true` (default `false`), OCR models are downloaded on the first job of every cold worker, or the job fails if the worker has no outbound network. The download step also ends in `|| echo WARN`, so a failed download does not fail the build and still produces an image.

## 10. Docling features the pipeline does with heuristics instead — Medium

| Docling feature (off) | What the pipeline does instead |
|---|---|
| `do_picture_classification` (logo, icon, chart, diagram, etc.) | Five handwritten passes: `_exclude_repeating_decorative_pictures`, `_exclude_repeating_chapter_divider_pictures`, `_exclude_decorative_heading_accent_pictures`, `_recover_page_number_pictures`, and the chart-axis bare-number filter. Plus a Claude vision call (`diagram_vlm.py`) for diagram text. |
| `do_picture_description` (alt text) | Alt text comes only from captions (`exporter.py:1370`). Uncaptioned figures get no description, a notable gap for an accessibility product. |
| `do_formula_enrichment` (LaTeX) | `formula` blocks are exported as Docling's raw text, which is often garbled for math. |
| `DoclingDocument` `content_layer` (body vs furniture) | Not read. Furniture detection uses labels plus repetition heuristics (`_relabel_misclassified_page_furniture`). |
| `TableStructureOptions.mode` | Not set explicitly, so it depends on the library default and can change between versions (ties to #2). |

These are candidates to evaluate, not drop-in fixes. Each one adds model downloads and GPU time, and would need checking against the existing VLRC fixtures.

## 11. Remote result handling and parity — Low

- `download_json` returns whatever the worker uploaded. A missing `raw_docling` or `cluster_confidences` key causes an unclear `KeyError` at [pipeline.py:1781](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L1781) instead of a clear "worker contract" error.
- `device` is hard-coded to `"cuda"` ([pipeline.py:1853](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L1853)), so `KONVERTER_DOCLING_DEVICE` is ignored in remote mode.
- The worker returns `{"ok": True}` without the version or timing, so the backend has no metadata about the remote run.
- Stop → reprocess race: cancel is best-effort, so a late, abandoned job can overwrite `{document_id}/docling.json` (it uses upsert) while a new job for the same document is running.

## 12. `mean_grade` serialisation — Low

`str(QualityGrade.GOOD)` gives `'QualityGrade.GOOD'` (checked in `.venv`), because `QualityGrade` is a `(str, Enum)` and not a `StrEnum`. [docling_runner.py:34](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py#L34) should use `.value`. Nothing reads `mean_grade` today (`service.py` uses only `mean_score`), so the impact is limited to stored data.

## 13. Label mapping losses — Low

[toc_hierarchy.py:1759-1775](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/toc_hierarchy.py#L1759-L1775):
- `checkbox_selected` and `checkbox_unselected` both become `form`, so whether the box is ticked is lost.
- `code`, `reference`, `handwritten_text`, `chart` and other unrecognised labels fall back to `text`. The code comments say this is deliberate, but it is not reported in `warnings.json`, so the reviewer cannot see it happened.

## 14. Signed upload TTL — Low

`signed_upload_target` accepts `ttl` but Supabase ignores it (as the docstring says). If a RunPod job waits in the queue longer than Supabase's fixed expiry, the worker's upload fails with an error that does not explain why.

---

## Suggested fix order (when code changes are allowed)

1. Fix #1 (status and error check, written to `warnings.json`) and #12. Both are small and only touch `docling_runner.py`.
2. Fix #2 by pinning a single Docling version for the extra and the worker. Also save `docling_version` with each output and fix #4 by saving a copy before changes.
3. Fix #3 with an optional real-Docling smoke test on one small fixture PDF, marked as skippable, plus contract tests for `_run_docling_remote` and the handler.
4. Fix #5, #7 and #8 (timeout and cancel, pdfium lock, bucket cleanup).
5. Run a fixture-based trial of picture classification and description (#10) against the existing heuristics.

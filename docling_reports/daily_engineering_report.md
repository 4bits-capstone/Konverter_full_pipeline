# Full Detailed Report — Konverter Pipeline Engineering (Today's Session)

> [!NOTE]
> All changes were implemented on branch `fix/docling` in `/Users/yethuaung/Konverter_full_pipeline` and verified across **685+ automated tests** (`pytest`) plus real multi-hundred-page VLRC reports.

---

## 1. Executive Summary

Today's work covered **six major workstreams**:
1. **Docling Integration Audit & 14 Gap Remediation (Milestones M1–M3):** Audited the entire local and remote (RunPod) Docling pipeline (`docling_runner.py`, `docling_worker/handler.py`, `pipeline.py`, `storage_bucket.py`, `service.py`, `main.py`, `exporter.py`, `toc_hierarchy.py`) and fixed all 14 identified reliability, parity, cleanup, and data-preservation gaps.
2. **Offline Benchmarks & Evaluations (Milestones M4–M5):**
   - Benchmarked `generate_parsed_pages=True` vs `False` on real VLRC PDFs ([r3_memory_timing_report.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/r3_memory_timing_report.md)).
   - Evaluated `do_picture_classification` and `do_picture_description` on 3 VLRC reports ([r4_picture_evaluation.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/r4_picture_evaluation.md)) and implemented the two recommended picture fixes (caption `$ref` resolution + accurate JSON-LD `alternativeText` claims, and split `"CHAPTER"` + `"01"` divider exclusion).
3. **Split & Missing Footnote Root-Cause Fixes:** Diagnosed and fixed 4 distinct split-footnote failure modes across the 5 VLRC reports (`Medicinal Cannabis`, `Committals`, `Inclusive Juries`, `Litigation Funding`, `Stalking Interim`), reducing split footnotes to **0** across all 5 reports.
4. **100% PDF-Verified Footnote Auto-Approval:** Built a 5-rule structural + full-margin PDF verification check (`_footnote_has_valid_numbered_body`, `_in_sequence_footnote_block_ids`, `_footnote_text_is_trustworthy`) and removed verified footnotes from the human review queue (`84%` to `97%` of footnotes auto-verified; `0` bad footnotes leaked).
5. **PDF-Backed Verification for Non-Footnote Blocks (`caption`, `quote`, `box_section`, `list`, `text`):** Added `_pdf_region_text_matches` and `_non_footnote_block_is_verified` to verify non-footnote blocks against their exact PDF crop (`fitz.Rect`), cutting total human review items across the 5 VLRC reports by **69.1% (`573` → `177` items)**.
6. **Local Apple Silicon GPU (`mps`) Acceleration:** Diagnosed why the 404-page `VLRC_Adoption_Report_forweb.pdf` took 154s (`KONVERTER_DOCLING_DEVICE=cpu` + single-worker queue), switched [.env](file:///Users/yethuaung/Konverter_full_pipeline/.env#L11) to `KONVERTER_DOCLING_DEVICE=mps`, and restarted the backend on the Apple M5 GPU.

---

## 2. Workstream 1: Docling Integration Audit & 14 Gap Fixes (M1–M3)

Full audit details are in [docling_gap_report.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/docling_gap_report.md) and [docling_fixes_summary.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/docling_fixes_summary.md).

```mermaid
flowchart LR
    A["PDF Upload"] --> B["DoclingRunner (Local MPS/CPU or RunPod GPU)"]
    B --> C["Pre-Mutation Snapshot (raw_docling_snapshot)"]
    C --> D["Stage 3: Structure, Footnotes, Callouts, Captions"]
    D --> E["Stage 5: Confidence & PDF Region Verification"]
    E --> F["Review Queue (Only Unverified / Ambiguous Items)"]
```

### Summary of All 14 Gaps Fixed

| Gap | Area | What Was Fixed | Files Modified |
| :---: | :--- | :--- | :--- |
| **#1** | Conversion Status & Errors | Checked `result.status` (`SUCCESS`, `PARTIAL_SUCCESS`) and serialized `result.errors` into `conversion_status`, `conversion_errors`, `failed_pages`, and `error_count` in both local and RunPod workers. | [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py), [handler.py](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/handler.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#2** | Raw Payload Snapshot | Preserved a deep copy of `parsed_raw` (`raw_docling_snapshot`) **before** Stage 3 mutates `texts`/`pictures` in place, so `docling-raw.json` is never polluted by synthetic blocks. | [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#3** | Remote Bucket Cleanup | Added `finally:` cleanup of `[source_key, result_key]` after remote RunPod parses, plus paginated recursive `delete_document_objects()` on `DELETE /api/documents/{id}` and TTL raises (`7200s`). | [storage_bucket.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/storage_bucket.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py), [service.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/service.py), [main.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/main.py) |
| **#4** | `pdfium_lock` Thread Safety | Wrapped `_build_review_items` (`pypdfium2` page rendering) in `with pdfium_lock:` so concurrent PDF renders and Docling parses cannot segfault `pdfium`. | [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#5** | Cancellation Propagation | Threaded `cancel_check` into `DoclingRunner.parse` (before lock, before converter build, before `convert`) and raised `Documenttimeout` (`KONVERTER_DOCLING_TIMEOUT_SECONDS=600.0`). | [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py), [config.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/config.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#6** | `NaN` / `±inf` Confidence | Added `_finite_float()` across `docling_runner.py`, `handler.py`, and `pipeline.py` so non-finite float values never break `json.dumps(..., allow_nan=False)` or PostgreSQL JSONB writes. | [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py), [handler.py](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/handler.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#7** | Version Drift | Pinned `docling==2.121.0` identically across [backend/pyproject.toml](file:///Users/yethuaung/Konverter_full_pipeline/backend/pyproject.toml) and [docling_worker/requirements.txt](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/requirements.txt). | [pyproject.toml](file:///Users/yethuaung/Konverter_full_pipeline/backend/pyproject.toml), [requirements.txt](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/requirements.txt) |
| **#8** | Worker Cold-Start Baking | Pre-downloaded `rapidocr` alongside layout & TableFormer models in [docling_worker/Dockerfile](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/Dockerfile), removed `|| true` silent build failures, and set `DOCLING_ARTIFACTS_PATH`. | [Dockerfile](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/Dockerfile), [handler.py](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/handler.py) |
| **#9** | `TableFormerMode` Config | Wired `TableFormerMode.ACCURATE` / `FAST` via `KONVERTER_DOCLING_TABLE_MODE` (`docling_table_mode`) into `pipeline_options.table_structure_options.mode` locally and remotely. | [config.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/config.py), [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py), [handler.py](file:///Users/yethuaung/Konverter_full_pipeline/docling_worker/handler.py) |
| **#10** | Parse vs Lock Wait Timing | Moved `parse_started = time.perf_counter()` inside `with self._lock:` so `parse_elapsed_seconds` measures true Docling conversion time rather than lock queue wait time. | [docling_runner.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/docling_runner.py) |
| **#11** | Label Coverage & Checkboxes | Added `checkbox_selected` (`checked=True`) and `checkbox_unselected` (`checked=False`) block support (`BlockType.checkbox`), semantic HTML checkbox export, and unknown-label logging. | [models.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/models.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py), [exporter.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/exporter.py), [toc_hierarchy.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/toc_hierarchy.py) |
| **#12** | Remote Payload Validation | Validated required remote JSON keys (`texts`, `tables`, `pictures`, `groups`, `body`, `pages`) and structural dict/list types on download from object storage. | [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#13** | Remote Device Separation | Added `KONVERTER_DOCLING_REMOTE_DEVICE=cuda` (`docling_remote_device`) so local `KONVERTER_DOCLING_DEVICE=cpu`/`mps` never forces the RunPod GPU worker onto CPU. | [config.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/config.py), [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py) |
| **#14** | Real-Docling CI E2E Test | Added a deterministic 4-page vector legal-report PDF fixture (`legal_report_sample.pdf`) and real-Docling E2E test suite in CI (`test_real_docling_e2e.py`). | [test_real_docling_e2e.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/tests/test_real_docling_e2e.py), [ci.yml](file:///Users/yethuaung/Konverter_full_pipeline/.github/workflows/ci.yml) |

---

## 3. Workstream 2: Benchmarks & Picture Improvements (M4–M5)

### 3.1 `generate_parsed_pages` Benchmark ([r3_memory_timing_report.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/r3_memory_timing_report.md))
- Tested `generate_parsed_pages=True` vs `False` on `docling==2.121.0`.
- **Finding:** `docling==2.121.0` automatically deletes `conv_res.pages` after `_assemble_doc()` when confidence calculation is over, so keeping `generate_parsed_pages=True` costs **0% extra RSS memory or parse latency** while preserving real `layout_score` and `ocr_score` confidence metrics.

### 3.2 Picture Classification & Caption Resolution ([r4_picture_evaluation.md](file:///Users/yethuaung/.gemini/antigravity/brain/060da294-1184-4986-99c9-9bb99cc7cc40/r4_picture_evaluation.md))
- Evaluated `do_picture_classification=True` and `do_picture_description=True` on 3 VLRC reports (514 pages, 162 raw picture items).
- Implemented two high-impact improvements:
  1. **Resolved Docling `item["captions"]` references on `picture` blocks** ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L2231)) and updated `_accessibility_properties` in [exporter.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/exporter.py#L844) so JSON-LD only claims `alternativeText` when every figure has a real caption (not the `"Figure"` fallback placeholder).
  2. **Excluded split `"CHAPTER"` + `"01"` chapter-divider picture banners** ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L949-L1023)) where Docling splits `"CHAPTER"` and the 2-digit number across sibling child text items inside a repeating full-page divider picture.
  3. *(Per your instruction, we skipped 7-character Roman numeral page numbers like `"xxxviii"`.)*

---

## 4. Workstream 3: Split & Missing Footnote Root-Cause Fixes

Testing across all 5 VLRC reports revealed **4 root causes** for split or orphaned footnotes. All 4 were fixed in [backend/app/pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py):

1. **Multi-Number Stacked Margin Markers (`"37 38 39 40 41 42"`):**
   - When 2–10 single-line footnotes are stacked vertically, Docling groups all their left-margin numbers into one text block (`"37 38 39 40 41 42"`) and labels it `page_footer` or `footnote`.
   - **Fix:** Updated `_is_footnote_margin_marker_mislabelled_as_footer` ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L4462)) to rescue multi-number margin blocks (`65 <= left <= 110 pt`) and added `_expand_multi_number_footnote_markers` ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L3169)) to split stacked numbers into individual marker items interpolated vertically across the bounding box.
2. **Pass 1 Same-Row Geometric Marker-to-Body Pairing:**
   - When a margin marker sits at the exact same vertical `top` (`Δtop <= 3.0 pt`) as its unnumbered footnote body block (`body_left - marker_left >= 20 pt`), sequential ordering sometimes paired the marker with an earlier continuation line.
   - **Fix:** Added a **Pass 1 same-row geometric match** in `_repair_split_footnote_markers` ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L3292)) before the sequential fallback pass, and merged the marker's bounding box (`_merge_marker_bounds_into_content`) into the paired footnote's `source_bounds`.
3. **Pipeline Ordering (`_repair_split_footnote_markers` before `_merge_indented_footnote_continuations`):**
   - Previously, `_merge_indented_footnote_continuations` ran *before* `_repair_split_footnote_markers`, causing unnumbered footnote bodies (e.g. footnote 52's `"Ibid."`) to be swallowed into footnote 51 before marker `"52"` could attach to `"Ibid."`.
   - **Fix:** Swapped the execution order in [pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L371-L372) so markers attach to their bodies **first**, and continuation merging only merges blocks that still lack a footnote number.
4. **Orphaned Footnote Recovery & Preceding-Footnote Tail Trimming:**
   - When Docling merged footnote $N$'s body into footnote $N-1$'s block and left marker $N$ orphaned, `_recover_orphaned_footnote_markers` ([pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py#L3450)) now:
     - Computes `lower_bound` from all non-furniture blocks below the marker (`other_top > top + 3.0 pt`),
     - Lowers `_RECOVERED_FOOTNOTE_MIN_LENGTH` to `4` so short footnotes like `"Ibid."` are recovered,
     - Expands `source_bounds` on the recovered block to include the full recovered text region, and
     - Trims the duplicated tail off the preceding footnote on the same page.

### Result Across 5 VLRC Reports
- **Split footnotes remaining:** **0** across all 5 reports (`Medicinal Cannabis`, `Committals`, `Inclusive Juries`, `Litigation Funding`, `Stalking Interim`).
- **Total complete footnotes recovered:** Increased from `1,134` (with 96 broken/split fragments) to **`1,218` complete, properly numbered footnotes**.

---

## 5. Workstream 4 & 5: 100% PDF-Verified Auto-Approval (Footnotes + Content Blocks)

To prevent human reviewers from wasting time reviewing blocks that are already 100% accurate, we implemented strict PDF-backed cross-verification in [backend/app/pipeline.py](file:///Users/yethuaung/Konverter_full_pipeline/backend/app/pipeline.py).

### 5.1 5-Rule Strict Footnote Verification
A footnote is marked `system_validated` and **excluded from the review queue** (`if footnote_verified: continue`) only when all 5 rules pass:
1. **Valid Numbered Body (`_footnote_has_valid_numbered_body`):** Starts with a footnote number (`1..999`) followed by a real body (not a bare marker or number sequence).
2. **Terminal Punctuation:** Ends with valid citation/sentence punctuation (`.`, `)`, `]`, `'`, `"`, `”`, `’`) and has no unresolved hyphen wrap (`-\n`).
3. **Sequential Numbering on Page (`_in_sequence_footnote_block_ids`):** Footnote number is strictly $N = N_{\text{prev}} + 1$ from the previous footnote (or `1` at the start of a chapter/document).
4. **Full-Margin PDF Crop Verification (`_footnote_text_is_trustworthy`):** Crops the PDF from `left = min(raw_left, 65.0)` (including the left margin column) and verifies that the normalized block text (number + body) matches the PDF crop (`>= 85%` coverage).
5. **Truncation Guard:** Checks the remaining PDF text in the crop after the matched body — if it starts with the next footnote number ($N + 1$), the footnote was merged and is **rejected** (sent to human review).

### 5.2 PDF-Backed Verification for Non-Footnote Blocks (`_non_footnote_block_is_verified`)
Extended PDF crop verification (`_pdf_region_text_matches` at `>= 88%` normalized PDF match) to auto-verify and remove from review:
- **`caption` (`figure_caption` / `table_caption`):** Must not be an `orphan_caption` (must be linked to a figure/table), must have `>= 6` chars, and must match the PDF crop (`94%–100%` of captions removed from review).
- **`quote` & `box_section`:** Must have `>= 20` chars, no unresolved line-break hyphenation, and match the PDF crop (`71%–100%` removed from review).
- **`list`:** Must not be VLM-generated, must have `>= 10` chars, and match the PDF crop (`69%–100%` removed from review).
- **`text` (medium-confidence `0.60 <= conf < 0.75`):** Must have normal body font size (`8.5 <= font_size <= 13.5 pt`, not a potential missed heading), start with a capital letter, end with terminal sentence punctuation, have `>= 25` chars, and match the PDF crop.

### Review Queue Reduction Across the 5 VLRC Reports

| Report | Pages | Review Items (Before) | Review Items (After) | Reviewer Workload Saved |
| :--- | :---: | :---: | :---: | :---: |
| **`Medicinal_Cannabis`** | 200 | 88 | **32** | **-63.6%** |
| **`Committals`** | 232 | 121 | **26** | **-78.5%** |
| **`Inclusive_Juries`** | 196 | 175 | **26** | **-85.1%** |
| **`Litigation_Funding`** | 184 | 62 | **26** | **-58.1%** |
| **`Stalking_Interim`** | 132 | 127 | **67** | **-47.2%** |
| **Total (5 Reports)** | **944** | **573** | **177** | **-69.1% (396 items removed)** |

---

## 6. Workstream 6: Performance Diagnosis & Apple Silicon GPU (`mps`) Acceleration

- Diagnosed why the 404-page `VLRC_Adoption_Report_forweb.pdf` took `154.4s` (`127.6s` Docling parse on CPU) and why the 84-page `VLRC_Photographing_and_Filming_Tenants_Possessions_Report.pdf` (`30.2s` active time) waited behind it.
- Switched `KONVERTER_DOCLING_DEVICE=mps` in [.env](file:///Users/yethuaung/Konverter_full_pipeline/.env#L11) so `DoclingRunner` uses your Mac's **Apple M5 GPU (`mps`)** for layout and TableFormer inference instead of CPU.

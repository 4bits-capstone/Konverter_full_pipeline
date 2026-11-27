# R4 Offline Feature Evaluation: Docling Picture Classification & Description (Gap #10)

**Date:** 2026-11-22
**Branch / Commit:** `Fix/docling` at `e3e40d8` (read-only evaluation; no repository files modified)
**Docling Version:** `2.121.0` (`HF_HUB_OFFLINE=1`, CPU execution on macOS `darwin`)

---

## 1. Executive Summary & Recommendation

**Recommendation: Keep both `do_picture_classification=False` and `do_picture_description=False` as defaults in `backend/app/docling_runner.py` (no change to default behaviour).**

1. **`do_picture_classification` (`docling-project/DocumentFigureClassifier-v2.5`, EfficientNet-B0, 33.5 MB)** adds negligible CPU time (`-0.6s` to `+6.2s` on 31–68p PDFs) and accurately identifies `flow_chart` (`0.83–0.99`) and `signature` (`0.97–0.999`) figures, **but cannot replace any of `backend/app/pipeline.py`'s 5 picture heuristics, `_synthesize_missing_pictures`, or `diagram_vlm.py`**:
   - It assigns the **`logo`** or **`icon`** label to styled roman/arabic page numbers (`0.84–0.995`), `"Glossary"` heading accent boxes (`0.97–0.98`), and unexcluded chapter dividers (`0.46–0.73`), making it identical at the label level to real publisher/CC logos (`0.42–0.9998`) and clip-art figures (`Capstone` p25 `Figure 5-2`: `icon 0.3117`).
   - It runs only on pictures Docling's layout model already detected: Docling 2.121.0 still misses Figures 1–3 on `report-2016.pdf` pages 93, 95, 96, so `_synthesize_missing_pictures` remains essential.
   - It classifies the whole `PictureItem` image and provides no text-fragment classification (`"diagram"` vs `"content"`) or multi-tier list grouping (`diagram_vlm.py`).
   - Enabling it forces `StandardPdfPipeline.keep_backend = True` (`standard_pdf_pipeline.py:671`), preventing per-page PDF backend unloading on large reports.
2. **`do_picture_description` (`HuggingFaceTB/SmolVLM-256M-Instruct`, 2.62 GB HF hub cache)** is **unfit for production legal/accessibility publishing** in its default configuration:
   - **Severe hallucination & vacuous descriptions:** In 9 empirical image descriptions across 5 fixtures, SmolVLM-256M fabricated non-existent content (`"AWS Lambda"` web page on Konverter's own architecture diagram; `"a picture of a person"` on a bilingual farewell-wishes form; `"book cover"` on a chapter divider; `"Compliance process"` / `"Case hearing"` on VLRC flowcharts), entered 4x repetitive loops, leaked truncated `<end_of_utteranc` tokens in 5/9 outputs, and produced `"In this image I can see the text on the image.<end_of_utteranc"` on the single large uncaptioned VLRC content diagram (`VLRC_Inclusive_Juries` p42).
   - **Coverage mismatch:** Docling's default `picture_area_threshold=0.05` skips 40 of 46 kept pictures (87%) across the 5 VLRC runtime documents; only 1 of 40 uncaptioned kept pictures (`VLRC_Inclusive_Juries` p42) meets `>=5%` page area.
   - **Prohibitive CPU latency:** `+73.7s` to `+103.3s` **per described picture** on CPU (`Capstone` 31p convert time jumped `19.4s -> 225.9s`, `11.7x`).
3. **Higher-leverage non-VLM fixes identified (for future consideration, not implemented here):**
   - `pipeline.py:2118` reads `item.get("caption", "")` rather than `self._item_caption(item, all_items)` (`item["captions"]` refs), causing even genuinely captioned Docling figures (`VLRC_Committals` p41 `Figure 1`, p89 `Figure 2`) to fall back to `"caption": "Figure"` in `exporter.py:1170` and falsely trigger `"alternativeText"` in `exporter.py:1390`.
   - `_exclude_repeating_chapter_divider_pictures` missed all 5 dividers in `VLRC_Stalking_Interim` (`p11,19,31,39,53`) because Docling split `"CHAPTER"` and `"01"` into two separate child items; `_recover_page_number_pictures` missed `"xxxviii"` (`VLRC_Medicinal_Cannabis` p40) because `_BARE_PAGE_NUMBER_RE` caps roman numerals at `{1,6}` characters (`"xxxviii"` is 7).

---

## 2. Offline Model Cache & Environment Verification

1. **Pre-cache command:** Ran `.venv/bin/python -m docling.cli.models download picture_classifier smolvlm`:
   - Succeeded (`exit 0`). Downloaded `docling-project--DocumentFigureClassifier-v2.5` (`32 MB`, 8 files) and `HuggingFaceTB--SmolVLM-256M-Instruct` (`3.3 GB` including `2.8 GB` in `onnx/`, 38 files) into `/Users/yethuaung/.cache/docling/models/`.
2. **Cache-path resolution detail (`HF_HUB_OFFLINE=1`):**
   - Because `backend/app/docling_runner.py` leaves `pipeline_options.artifacts_path = None` (default), Docling's `resolve_model_artifacts_path()` (`docling/models/inference_engines/vlm/_utils.py:120-122`) calls `huggingface_hub.snapshot_download(repo_id=...)` against `~/.cache/huggingface/hub/` rather than `~/.cache/docling/models/`.
   - When `onnx/*` was initially omitted from `~/.cache/huggingface/hub/`, `HF_HUB_OFFLINE=1` raised `IncompleteSnapshotError` (`24 file(s) are missing (onnx/decoder_model_merged.onnx, ...)`), proving that `artifacts_path=None` expects a complete HF snapshot (`2.62 GB` for `SmolVLM-256M-Instruct`).
   - After populating complete snapshots in `~/.cache/huggingface/hub/`, **all 4 models** (`docling-layout-heron`, `docling-models`, `DocumentFigureClassifier-v2.5`, `SmolVLM-256M-Instruct`) resolved under `HF_HUB_OFFLINE=1`, and every benchmark run executed 100% offline.
3. **Engine & backend observations in Docling `2.121.0`:**
   - `do_picture_classification` defaults to `DocumentPictureClassifierOptions.from_preset("document_figure_classifier_v2")` (`docling-project/DocumentFigureClassifier-v2.5`, 26 classes, `TransformersImageClassificationEngine`).
   - `do_picture_description` defaults to `PictureDescriptionVlmEngineOptions.from_preset("smolvlm")` (`HuggingFaceTB/SmolVLM-256M-Instruct`, `picture_area_threshold=0.05`, `scale=2.0`, `prompt="Describe this image in a few sentences."`, `AutoInlineVlmEngine` -> `TransformersVlmEngine` on `device="cpu"`).
   - Setting either flag `True` sets `self.keep_backend = True` in `StandardPdfPipeline._init_models()` (`standard_pdf_pipeline.py:667-675`), retaining every page's PyPDFium2 backend in memory across the whole document instead of calling `page._backend.unload()` per page.

---

## 3. Existing Corpus Baseline: VLRC Runtime `docling.json` Artifacts

Inspection of the 5 unique existing VLRC runtime `docling.json` files (`backend/runtime/documents/`) shows how Konverter's current heuristics behave before any new Docling options:

| Document (`doc_id`) | Pages | Total Pics | Excluded | Kept | Captioned Kept | Uncaptioned Kept | Kept `>=5%` Page Area | Bare-Number Pic Children | `diagram_vlm` Frag Candidates (`>=2` non-num kids) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `VLRC_Committals` (`a1be5f4c`) | 184 | 13 | 3 | 10 | 3 | 7 | 3 | 2 | 4 (`p1`, `p3`, `p41`, `p89`) |
| `VLRC_Stalking_Interim` (`e1d46c42`) | 68 | 13 | 1 | 12 | 0 | 12 | 0 | 6 | 1 (`p3`) |
| `VLRC_Inclusive_Juries` (`41096af8`) | 284 | 29 | 20 | 9 | 1 | 8 | 1 | 16 | 0 |
| `VLRC_Medicinal_Cannabis` (`96aaba81`) | 288 | 27 | 19 | 8 | 1 | 7 | 1 | 18 | 1 (`p3`) |
| `VLRC_Litigation_Funding` (`7daea05b`) | 192 | 12 | 5 | 7 | 1 | 6 | 1 | 4 | 1 (`p3`) |
| **Total** | **1,016** | **94** | **48** | **46** | **6** | **40** | **6** | **46** | **7** |

Key baseline findings:
- **87.0% of kept figures (40/46) are uncaptioned**, and **only 6/46 (13.0%)** meet Docling's default `picture_area_threshold=0.05` (most kept pictures are small publisher crests, CC icons, signatures, or cover/divider graphics `<5%` area).
- **Caption bug in `pipeline.py:2118`:** Even for the 6 captioned figures (`VLRC_Committals` `blocks.json` `#/pictures/6, 10, 11`), `pipeline.py:2118` reads `item.get("caption", "")` instead of `item["captions"]` refs, so `block["text"] == ""` and `exporter.py:1170` emits `"caption": "Figure"`.
- **Two narrow heuristic edge cases observed in runtime artifacts:**
  - `VLRC_Stalking_Interim` p11, 19, 31, 39, 53 (`132–137 x 113–131pt`): Docling split `"CHAPTER"` and `"01"` into 2 separate child items, so `_CHAPTER_DIVIDER_TEXT_RE` (`^\s*chapter\s+\d+\s*$`) matched none of them.
  - `VLRC_Medicinal_Cannabis` p40 (`37.9 x 10.7pt`, PyMuPDF text `"xxxviii\n"`): escaped `_recover_page_number_pictures` because `_BARE_PAGE_NUMBER_RE` restricts roman numerals to `{1,6}` characters (`"xxxviii"` is 7).

---

## 4. Benchmark Measurements: Runtime & Memory Overhead (Offline CPU)

All runs executed in isolated subprocesses with `HF_HUB_OFFLINE=1`, `device="cpu"`, `do_ocr=False`, `do_table_structure=True`, `generate_parsed_pages=True`, and `HeadingHierarchyOptions` matching `docling_runner.py`.

| Fixture & Scope | Mode | Init (s) | Convert (s) | Total (s) | RSS After Init (MB) | RSS After Convert (MB) | Max RSS (MB) | Peak Traced (MB) | Pictures (Described) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Capstone Final Report Template.pdf` (31p full) | `baseline` | 10.893 | 19.355 | 30.249 | 507.25 | 1677.45 | 2617.72 | 307.13 | 4 (0) |
| `Capstone Final Report Template.pdf` (31p full) | `classify` | 8.995 | 25.579 | 34.573 | 500.78 | 1220.38 | 2216.06 | 308.34 | 4 (0) |
| `Capstone Final Report Template.pdf` (31p full) | `describe` | 8.896 | **225.853** | 234.749 | 506.78 | 1324.11 | 2212.36 | 323.01 | 4 (**2**) |
| `VLRC_Stalking_Interim` (68p full) | `baseline` | 9.821 | 44.456 | 54.276 | 498.97 | 1779.00 | 2712.36 | 331.44 | 13 (0) |
| `VLRC_Stalking_Interim` (68p full) | `classify` | 10.562 | 43.872 | 54.434 | 501.02 | 1674.72 | 2555.02 | 333.40 | 13 (0) |
| `VLRC_Committals` (`p1-3,10,12,16,20,41,89,184`, 10p) | `baseline` | 8.871 | 12.805 | 21.676 | 506.41 | 1613.98 | 1760.22 | 288.69 | 13 (0) |
| `VLRC_Committals` (`p1-3,10,12,16,20,41,89,184`, 10p) | `classify` | 11.423 | 13.755 | 25.178 | 506.59 | 1690.77 | 1931.80 | 293.96 | 13 (0) |
| `VLRC_Committals` (`p1,41,89`, 3p) | `describe` | 9.562 | **231.732** | 241.294 | 504.11 | 994.47 | 1906.12 | 308.53 | 4 (**3**) |
| `report-2016.pdf` (`p1,9,93-96,164`, 7p) | `classify` | 12.864 | 15.731 | 28.595 | 421.86 | 994.91 | 1510.09 | 290.97 | 4 (0) |
| `report-2016.pdf` (`p1,9,93-96,164`, 7p) | `describe` | 9.529 | **80.027** | 89.556 | 501.20 | 1879.70 | 2016.70 | 305.47 | 4 (**1**) |
| `VLRC_Inclusive_Juries` (`p1-3,14,16,31,42,135,259,283-284`, 11p) | `classify` | 8.516 | 13.735 | 22.252 | 507.23 | 1647.02 | 1813.75 | 306.92 | 12 (0) |
| `VLRC_Inclusive_Juries` (`p42`, 1p) | `describe` | 9.822 | **73.661** | 83.483 | 503.95 | 998.53 | 1636.12 | 304.50 | 1 (**1**) |
| `VLRC_Stalking_Interim` (`p1,11`, 2p, `area_threshold=0.0`) | `describe` | 9.315 | **160.671** | 169.986 | 507.36 | 1197.61 | 2064.67 | 302.34 | 2 (**2**) |
| `VLRC_Medicinal_Cannabis` (`p1,10,12,20,40`, 5p) | `classify` | 9.073 | 10.685 | 19.757 | 503.98 | 1608.80 | 1658.83 | 306.83 | 6 (0) |

**Overhead takeaways:**
- **`do_picture_classification`:** Negligible CPU runtime overhead (`+0.95s` on `VLRC_Committals` 10p/13 pics; `-0.58s` noise on `VLRC_Stalking_Interim` 68p/13 pics; `+6.22s` on `Capstone` 31p/4 pics) and `+1–2 MB` traced Python heap. Main architectural cost is `keep_backend=True` retaining page PDF backends across long documents.
- **`do_picture_description`:** Dominates runtime at **~74–103s per described picture on CPU** (44–80s/image even on 1–3 page runs), while adding ~2.62 GB of model artifacts in HF hub cache.

---

## 5. Evaluation of `do_picture_classification` vs. Picture Heuristics & `diagram_vlm.py`

### 5.1 Observed Predictions Across Heuristic Categories

| Category / Heuristic | Fixture & Picture Example | Size & Area | Current Pipeline Decision | `DocumentFigureClassifier-v2.5` Top-1 (Top-2) | Can Classification Replace Heuristic? |
|---|---|---|---|---|---|
| **Undetected Figures** (`_synthesize_missing_pictures`) | `report-2016.pdf` p93, p95, p96 (Figures 1–3) | `>=80pt` embedded images | **Synthesized** via PyMuPDF `get_images()` | **Not detected at all** (`0` pictures on p93/95/96) | **No.** Classifier only scores layout-detected `PictureItem`s. |
| **Page-Number Pictures** (`_recover_page_number_pictures`) | `VLRC_Committals` p16 (`"xiv"`), p20 (`"xviii"`), `Medicinal_Cannabis` p20 (`"xviii"`), p40 (`"xxxviii"`), `Stalking` p54 (`"44"`) | `14–38 x 11pt` (`<=0.08%`) | Excluded (except `"xxxviii"` due to `{1,6}` regex cap) | `logo` (`0.9234`, `0.9917`, `0.9949`, `0.9950`); `icon` (`0.8368` on `"44"`) | **No.** Indistinguishable from real logos/icons without PDF text re-read. |
| **Heading Accent Boxes** (`_exclude_decorative_heading_accent_pictures`) | `"Glossary"` accent on `Committals` p12, `Juries` p16, `Cannabis` p12 | `88–120 x 23–33pt` (`0.4–0.8%`) | Excluded via `>=0.5` overlap with `_ALWAYS_TOP_LEVEL` | `logo` (`0.9727`, `0.9777`, `0.9773`) | **No.** Same `logo` label/confidence as genuine crests/logos. |
| **Chapter Dividers** (`_exclude_repeating_chapter_divider_pictures`) | `Juries` p31 (`CHAPTER 01`), p135 (`CHAPTER`); `Stalking` p11, 19, 31, 39, 53 (unexcluded) | `132–137 x 113–131pt` (`3.1–3.5%`) | `Juries` p31 excluded; `Stalking` 5 dividers missed (`"CHAPTER"` + `"01"` split) | `logo` (`0.4223` on `Juries` p31; `0.4638–0.7273` on `Stalking` p11–53; `icon` runner-up `0.12–0.39`) | **Partial signal only.** Cannot safely drop `logo` globally without dropping cover/publisher logos (`0.42–0.9998`). |
| **Repeating Decorative** (`_exclude_repeating_decorative_pictures`) | Tiny `<=30pt` template graphics across `>=3` pages (`Juries` p259 `28.1x19.0` `"231"` appeared once -> kept) | `<=30pt` | Excluded only if `>=3` distinct pages at rounded bbox | `icon` (`0.9399` on `Juries` p259) | **No.** Single-page visual class has no cross-page repetition signal. |
| **Cover Graphic w/ Contact Text** (`diagram_vlm.classify_picture_text_fragments` & bare-number filter) | `VLRC_Committals` p1 cover arrows (12 VLRC address/phone lines nested inside) | `400 x 677pt` (`53.9%`) | Kept; bare-number filter skips numbers; `diagram_vlm` preserves `"content"` lines | `icon` (`0.7455`), `bar_chart` (`0.0879`), `flow_chart` (`0.0860`) | **No.** Does not classify nested text fragments as `"content"` vs `"diagram"`. |
| **Complex Flowcharts / Diagrams** (`diagram_vlm` + chart-axis filter) | `Committals` p41 (`Figure 1`, 40 kids), p89 (`Figure 2`, 55 kids); `Juries` p42 (uncaptioned); `Capstone` p13, p16 | `35–67%` page area | Kept; `diagram_vlm` excludes internal labels as `"diagram"` | `flow_chart` (`0.9923`, `0.9947`, `0.8324`, `0.9959`, `0.9947`) | **Complementary pre-filter only.** High-precision `flow_chart` ID, but does not group or filter children. |
| **Signatures & Forms / Screenshots** | `report-2016` p9; `Committals` p10; `Juries` p14; `Cannabis` p10; `report-2016` p94 ("My Wish" form) | `1.0–51.3%` | Kept (signatures have captions; p94 kept as picture) | `signature` (`0.8131`, `0.9996`, `0.9995`, `0.9749`); p94 `screenshot_from_computer` (`0.8420`) | Useful metadata only; no heuristic targets these for exclusion. |
| **Small Placeholder / Ambiguous Figure** | `Capstone` p25 `Figure 5-2` (drafting-tools clip-art icon under a Gantt-chart template caption) | `140 x 116pt` (`3.25%`) | Kept (captioned figure) | `icon` (`0.3117`), `engineering_drawing` (`0.2552`), `screenshot_from_computer` (`0.2232`) | **Risk if filtering `icon`:** blindly excluding `icon` drops real figure blocks. |

### 5.2 Comparison with `diagram_vlm.py` Capabilities
`backend/app/diagram_vlm.py` performs **two** distinct tasks that `do_picture_classification` does not address:
1. **`classify_picture_text_fragments` (`diagram_vlm.py:230-263`):** Given `>=2` non-caption, non-bare-number text fragments nested inside a `PictureItem`, uses Claude (`claude-sonnet-4-5-20250929`, 150 DPI page PNG) to label each fragment `"diagram"` (excluded so chart axis/box text doesn't become floating paragraphs) vs `"content"` (preserved, e.g., `VLRC_Committals` p1 address/phone over cover art). Fails closed to keeping all fragments when `claude_api_key` is empty.
2. **`classify_diagram_grouping` (`diagram_vlm.py:160-185`):** Maps multi-tier diagram bullet items to preceding headers by index when `pipeline._split_diagram_list_by_preceding_headers` cannot resolve positions geometrically — operating on Docling's `list` + `section_header_*` blocks rather than `PictureItem`s at all.

**Verdict on `do_picture_classification`:** Cannot replace any of the 5 heuristics or `diagram_vlm.py`. Could only serve as a future **advisory metadata tag** or **pre-filter** (e.g., skipping `diagram_vlm` calls when a picture is `signature` `>0.95`), which does not justify changing default behaviour today given `keep_backend=True`.

---

## 6. Evaluation of `do_picture_description` vs. Caption-Only Alt Text (`exporter.py` / `preview_html.py`)

### 6.1 Current Konverter Alt-Text Behaviour (Verified in Source & Runtime)
- `pipeline.py:2115-2118` constructs picture blocks with `text = resolver.output_text(item)` and `if label == "picture" and not text: text = str(item.get("caption", "")).strip()`. Because Docling stores captions in `item["captions"]` (`$ref` list) rather than `item["caption"]`, `block["text"]` is **`""` even on captioned figures** (confirmed in `VLRC_Committals/blocks.json` for `#/pictures/6, 10, 11`).
- `exporter.py:1170` (and `923` inside callout boxes) sets `"caption": text or "Figure"`.
- `preview_html.py:687,696` writes `<img class="docling-figure-image" src="..." alt="{caption}"><figcaption>{caption}</figcaption>`.
- `exporter.py:1390-1401` computes `all_figures_captioned = all(str(f.get("caption", "")).strip() for f in figures)` — which trivially evaluates to `True` whenever `caption` defaults to `"Figure"`, falsely asserting `"alternativeText"` in Schema.org JSON-LD.
- Currently, **neither `pipeline.py` nor `exporter.py` reads `picture.meta.description`** (`annotations`), so enabling `do_picture_description=True` alone would produce descriptions in `raw_docling` with zero effect on exported HTML unless downstream code were also changed.

### 6.2 Empirical `SmolVLM-256M-Instruct` Output Quality & Failure Modes

| Fixture & Page | Visual Ground Truth (Verified via Rendered PNG) | `area_fraction` | Verbatim `SmolVLM-256M-Instruct` Description | Quality Assessment |
|---|---|---:|---|---|
| `Capstone` p13 (`Figure 1. System Architecture`) | Konverter 5-stage architecture diagram (`Supabase`, `AWS Lightsail`, `RunPod`, `Document Intelligence Pipeline`, `Outputs`) | 0.4182 | `"The image is a web page that is part of a web application. The page is titled \"AWS Lambda\" ... Below the title, there is a section labeled \"AWS Lambda\" ... 1. **Main Content Area**: ... 2. **Footer Section**:   - The footer section contains the ma"` | **Complete hallucination.** Zero mention of AWS Lambda in diagram; truncated mid-word at `200` tokens. |
| `Capstone` p16 (`Figure 4-6: Deployment Diagram`) | Deployment diagram (`Frontend (React Build)` -> `CPU Pod` -> `Serverless GPU Endpoint`, `Docker Hub`, `OpenAI API`, `WordPress`, `Supabase`) | 0.3479 | `"In the center of the image is the frontend (React Build) which is connected to the CPU Pod which is connected to the Backend GPU (app/data). The Backend GPU is connected to the Docker Hub which is connected to the OpenAI API which is further connected to the WordPress (client site) which is connected to the Docker Hub which is then connected to the Docker Hub which is further connected to the Docker Container which is then connected to the CPU Pod.<end_of_utteranc"` | **Wrong topology + loop + token leak.** Hallucinates `Backend GPU (app/data)` and `Docker Container`, misroutes edges, repeats `Docker Hub`, leaks `<end_of_utteranc`. |
| `Capstone` p1 & p25 | RMIT logo (`1.09%`); `Figure 5-2` icon (`3.25%`) | 0.0109, 0.0325 | `null` (skipped by `picture_area_threshold=0.05`) | Skipped by default threshold. |
| `report-2016.pdf` p94 (Excerpt of "My Wish" form) | Bilingual (EN/ZH) Confirmation & Witness form boxes (text fields for name, DOB, signature, address) | 0.5127 | `"This is a page of a book. On this page, there are some text and a picture of a person.<end_of_utteranc"` | **Hallucination + token leak.** No person image exists; misses form purpose entirely. |
| `VLRC_Committals` p1 (Cover art) | Vertical white arrows on blue background (2 up, 1 right-turn, 1 capped) | 0.5394 | `"The image consists of three horizontal white arrows pointing in the same direction... The image does not contain any text, numbers, or other objects...<end_of_utteranc"` | **Factually wrong orientation** (`horizontal` vs vertical/branching) + token leak. |
| `VLRC_Committals` p41 (`Figure 1`) | Present committal flowchart (11 grey boxes, `Commencement`, `Filing hearing`, `Plea brief`, `Trial on indictment`) | 0.6099 | `"The image is an infographic titled \"Commencement of a proceeding chapter 2\" which is part of a larger document titled \"Compliance process\"... **Filing Hearing part 4.2**: This section is connected to both \"Compliance process\" and \"Compulsory examination process\"... This sectio"` | **Hallucinates `"Compliance process"`**, loops on connections, omits 90% of flowchart, truncates mid-word. |
| `VLRC_Committals` p89 (`Figure 2`) | Proposed pre-trial case management flowchart (15 boxes, `FILING HEARING`, `ISSUES HEARING`, `County Court`, etc.) | 0.6739 | `"The image is a legal document titled \"Informant commences proceedings by filing charges\"... below the header, there is a subheader that reads \"Court matters, charges\"... - The \"Filing Hearing\" section is further divided into two parts: \"Filing Hearing\" and \"Case hearing\"."` (repeated 4x) | **Hallucinates `"Case hearing"`**, enters 4x repetition loop, misses flowchart structure. |
| `VLRC_Inclusive_Juries` p42 (Uncaptioned diagram) | 5-step chevron flow: `1 Random selection...`, `2 Determination...`, `3 Summons`, `4 The jury pool`, `5 Selection... -> Jury empanelled` | 0.4726 | `"In this image I can see the text on the image.<end_of_utteranc"` | **Vacuous + token leak.** Zero useful alt text on the exact uncaptioned content figure where alt text was most needed. |
| `VLRC_Stalking_Interim` p1 (`threshold=0.0`) | VLRC logo (`83.1x54.6pt`) | 0.0091 | `"In this image I can see the text on the red background.<end_of_utteranc"` | Vacuous + token leak. |
| `VLRC_Stalking_Interim` p11 (`threshold=0.0`) | Red-orange chapter divider box printing `CHAPTER 01` | 0.0311 | `"The image is a book cover. The background of the book cover is red... The text \"1\" is written below the number \"01\".<end_of_utteranc"` | Hallucinates `"book cover"` and extra `"1"` + token leak. |

**Root cause of `<end_of_utteranc` leak:** `stage_model_specs.py:1484-1515` defines `PICTURE_DESC_SMOLVLM` without `stop_strings=["<end_of_utterance>"]` (unlike `VLM_CONVERT_SMOLDOCLING` at line 1089), so SmolVLM-256M's end-of-turn marker leaks verbatim into `description` when tokenized/truncated.

---

## 7. Final Conclusion

1. **Keep `do_picture_classification=False` and `do_picture_description=False` by default.** Neither feature is a safe drop-in replacement for Konverter's existing heuristics or `diagram_vlm.py`.
2. **Do not adopt `SmolVLM-256M-Instruct` for accessibility alt-text:** In WCAG 2.1 legal publishing, hallucinated descriptions (`"AWS Lambda"`, `"a picture of a person"`, `"Compliance process"`, `"Case hearing"`) and `<end_of_utteranc` artifacts are **worse** for screen-reader users than caption-derived alt text or flagging uncaptioned figures for human review, and incur ~75–103s/image CPU latency plus 2.62 GB model weight overhead.
3. **Recommended non-Docling-default improvements (for a separate engineering milestone if desired):**
   - Wire Docling's existing `item["captions"]` refs in `pipeline.py:2118` and fix `exporter.py:1390` so `"Figure"` fallback does not falsely claim `"alternativeText"`.
   - Update `_exclude_repeating_chapter_divider_pictures` (`pipeline.py:494`) to handle split `"CHAPTER"` + `"01"` children, and extend `_BARE_PAGE_NUMBER_RE` (`pipeline.py:64`) roman numerals beyond 6 chars (`{1,8}`).

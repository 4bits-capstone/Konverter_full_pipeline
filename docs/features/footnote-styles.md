# How Konverter keeps footnote styles (italic / bold)

**Problem:** Docling's PDF backend never fills in text formatting, so italics (case names, titles) are lost at extraction.

**Fix:** read the styling back from the PDF itself. Docling's text stays authoritative; we only add *ranges* over it.

## Flow

1. **Extract** — Docling parses the PDF as usual (text, page, `source_bounds` per footnote block).
2. **Recover** — `pipeline.py::_attach_text_styles` runs right after Docling. For each `footnote` block it opens that page's region in the PDF with pymupdf and reads the font of each character (`italic` flag / font name contains "italic"/"oblique"; `bold` likewise). `text_styles.py::extract_style_ranges` aligns those characters to Docling's text.
3. **Attach** — on the block:
   - `styles`: `[{start, end, italic, bold}, ...]` — offsets into the text
   - `styles_text`: the exact string the offsets were computed against
4. **Export** — `exporter.py` copies `styles` onto each footnote in `structured.json` via `styles_for_text`.
5. **Render** — `preview_html.py` calls `render_styled`, which HTML-escapes the text and wraps ranges in `<em>` / `<strong>`.

## Safety rules

- **Fails closed:** if the PDF region's characters don't match the block's text exactly (ignoring whitespace), no styles are returned. A misaligned span can never italicise the wrong words.
- **Never rewrites text:** ranges only, no replacement text.
- **Text must be unchanged:** `styles_for_text` returns styles only while the block's text still equals `styles_text`.

## Known limits

- **Edited footnote** → text no longer equals `styles_text` → renders plain (italics dropped).
- **Split footnote** (one block holding several notes, split by `_split_footnote_entries`) → offsets no longer line up → renders plain.
- Footnotes only; body text, headings and tables don't get style recovery.
- Footnote *detection* recall is a separate, still-open problem (Marker 15 Oct benchmark: recall 0.12).

## Files

`backend/app/text_styles.py` · `backend/app/pipeline.py` · `backend/app/exporter.py` · `backend/app/preview_html.py` · tests: `backend/tests/test_text_styles.py`

## Check on a processed document

Footnote blocks in `backend/runtime/documents/<id>/blocks.json` with a `styles` key are the ones that kept italics. On Inclusive Juries (284 pages), 491 of 1,188 footnotes had styles.

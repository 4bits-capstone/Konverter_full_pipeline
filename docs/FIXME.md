# System Fixes:

## Backend Fixes

Do a test of everything in the backend

- Adjust confidence threshold (60%) — currently 0.60; needs a target value decided
- ~~Fix 'key recommendations' section~~ — not in the UI anymore (deliberately removed in a past redesign, only dead CSS remains); nothing to fix
- ~~'Cite this report' output is broken~~ — fixed: citation is now always-visible text (works even when embedding sites strip scripts), and the copy button no longer hangs silently in sandboxed contexts
- ~~Verify changing label structures works ie. Table -> Footnote is broken: it changes it to text~~ — verified already fixed: a structure-label change stores the chosen label, and a table converted to a footnote stays a footnote in the publication (the same for the other real labels). Covered by `test_structure_label_change_keeps_the_chosen_label_instead_of_plain_text`.
- ~~Adding more items to a list is broken~~ — verified already fixed: the review list editor appends a row, and saving re-parses that line into the list that gets exported. Covered by `test_adding_a_list_item_is_kept_and_exported` and the Review page test "adds a list item and saves it with the rest of the list".
- ~~We should still render the pictures, tables, and headings despite their confidence score because they are very important and cannot be missed.~~ — verified already fixed: pictures, tables, and headings scored below the medium threshold still enter the review queue and the publication. The 0.60 threshold was not changed. Low-confidence body text still stays pending for review. Covered by `test_low_confidence_pictures_tables_and_headings_stay_in_review_and_export`.
- ~~Manually edited footnotes lose style metadata and become plain text~~ — fixed: the review editor shows italic/bold as real formatting (Italic/Bold buttons, Ctrl/⌘+I and Ctrl/⌘+B) for footnotes, body text, quotes, captions and headings, opens with the styles detected from the PDF, and saves them with the text. Use the Review page "Validation" filter -> "Manually reviewed" to find hand-edited footnotes.

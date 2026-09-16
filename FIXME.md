# System Fixes:

## Backend Fixes

Do a test of everything in the backend

- Adjust confidence threshold (60%) — currently 0.60; needs a target value decided
- ~~Fix 'key recommendations' section~~ — not in the UI anymore (deliberately removed in a past redesign, only dead CSS remains); nothing to fix
- ~~'Cite this report' output is broken~~ — fixed: citation is now always-visible text (works even when embedding sites strip scripts), and the copy button no longer hangs silently in sandboxed contexts
- Verify changing label structures works ie. Table -> Footnote is broken: it changes it to text
- Adding more items to a list is broken
- We should still render the pictures, tables, and headings despite their confidence score because they are very important and cannot be missed.
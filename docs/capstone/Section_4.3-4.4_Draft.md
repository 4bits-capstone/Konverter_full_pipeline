Draft to fill the placeholder on page 14 of the Capstone Final Report Template, between §4.2 (Current Scope / Figure 1) and the existing §4.3 "Split compute architecture and rationale". This proposes two new subsections, which would push the existing §4.3 to §4.8 down to §4.5 to §4.10. It's written from direct work on the extraction pipeline and review interface this cycle, so the model and front-end owners should still check it against their own account before it goes into the final document.

---

## 4.3 AI layout-parsing model

The document-parsing stage is built on Docling, an open-source document-layout model, rather than a model trained in-house. Docling converts each page of a PDF into a structured intermediate representation: text blocks, tables, pictures, and page furniture such as headers, footers, and page numbers, each with a bounding box and a raw structural label. This choice followed a comparison against a fine-tuned LayoutLMv3 pathway earlier in the project. Docling was adopted for the shipped system because it reduced dependency complexity while giving comparable or better results on the report structures in scope, and its use is reflected in Figure 1 and Table 4-2.

Docling's own layout classification is not treated as final. A post-processing layer sits between the raw Docling output and the review queue, correcting a set of structural error patterns found through testing against real VLRC reports rather than a generic benchmark:

**Heading hierarchy.** Docling's section-header detection does not by itself establish which heading is H1 versus H5. A resolver reconstructs this by matching detected headings against the report's own printed table of contents, correcting cases where Docling under- or over-promotes a heading's level.

**Footnote integrity.** A chain of targeted repairs addresses footnote-specific failure modes: markers split across two blocks, wrapped continuation lines mistaken for a new footnote, and two adjacent footnotes extracted in reverse order. For a footnote marker Docling captured with no body text at all, the system recovers the missing text by independently re-reading that exact region of the source PDF's own text layer, so nothing is ever invented.

**Decorative and furniture elements.** Repeating template graphics, page numbers rendered as part of a stylised chapter-opening design and misclassified as embedded pictures, and repeating chapter-divider graphics are identified and excluded from the reviewable output, so they don't appear as spurious low-confidence items.

**AI-vision-assisted structure correction.** For a narrow set of cases that a purely geometric rule cannot resolve, for example a diagram whose grouped content (a hierarchy chart with several tiers, each with its own list of items) gets flattened by Docling into a single undifferentiated list, a vision-capable language model is used to classify the structure directly from the rendered page image. This use is deliberately restricted to classification and grouping decisions: which extracted item belongs under which heading, and whether a text fragment nested inside a picture is part of that picture's own diagram content or independent body text. The model is never asked to transcribe or invent text, so a wrong classification can misroute content for review but can never introduce fabricated wording into a legal document.

Every extracted block carries a confidence score, and this score is what determines whether it reaches a human reviewer at all (§2.3). A block scoring above the high-confidence threshold is accepted automatically. Anything below it is queued for review and banded as medium or low confidence to help a reviewer prioritise.

## 4.4 Review interface design

The reviewer console follows a four-stage workflow of Upload, Review, Metadata, and Preview. It is implemented as a React single-page application (Table 4-2) and served from the same frontend described in Figure 1.

**Upload** accepts one or more PDFs and tracks each as an independent processing job, so a reviewer can begin working on the first completed document while others are still being parsed.

**Review** is the core of the interface. Extracted content is queued by confidence band (high, medium, or low), and each flagged item is shown with the original PDF region displayed directly alongside the extracted text or table, so a reviewer can compare the source and the output without leaving the page. A reviewer can accept an item as is, edit its extracted text, table data, or structure label, or remove it altogether. Changing a structure label, for example reclassifying a block from plain text to a heading, or from a low-confidence picture to an image upload, changes which correction editor is shown and how that block is rendered in the generated output. Footnotes follow a distinct rule: a footnote is only pre-accepted once an independent re-read of that exact region of the source PDF's text layer agrees with what Docling extracted. This is a system decision made before any person has seen the item, and it is recorded as such, kept separate from a reviewer's own accept, edit, or reject action, so the audit trail (§4.6) never conflates the two.

**Metadata** presents a small, fixed set of publication fields, namely title, author, date, jurisdiction, and citation, for confirmation or correction ahead of publication.

**Preview** shows the fully assembled accessible HTML output for a final visual check, and is also where final approval is granted. Approval is gated: it cannot be completed while blocking review items remain unresolved. This is also the point at which the accessible HTML, Schema.org JSON-LD, and structured JSON exports described in §4.2 are generated, making the document eligible for publication (§4.7).

Every accept, edit, and approval action is written to the tamper-evident audit log described in §4.6, giving the review process the same provenance guarantee that the audit design section describes for the system as a whole: a verifiable record of who did what and when.

# Engineering Journal — Ye Thu Aung (s4066945)
## SSET Capstone — Konverter (Komosion / Victorian Law Reform Commission)
### Programming Project 2 | 27 May – 17 September 2026

*Drafted from the official meeting minutes register (Meetings 1–19) plus direct technical work on the extraction pipeline, footnote handling, and pipeline evaluation. Review and personalize before submission — this is a first draft, not a final record of your own voice.*

---

### Week 1: 27 May – 2 June 2026

**Key project activities:** Kickoff meeting with Komosion (Meeting 1). Team identified inconsistent labels, weak classes, and compute limits obstructing model training. Agreed to begin collaborative annotation and restart model training to address overfitting. Began investigating Docling as a candidate extraction framework alongside continued layout-model experiments.

**Key individual contributions and accomplishments:** Assigned to integrate OCR into the extraction pipeline and test a fresh model training iteration (Action 1.3).

**Major issues:** Annotation inconsistency and weak-class coverage were blocking reliable model evaluation from the outset. Scope of "AI-ready output" was still undefined at this stage.

---

### Week 2: 3 – 9 June 2026

**Key project activities:** Meeting 2 compared Docling extraction (with additional heading classification) against the LayoutLMv3 pathway. Established that Docling's section-header detection does not by itself resolve H1–H5 hierarchy — font cues, layout rules, and an LLM-assisted pass were proposed as supplementary methods. Existing annotations were mapped to a new, consistent label standard rather than restarting from scratch.

**Key individual contributions and accomplishments:** Continued model improvement work on Colab, tracking F1 score across training iterations (Action 2.2).

**Major issues:** No architecture decision yet between the two extraction pathways; the team needed comparative results before committing.

---

### Week 3: 10 – 16 June 2026

**Key project activities:** Meeting 3 confirmed the team's primary pathway: the layout model, with Docling retained for extraction support and preprocessing. Evaluation showed Docling was faster in testing but struggled with heading hierarchy even after additional training. Annotation of a ~30-document corpus became the immediate priority.

**Key individual contributions and accomplishments:** Prepared learning curves and per-class error analysis to support the pathway decision (Action 3.2); began training and evaluating a larger model on cloud infrastructure (Action 3.4).

**Major issues:** Heading-hierarchy resolution remained unsolved regardless of which extraction pathway was chosen — flagged as a cross-cutting problem, not specific to either architecture.

---

### Week 4: 17 – 23 June 2026

**Key project activities:** Meeting 4 reported 34 annotated documents and development F1 of ~0.94 (micro) / 0.93 (macro), with images and tables still identified as weak classes. A double-page image bug causing incorrect bounding boxes was identified. DeepSeek-based hierarchy resolution was scoped for integration.

**Key individual contributions and accomplishments:** Added weak-label examples to improve image/table coverage, retrained the model, and diagnosed and fixed the double-page bounding-box processing bug (Action 4.1).

**Major issues:** The double-page bug was initially ambiguous between a data-pipeline fault (Label Studio upload) and a genuine model fault — required isolating root cause before it could be fixed correctly.

---

### Week 5: 24 – 30 June 2026

**Key project activities:** Meeting 5 confirmed a hybrid extraction design: the base layout model handling text and headings, Docling handling tables and images. Large-model testing was discontinued once the base model was judged sufficient. Vy Huynh joined as UI/UX designer.

**Key individual contributions and accomplishments:** Began development of the hybrid extraction pipeline jointly with Zyle Estacion (Action 5.1), combining the two models' outputs into a single extraction path.

**Major issues:** Metadata extraction (citation and jurisdiction rules) still relied on hardcoded assumptions specific to VLRC's report format — flagged as a generalisation risk for future clients.

---

### Week 6: 1 – 7 July 2026

**Key project activities:** Meeting 6 found the hybrid pipeline improved table detection but introduced new label noise. The team simplified the approach to generic heading detection followed by a separate hierarchy-resolution step. Frontend architecture was confirmed: React frontend, Python/FastAPI backend.

**Key individual contributions and accomplishments:** Refactored generic heading detection and table handling jointly with Zyle Estacion to reduce the label noise introduced by the hybrid approach (Action 6.1).

**Major issues:** The hybrid pipeline's own table-detection gains had a direct cost in heading-label reliability — a genuine trade-off, not a simple bug, requiring a design change rather than a patch.

---

### Week 7: 8 – 14 July 2026

**Key project activities:** Meeting 7 reported a hierarchy resolution result of 98.6% on the development test set. OCR-generated symbol noise remained a residual source of output errors. Aung Su Pyae demonstrated the first upload and review interface; feedback requested clearer review guidance, source-PDF access, and safer correction/rejection recovery.

**Key individual contributions and accomplishments:** Worked with Zyle Estacion to remove residual OCR noise from extracted output and finalise the hybrid pipeline for handoff to the review interface (Action 7.4).

**Major issues:** The review workflow did not yet distinguish an automated system decision from a human reviewer's own decision — a distinction later proven important for trust in the audit trail.

---

### Week 8: 15 – 21 July 2026

**Key project activities:** Two meetings this week. Meeting 8 (15 Jul) confirmed the team would prioritise native Docling extraction to reduce dependency complexity on the layout model, with heading hierarchy and post-processing still requiring further work; a demonstration pipeline freeze was planned ahead of the first client presentation. Meeting 9 (21 Jul) was the first client meeting: the team demonstrated the full document-conversion workflow directly to Victoria Kyriakopoulos of VLRC, covering multi-document upload, confidence-based review, source comparison, corrections, and final approval, with accessible HTML and machine-readable JSON-LD as outputs.

**Key individual contributions and accomplishments:** Froze the demonstration pipeline ahead of the client session to ensure a stable, reproducible state for the first live client demo (Action 8.6) — a meaningful responsibility given this was the team's first direct exposure to the actual client.

**Major issues:** Balancing pipeline stability against continued development pressure — freezing the pipeline the same week a client demo was delivered meant no further extraction changes could be tested until after the meeting.

---

### Week 9: 22 – 28 July 2026

**Key project activities:** Meeting 10 (29 Jul, industry partner) reviewed the VLRC client session positively, particularly the review workflow and end-to-end vision, while flagging landing-page readability for refinement. Internally, Docling, metadata, and JSON-LD generation were still not fully joined into one path, and inconsistent labels and list formats were affecting evaluation quality.

**Key individual contributions and accomplishments:** Contributed to hierarchy optimisation and inference-API integration work alongside Zyle Estacion (Action 10.2), addressing part of the disjointed Docling/metadata/JSON-LD pipeline.

**Major issues:** Confidence thresholds for auto-acceptance were still being assessed against a single example document rather than a representative sample — a methodological gap the team would return to twice more before resolving it.

---

### Week 10: 29 July – 4 August 2026

**Key project activities:** Meeting 11 reported that backend-to-frontend integration and JSON-LD generation were functional, though editing lists, tables, and footnotes still produced formatting issues. The team agreed to formally compare Marker 2 against the existing extraction pipeline on five selected reports, contingent on first fixing ground-truth consistency and evaluator correctness. A client-testable MVP was targeted for Week 20.

**Key individual contributions and accomplishments:** Assigned jointly with Zyle Estacion to run the comparison between Marker 2 and the existing pipeline on five reports (Action 11.4); contributed to reviewing label-specific confidence scores ahead of any threshold change (Action 11.5).

**Major issues:** The team noted that low-confidence footnotes were "often correct" — meaning the confidence score itself was not a reliable proxy for correctness, a finding that shaped later footnote-specific fixes rather than a general threshold adjustment.

---

### Week 11: 5 – 11 August 2026

**Key project activities:** Meeting 12 reported that Marker 2 showed potential speed improvements over the existing pipeline, but format mismatches and evaluation issues meant no final migration decision could yet be made; component licensing for Marker 2 required separate documentation and verification. The review interface was redesigned to reduce workflow complexity, adding batch approval, unified editing, and provenance tracking.

**Key individual contributions and accomplishments:** Supported repair of the evaluation mismatches surfaced by the Marker 2 comparison so that a fair, apples-to-apples result could eventually be reached, and continued non-VLRC report testing to identify pipeline gaps outside the primary corpus (Action 12.6, team-shared).

**Major issues:** A migration decision on Marker 2 remained unresolved due to format incompatibility between its output and the team's existing schema — this would recur as an open item through several more meetings before being deferred as a future option rather than adopted.

---

### Week 12: 12 – 18 August 2026

**Key project activities:** Meeting 13 demonstrated the fully integrated workflow — upload, review, and export — alongside an admin dashboard linked to backend records. The final demo-planning decision retained Docling over Marker 2, citing existing customisation and hosting constraints; Marker 2 and the Cosmograph knowledge-visualisation concept were kept as future options rather than adopted immediately. A sample report produced 227 review flags, prompting investigation into footnote-specific scoring and thresholds.

**Key individual contributions and accomplishments:** Reviewed a full sample document end-to-end and worked on refining footnote review flags jointly with Zyle Estacion and Aung Su Pyae (Action 13.2) — directly following on from Week 10's finding that footnote confidence scores were unreliable.

**Major issues:** 227 review flags on a single sample report was identified as a high review burden; the audit trail could record individual events but lacked a complete document version history or a bulk-change view, limiting how efficiently a reviewer could work through that volume.

---

### Week 13: 19 – 25 August 2026

**Key project activities:** Meeting 14 (progress review and first rehearsal) reported roughly a 60% reduction in the review queue after implementing footnote auto-acceptance, though other medium- and low-confidence items still required human review. The team rehearsed the full product narrative and identified WordPress staging issues (script and JSON-LD embedding) as unresolved. A cost slide was requested ahead of the final client presentation.

**Key individual contributions and accomplishments:** Worked on chatbot voice-interruption handling (Action 14.6), and contributed to preparing the cost slide and revising the demo narrative as a shared team task (Action 14.7).

**Major issues:** The redesigned review interface had removed a visual landing-page confirmation step that reviewers relied on for reassurance — flagged as a regression to fix before the client-facing rehearsal, not just a cosmetic issue.

---

### Week 14: 26 August – 1 September 2026

**Key project activities:** No formal meeting recorded this week (between Meeting 14 on 28 Aug and Meeting 15 on 2 Sep) — team time went into implementing the prior week's rehearsal feedback: migrating processing to serverless/separate services, revised UI export labels, and WordPress script/JSON-LD fixes ahead of the next rehearsal.

**Key individual contributions and accomplishments:** Continued footnote and chatbot refinement work in preparation for the upcoming rehearsal cycle, building on Weeks 12–13's footnote-flag investigation.

**Major issues:** Infrastructure split between lightweight always-on services and heavier on-demand processing remained a work in progress, with continuous-server cost and image size raised as open infrastructure concerns.

---

### Week 15: 2 – 8 September 2026

**Key project activities:** Four meetings this week, reflecting the final rehearsal push and the second live client presentation. Meeting 15 (2 Sep, 8am) was cut short when the full team could not attend and was rescheduled the same day. Meeting 16 (2 Sep, 10am) rehearsed the complete upload-to-output workflow, including confidence-based review, footnote auto-acceptance, five-field metadata review, and chatbot/export features; feedback focused on tightening the presentation to 20–25 minutes. Meeting 17 (3 Sep) ran a full rehearsal covering interface and backend responsibilities, explained the footnote acceptance exception to high/medium/low confidence handling, and identified a need for reliable timing evidence and testing on non-legal document types. Meeting 18 (4 Sep) was the second live client demonstration, presented jointly to VLRC (Victoria Kyriakopoulos, Natalie Young) and John Hamilton of MinterEllison — covering the full pipeline from upload to publishing, with a live table/list error in the preview used to illustrate the real consequence of an incorrect review decision.

**Key individual contributions and accomplishments:** Prepared the web-publishing demonstration segment and gathered timing evidence to support the presentation's efficiency claims (Action 17.4); cleaned demo files, refined chatbot citation behaviour, and scoped additional tests (Action 16.4).

**Major issues:** Client feedback at the live demonstration raised two specific, unresolved product questions: how footnote auto-acceptance is explained to a non-technical reviewer, and whether formatting fidelity (particularly italics) survives correction and re-approval — both were carried forward as open action items rather than resolved in the room.

---

### Week 16: 9 – 15 September 2026

**Key project activities:** Meeting 19 (10 Sep) completed direct WordPress publishing (Save Draft and Publish Live), with selective publishing for other client use cases deferred as future work. The team began preparing formal handover documentation — repository links, local setup, environment configuration, deployment and restart instructions, health checks, and a short recorded user workflow. A security concern was raised: unauthorised API-key usage had been identified, with an investigation assigned but not concluded in the meeting.

**Key individual contributions and accomplishments:** Reported on footnote detection and chatbot timeframe restrictions, implemented footnote font-style extraction, and was assigned jointly with Linn Htin Nyo to investigate the API-key misuse and document mitigations (Action 19.2) — a security-critical task carried into the following week. Also assigned to complete remaining footnote UI and system checks ahead of the showcase (Action 19.3).

**Major issues:** The API-key misuse investigation had not established a root cause or completion by the end of this week's meeting — a genuinely open security item requiring dedicated follow-up before the showcase, not a routine cleanup task.

---

### Week 17: 16 – 17 September 2026 (Showcase week)

**Key project activities:** Final pre-showcase engineering pass, closing out the security investigation and the last two of this cycle's technical gaps: extraction fixes for structural cases the pipeline had not previously handled correctly (a diagram whose grouped content was extracting as one flattened list instead of correctly separated sections; page-number graphics on front-matter pages being misclassified as embedded pictures instead of recognised as text; repeated chapter-divider graphics also being misclassified as content requiring review; and diagram-internal text leaking into the body output as disconnected floating fragments). Completed the API-key misuse investigation. Finalised handover documentation for the incoming team, including known limitations and explicit gaps still requiring a decision (e.g. a missing backend build file, an unresolved heading-duplication edge case in one client document). Ran a comparative evaluation of the shipped pipeline against Datalab's Marker on the same real client document, to ground the project's competitive positioning claims in an actual result rather than only public vendor material.

**Key individual contributions and accomplishments:** Diagnosed and fixed four distinct structural extraction defects directly in the pipeline, each backed by regression tests; completed and documented the API-key security investigation with Linn Htin Nyo; authored the handover documentation covering setup, deployment, known limitations, and open items; ran and documented a three-case structural benchmark against Marker to support later market-positioning work.

**Major issues:** One structural defect (a duplicate heading in a previously-approved client document) was found to persist even after a full, careful re-extraction, and was documented as a known limitation for the incoming team rather than resolved outright, since a fix would touch shared heading-detection logic used by every document — too large a change to make safely this close to handover. Showcase held 17 September, 09:30–15:30.

---

*End of journal. Weeks are anchored to the meeting register in Meeting_Minutes.pdf; entries for weeks without a formal meeting are drawn from the surrounding weeks' action items and the technical work log. Recommend cross-checking each week's "individual contributions" line against your own memory before submission — this draft reflects the documented record, not a substitute for your own account.*

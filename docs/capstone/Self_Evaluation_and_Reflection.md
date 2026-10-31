# Student Self-Evaluation and Reflection
## SSET Capstone Project — Konverter (4 Bits | Komosion | RMIT Vietnam)
### Ye Thu Aung (s4066945)

*Drafted from the project's official meeting minutes (Meetings 1–19, 27 May – 10 September 2026) and the accompanying engineering journal. Review and adjust before submission — self- and peer-assessment should reflect your own honest judgement, not just a documented record.*

---

### 1. What are your main tasks and responsibilities within this Capstone project?

My work on Konverter centred on the document-extraction pipeline and its correctness, rather than the frontend or infrastructure layers. Specifically:

- **Model training and evaluation**: integrating OCR into the extraction path, running and retraining models on Colab and cloud infrastructure, tracking F1 score, and producing per-class error analysis to guide architecture decisions (Weeks 1–4).
- **Hybrid and native pipeline development**: building the hybrid extraction pipeline that combined the base layout model with Docling, then refactoring it down to native Docling extraction with a separate heading-hierarchy resolution step once the hybrid approach's trade-offs became clear (Weeks 5–8).
- **Footnote detection and correctness** — the single most recurring thread across the project. This spanned OCR-noise removal, review-flag refinement, investigating why confidence scores were an unreliable proxy for footnote correctness, implementing footnote auto-acceptance (which cut the review queue by roughly 60%), and later diagnosing and fixing several distinct structural extraction defects (diagram content flattening into a single list instead of correctly separated sections, page-number graphics and repeated chapter-divider graphics being misclassified as pictures needing review, and diagram-internal text leaking into the body as disconnected fragments).
- **Pipeline evaluation**: leading, with Zyle Estacion, the formal comparison between Marker 2 and the existing pipeline on five reports, and later a targeted structural benchmark against Marker to ground the project's own claims in a real result.
- **Security response**: jointly investigating and documenting a real unauthorised API-key usage incident found late in the project, alongside Linn Htin Nyo.
- **Chatbot and export features**: voice-interruption handling, citation refinement, and web-publishing demonstration preparation.
- **Handover documentation**: authoring the setup, deployment, and known-limitations documentation for the team taking the system over after the capstone.

---

### 2. What are your completed works and contributions to the project until this point? Rate 0–10.

**Completed work:**
- Shipped the OCR integration and multiple retraining iterations that resolved the project's early weak-class and double-page bounding-box problems.
- Co-built the hybrid extraction pipeline, then the refactor to native Docling + hierarchy resolution once the hybrid trade-offs (better tables, worse headings) became clear — a real architectural pivot, not a minor tweak.
- Diagnosed and fixed the footnote confidence-score reliability problem, then implemented auto-acceptance logic that measurably reduced human review workload (~60% reduction reported at Meeting 14).
- Found and fixed four distinct, previously-unhandled structural extraction defects late in the project (diagram/list flattening, misclassified page-number and chapter-divider graphics, diagram-text leakage), each with its own regression test.
- Co-led the Marker 2 comparison and a later structural benchmark against Marker, providing the project with real comparative evidence rather than only vendor claims.
- Investigated and documented the API-key security incident to closure.
- Authored the handover documentation, including an explicit, honest list of known limitations and unresolved items for the incoming team.

**Self-rating: 8/10.**

Rationale: the footnote-correctness and structural-extraction work in particular went beyond fixing symptoms — it involved finding real root causes (e.g. that low confidence didn't mean low correctness; that a "picture" label from Docling wasn't reliable evidence of an actual embedded image) and building fixes that were tested and verified against live client documents, not just plausible-looking patches. I'm not rating this a 9 or 10 because some of my own assigned items (the Marker 2 evaluation-mismatch repair, non-VLRC document testing) were shared or supported rather than solely owned, and because one structural defect (a heading duplication in a previously-approved client document) remains unresolved and was documented as a known limitation rather than fixed — an honest account should reflect that not everything reached closure.

---

### 3. Briefly describe the main tasks and responsibilities of other student members. Rate 0–10.

**Aung Su Pyae (s4087009)** — Frontend and UI/UX lead. Built the upload interface, the review interface (source comparison, correction workflow, structure-label editing), the metadata review screens, and the WordPress direct-publishing (Save Draft / Publish Live) flow. Also documented UI requirements and framework constraints early in the project and led the client-facing demonstrations of the review workflow at both live sessions.
**Rating: 8/10** — consistently the one demonstrating the product live to the client, and the review interface went through multiple genuine simplification iterations based on direct feedback rather than staying static.

**Linn Htin Nyo (s4037889)** — Infrastructure, administration, and knowledge-feature exploration. Investigated Cosmograph as a knowledge-discovery visualisation concept, worked on serverless migration, built the admin dashboard with role-based access and audit records, and co-investigated the API-key security incident in the final weeks.
**Rating: 8/10** — the audit-record and role-based-access work directly addressed a client-raised accountability concern, and the security co-investigation was completed to closure under real time pressure near handover.

**Zyle Estacion (s4064846)** — Extraction pipeline and metadata lead. Evaluated Docling, implemented metadata extraction logic, worked on heading-hierarchy resolution, co-led the Marker 2 comparison, and mapped existing annotations to the evolving label standard across several architecture changes.
**Rating: 8/10** — carried a lot of the pipeline-evaluation decision-making (Docling vs. layout model vs. Marker 2) that other work, including my own footnote fixes, ultimately depended on.

*(Ratings here reflect my own perspective as a teammate working alongside them on a shared pipeline; a fuller assessment should also draw on their own self-evaluations and the supervisors' observations.)*

---

### 4. Briefly describe critical issues that need to be addressed to further support the project's progression and completion.

- **The Docling vs. Marker 2 decision was never fully closed.** Marker 2 showed real speed advantages but was blocked by format mismatches and incomplete evaluation; the team's decision to retain Docling for the final demo was made for hosting and customisation reasons, not because Marker 2 was proven worse. This should be revisited with a controlled, apples-to-apples benchmark before any future migration decision.
- **One structural defect remains unresolved by design, not by oversight.** A heading-duplication issue in a previously-approved client document persists even after full re-extraction, because a real fix would touch heading-detection logic shared by every document — correctly judged too risky to change this close to handover, but it needs dedicated time and full regression testing in the next phase.
- **Client-raised product questions from the final demo remain open**: how footnote auto-acceptance is explained to a non-technical reviewer, and whether formatting fidelity (particularly italics) survives correction and re-approval. Both were acknowledged live but not resolved before showcase.
- **Validation has been almost entirely within VLRC's own legal-report corpus.** The pipeline's behaviour on other document domains (health, education, or other government agencies mentioned as future test cases) is largely untested, which is a real risk if the product is positioned more broadly than this one client.
- **The handover itself has open items**, documented explicitly rather than hidden: a backend build file the incoming team needs to locate or recreate, and infrastructure decisions (serverless split, continuous-server cost) that were still "in progress" as of the last recorded meeting.


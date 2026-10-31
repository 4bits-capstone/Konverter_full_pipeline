# RAG test fixtures

`fixtures/*.json` are trimmed excerpts of real converter output (`structured.json`'s
`publication.sections`, nothing else), produced by running the three benchmark PDFs
through `KonverterPipeline.process` + `build_publication` with no human review:

| file | source | what it keeps |
|---|---|---|
| `act_front.json` | Cemeteries and Crematoria Act 2003, v038 | cover, Table of Provisions (first 12 rows), ss 1–4 |
| `act_part6.json` | same | Part 6, ss 73–80 (includes ss 77 and 79) |
| `act_end.json` | same | ss 180–186, Schedule 1 start, Endnotes start |
| `report.json` | VLRC Funeral and Burial Instructions report (2016) | all 25 recommendations, chapter 6 up to para 6.25 |
| `paper.json` | VLRC consultation paper (2015) | chapters 7–8 and the appendix list of questions |
| `documents.json` | benchmark manifest | doc ids, types, versions, dates |

The Act is split in three files because each slice is contiguous on its own: the chunker
requires section numbers to keep climbing. The PDFs are not committed.

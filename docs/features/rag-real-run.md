# Real ingest run: commands and checks

Run from the repo root with the venv active:

    cd /Users/yethuaung/Konverter_full_pipeline
    source .venv/bin/activate

## 1. Dry runs (already done and matching)

    python -m app.rag ingest docs/rag-inputs/samples --manifest docs/rag-inputs/documents.json --only act@038 --only paper --dry-run

    python -m app.rag ingest --from-store 08c753bf34104f18a1dd6b443856a4ba --as report --manifest docs/rag-inputs/documents.json --dry-run

Expected: act@038 308 chunks / 137 links, paper 287 / 4 links, report 836 / 0 links.

## 2. Real run (this order)

    python -m app.rag ingest docs/rag-inputs/samples --manifest docs/rag-inputs/documents.json --only act@038 --only paper

Expected footer: embedding calls: 10, texts embedded: 595

    python -m app.rag ingest --from-store 08c753bf34104f18a1dd6b443856a4ba --as report --manifest docs/rag-inputs/documents.json

Expected footer: embedding calls: 14, texts embedded: 836

If a run stops partway (for example a rate limit), run the same command again: finished batches are kept.

## 3. Check in the Supabase SQL editor

    select doc_id, version, count(*) from rag_chunks group by 1,2 order by 1;
    -- act 038: 308, paper '': 287, report '': 836

    select count(*) from rag_links;                                  -- 141
    select count(*) from rag_chunks where metadata ? 'text_source';  -- 16
    select count(*) from rag_chunks where embedding is null;         -- 0

## 4. Idempotence: run both commands from step 2 again

Expected footer both times: embedding calls: 0, texts embedded: 0

## 5. First question (Q07, gold act:s-79)

    python -m app.rag ask "Can a right of interment be transferred, and is there a limit on the price?" --doc act

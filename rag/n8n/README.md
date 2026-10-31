# n8n: Ask workflow

`konverter-rag-ask.json` answers a question from the ingested documents: webhook -> embed the question -> `match_chunks` ->
DeepSeek -> JSON answer. It is the n8n twin of `python -m app.rag ask` (same prompt, same retrieval filters, same answer rules,
same response JSON), and a test runs the workflow's JavaScript against the Python code to keep them identical.

Not in this workflow: **link expansion** (`--links`, Python only) and **ingest** (run `python -m app.rag ingest`; there is no n8n ingest
trigger in this round).

## Files

| File | What |
|---|---|
| `konverter-rag-ask.template.json` | Hand-edited source. Everything except the system prompt. |
| `konverter-rag-ask.json` | **Generated**: the template with the system prompt from `backend/app/rag/prompts/answer_system.txt`. Import this one. |

Regenerate after editing either input: `python -m app.rag n8n-export` (`pytest` fails if the committed export is stale).
Edit the prompt only in `answer_system.txt`.

## Setup

1. **Database**: run `python -m app.rag sql` (it renders `backend/sql/006_rag_chunks.sql` for your embedding size), paste the output into the Supabase SQL
   editor, then ingest documents with `python -m app.rag ingest`. The workflow calls the RPC `match_chunks(query_embedding, k, doc_ids, as_of_date, meta_filter)`.
2. **Import** `konverter-rag-ask.json` in n8n (Workflows -> Import from file). It is imported inactive.
3. **Credentials** (the file contains none; each node shows a placeholder to pick):

   | Node | n8n credential type | Set it to |
   |---|---|---|
   | Webhook | Header Auth | Name `X-Konverter-Key`, Value: a long random secret. Callers send this header. |
   | Embed question | Header Auth | Name `Authorization`, Value `Bearer <your Voyage key>` (or your OpenAI key if `embed_provider` is `openai`) |
   | match_chunks | Supabase API | Your project's host and the **service role** key (the RPC is granted to `service_role` only) |
   | DeepSeek | Header Auth | Name `Authorization`, Value `Bearer <your DeepSeek key>` |

4. **Config node** (the only place settings live; the workflow does not read `$env`, which n8n can block):

   | Field | Value |
   |---|---|
   | `supabase_url` | `https://<your-project>.supabase.co` |
   | `embed_provider`, `embed_model`, `embed_dim` | Must equal `RAG_EMBED_PROVIDER`, `RAG_EMBED_MODEL`, `RAG_EMBED_DIM` used at ingest. A different model or size gives meaningless similarities, so do not change one side only. |
   | `llm_url`, `llm_model`, `llm_max_tokens` | DeepSeek chat completions endpoint and model (defaults match `DEEPSEEK_BASE_URL`, `RAG_LLM_MODEL`) |
   | `top_k`, `min_similarity` | Default number of chunks, and the similarity floor (`RAG_TOP_K`, `RAG_MIN_SIMILARITY`) |

5. **Activate** and call it:

   ```bash
   curl -X POST "$N8N_URL/webhook/konverter-rag-ask" \
     -H "X-Konverter-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"question": "Can a right of interment be transferred?", "doc_ids": ["act"], "as_of_date": "2025-10-22"}'
   ```

## Request

`{ "question": "...", "doc_ids": ["act"], "as_of_date": "YYYY-MM-DD", "k": 8, "meta_filter": {"review_status": "reviewed"} }`.
Only `question` is required (max 2000 characters). `k` is 1-50. `as_of_date` returns only text in force on that date (`effective_from` inclusive,
`effective_to` exclusive). `meta_filter` is a flat object matched against chunk metadata. A bad request gets HTTP 400 `{ "error": "..." }`.

## Response

```json
{
  "answer": "... [act:s-79]",
  "citations": ["act:s-79"],
  "unsupported_citations": [],
  "abstained": false,
  "abstain_reason": "no_passages | model | no_valid_citations | llm_error",
  "retrieved": ["act:s-79"],
  "scores": [{"chunk_id": "act@038:s-79", "section_id": "act:s-79", "similarity": 0.61}],
  "ranked": [{"chunk_id": "...", "section_id": "...", "similarity": 0.61}],
  "latency_ms": 2140, "model": "deepseek-chat", "usage": {}
}
```

- `abstain_reason` and `error` appear only when relevant. When nothing passes the similarity floor the answer is "Not found in the provided documents." and the
  model is not called.
- `citations` are section IDs that were actually retrieved (or listed in a chunk's `contains`). Invented ones are dropped into `unsupported_citations`. An answer
  left with no valid citation becomes an abstention.
- `retrieved` / `scores` are what the model saw (after the floor). `ranked` is everything `match_chunks` returned, before the floor: measure retrieval on that.

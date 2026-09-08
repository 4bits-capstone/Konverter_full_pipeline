# Supabase schema

Run these in the Supabase SQL editor, in order, against the project referenced
by `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` in `.env`. Each is idempotent
(`create ... if not exists` / `create or replace`), so re-running is safe.

| File | Purpose |
| --- | --- |
| `001_documents_and_audit_log.sql` | Core `documents` and `audit_log` tables. |
| `002_audit_log_hash_chain.sql` | Trigger that chains each `audit_log` row's hash to the previous row's, so a row edited or deleted after the fact is detectable. |
| `003_audit_log_lockdown.sql` | Revokes `update`/`delete` on `audit_log` from client roles — it's insert-only. |
| `004_wordpress_publications.sql` | `wordpress_publications` table: durable record of every WordPress publish, used to warn before creating a duplicate page. |

`verify_audit_log_chain.sql` is a read-only diagnostic, not part of the setup
sequence — run it any time to check the `audit_log` hash chain is intact.

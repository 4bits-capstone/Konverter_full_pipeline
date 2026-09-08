-- Diagnostic, not a migration: run manually to confirm the audit_log hash
-- chain (see 002_audit_log_hash_chain.sql) hasn't been tampered with.
-- Every row should show chain_ok = true.
select
  id,
  action,
  created_at,
  prev_hash,
  entry_hash,
  case
    when lag(entry_hash) over (order by id) is null
      then prev_hash = repeat('0', 64)   -- first row of the chain
    else prev_hash = lag(entry_hash) over (order by id)
  end as chain_ok
from audit_log
order by id;

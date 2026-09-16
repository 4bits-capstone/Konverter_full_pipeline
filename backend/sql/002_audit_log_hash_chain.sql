-- Tamper-evident audit log: each row's hash chains from the previous row's
-- hash, so any row edited or deleted after the fact breaks the chain
-- (detectable with verify_audit_log_chain.sql).
create extension if not exists pgcrypto;

create or replace function audit_hash_chain()
returns trigger as $$
declare
  last_hash text;
begin
  select entry_hash into last_hash
    from audit_log order by id desc limit 1;
  new.prev_hash := coalesce(last_hash, repeat('0', 64));
  new.entry_hash := encode(
    digest(
      new.prev_hash ||
      coalesce(new.document_id::text,'') ||
      coalesce(new.actor_id::text,'') ||
      new.action ||
      coalesce(new.detail::text,'') ||
      coalesce(new.created_at::text, now()::text),
      'sha256'),
    'hex');
  return new;
end;
$$ language plpgsql;

create trigger audit_hash_chain_trigger
  before insert on audit_log
  for each row execute function audit_hash_chain();

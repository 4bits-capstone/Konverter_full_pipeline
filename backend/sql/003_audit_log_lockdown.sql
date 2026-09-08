-- audit_log is append-only: no client role may modify or remove a row once
-- written, only ever insert new ones.
revoke update, delete on audit_log from anon, authenticated;

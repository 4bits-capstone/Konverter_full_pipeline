-- Lock documents and audit_log down to the service role, the same pattern
-- as wordpress_publications (004). Only the backend touches these tables,
-- using SUPABASE_SERVICE_ROLE_KEY (which bypasses RLS); the frontend never
-- queries them directly, so no policies are needed. With RLS on and no
-- policies, the public anon key and signed-in users can't read or write
-- any rows through the Supabase API.
--
-- RLS was already switched on for these tables in the production project's
-- dashboard; this file makes that part of the schema so a rebuilt project
-- gets it too. Safe to re-run.
alter table documents enable row level security;
alter table audit_log enable row level security;
alter table wordpress_publications enable row level security;

-- Defence in depth: even if a permissive policy were ever added by mistake,
-- client roles have no table privileges to use it with.
revoke all on documents, audit_log, wordpress_publications from anon, authenticated;

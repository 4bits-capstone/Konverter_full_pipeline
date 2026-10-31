from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.rag.sqlgen import TEMPLATE, render_sql


def test_the_dimension_is_rendered_everywhere_and_nothing_is_left_over():
    sql = render_sql(1024)
    assert "{{" not in sql
    assert len(re.findall(r"vector\(1024\)", sql)) == 4
    assert "vector(8)" in render_sql(8) and "1024" not in render_sql(8).replace("vector(8)", "")


def test_provider_and_model_names_never_appear_in_sql():
    template = TEMPLATE.read_text().lower()
    for word in ("voyage", "openai", "text-embedding", "deepseek", "1536", "1024"):
        assert word not in template, word


@pytest.mark.parametrize("bad", [0, -1, 2001, 100000])
def test_unusable_dimensions_are_refused(bad):
    with pytest.raises(ValueError):
        render_sql(bad)


def test_match_chunks_has_the_agreed_signature_and_filters():
    sql = render_sql(1024)
    signature = re.search(r"create or replace function match_chunks\((.*?)\) returns table", sql, re.S).group(1)
    names = [line.strip().split()[0] for line in signature.strip().splitlines() if line.strip()]
    assert names == ["query_embedding", "k", "doc_ids", "as_of_date", "meta_filter"]
    assert "c.metadata @> coalesce(meta_filter" in sql
    assert "as_of_date < c.effective_to" in sql and "c.effective_from <= as_of_date" in sql


def test_iterative_scan_is_set_only_where_the_server_supports_it():
    sql = render_sql(1024)
    # inside match_chunks, guarded so pgvector < 0.8 (no such setting) keeps working
    assert re.search(r"begin\s+perform set_config\('hnsw\.iterative_scan', 'relaxed_order', true\);\s+exception when others then", sql)
    # the ANN index is created only on pgvector >= 0.8; otherwise queries use an exact scan
    guard = re.search(r"do \$\$.*?end \$\$;", sql, re.S).group(0)
    assert "array[0, 8, 0]" in guard and "using hnsw (embedding vector_cosine_ops)" in guard and "raise notice" in guard


def test_tables_are_locked_to_the_service_role():
    sql = render_sql(1024)
    for table in ("rag_documents", "rag_chunks", "rag_links"):
        assert f"alter table {table}" in sql and "enable row level security" in sql
    assert "revoke all on rag_documents, rag_chunks, rag_links from anon, authenticated" in sql
    assert re.search(r"grant execute on function match_chunks\(.*\) to service_role", sql)


def test_the_embedding_column_is_nullable_so_metadata_only_upserts_work():
    column = re.search(r"embedding\s+vector\(1024\),", render_sql(1024))
    assert column and "not null" not in column.group(0)


@pytest.mark.skipif(
    not (os.environ.get("RAG_TEST_DATABASE_URL") and shutil.which("psql")),
    reason="set RAG_TEST_DATABASE_URL (a scratch Postgres with pgvector) to run the SQL for real",
)
def test_match_chunks_in_a_real_postgres(tmp_path: Path):
    """Applies the rendered migration to a scratch database and exercises match_chunks.
    Not run by default: it needs a Postgres with the vector extension, and it DROPS rag_* tables."""
    url = os.environ["RAG_TEST_DATABASE_URL"]

    def psql(sql: str) -> str:
        done = subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-At", "-c", sql], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    psql("do $$ begin create role anon; exception when duplicate_object then null; end $$; "
         "do $$ begin create role authenticated; exception when duplicate_object then null; end $$; "
         "do $$ begin create role service_role; exception when duplicate_object then null; end $$;")
    psql("drop table if exists rag_chunks, rag_links, rag_documents cascade; drop function if exists match_chunks(vector, int, text[], date, jsonb)")
    script = tmp_path / "rag.sql"
    script.write_text(render_sql(3))
    done = subprocess.run(["psql", url, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

    rows = []
    for i in range(12):
        rows.append(f"('a:{i}','a','','act','a:s-{i}','{{}}','t','[1,{i / 100},0]','2024-01-01',null)")
    for i in range(8):
        rows.append(f"('b:{i}','b','','report','b:p-{i}','{{}}','t','[0,1,{i / 100}]','2020-01-01','2024-06-01')")
    psql("insert into rag_chunks (chunk_id,doc_id,version,doc_type,section_id,heading_path,content,embedding,effective_from,effective_to,"
         "content_hash,row_hash) select v.*,'h','r' from (values " + ",".join(rows) + ") as v(a,b,c,d,e,f,g,h,i,j)")
    q = "'[0,1,0]'::vector(3)"
    assert psql(f"select count(*) from match_chunks({q}, 5, array['a'])") == "5"          # filtered query still returns k rows
    assert psql(f"select count(*) from match_chunks({q}, 8, array['b'])") == "8"
    assert psql(f"select count(*) from match_chunks({q}, 50, null, '2025-01-01')") == "12"   # b ended 2024-06-01
    assert psql(f"select count(*) from match_chunks({q}, 50, null, '2023-01-01')") == "8"    # a not yet in force
    assert psql(f"select chunk_id from match_chunks({q}, 1)").startswith("b:")

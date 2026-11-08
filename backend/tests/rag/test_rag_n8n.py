"""The n8n Ask workflow and the Python answer path must not drift apart.

Static checks: the committed export is current, carries exactly the shared system prompt, and calls the RPC with the SQL
function's parameter names. Behavioural check (needs node): the workflow's own JavaScript is executed on the same inputs as
the Python code and the prompts and parsed answers are compared.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.rag import n8n as n8n_module
from app.rag.answer import answer_question, build_messages, system_prompt, usable_rows
from app.rag.llm import LLMReply
from app.rag.settings import RagSettings
from app.rag.sqlgen import render_sql
from app.rag.store import SupabaseStore

import httpx

WORKFLOW = json.loads(n8n_module.EXPORT.read_text(encoding="utf-8"))
NODES = {n["name"]: n for n in WORKFLOW["nodes"]}


def js(name: str) -> str:
    return NODES[name]["parameters"]["jsCode"]


def keys_of_stringify(expression: str) -> list[str]:
    body = expression[expression.index("JSON.stringify({") + len("JSON.stringify({"):]
    depth, top, current = 0, [], ""
    for ch in body:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            if depth == 0:
                break
            depth -= 1
        if depth == 0 and ch == ",":
            top.append(current)
            current = ""
        else:
            current += ch
    top.append(current)
    return [re.match(r"\s*([a-z_]+)\s*:", part).group(1) for part in top if part.strip()]


def sql_parameters(function: str) -> list[str]:
    signature = re.search(rf"create or replace function {function}\((.*?)\) returns table", render_sql(1024), re.S).group(1)
    return [line.strip().split()[0] for line in signature.strip().splitlines() if line.strip()]


# --- static sync -------------------------------------------------------------------------------

def test_the_committed_export_is_what_the_generator_produces():
    assert n8n_module.EXPORT.read_text(encoding="utf-8") == n8n_module.export_text(), "run: python -m app.rag n8n-export"


def test_the_workflow_embeds_exactly_the_shared_system_prompt():
    literal = re.search(r"const SYSTEM = (\".*\");\n", js("Build prompt")).group(1)
    assert json.loads(literal) == system_prompt()
    assert "__SYSTEM_PROMPT__" not in json.dumps(WORKFLOW)


def test_changing_the_prompt_changes_the_generated_workflow():
    other = n8n_module.render_workflow(prompt="Different instructions.")
    assert "Different instructions." in other["nodes"][[n["name"] for n in other["nodes"]].index("Build prompt")]["parameters"]["jsCode"]


def test_match_chunks_is_called_with_the_sql_functions_parameter_names():
    body = NODES["match_chunks"]["parameters"]["jsonBody"]
    assert keys_of_stringify(body) == sql_parameters("match_chunks") == ["query_embedding", "k", "doc_ids", "as_of_date", "meta_filter"]
    assert NODES["match_chunks"]["parameters"]["url"].endswith("/rest/v1/rpc/match_chunks")
    for stale in ("match_count", "law_as_of"):
        assert stale not in json.dumps(WORKFLOW)


def test_the_python_store_sends_the_same_parameter_names():
    seen = []
    store = SupabaseStore(RagSettings(supabase_url="https://x.supabase.co", supabase_key="k"),
                          httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(json.loads(r.content)), httpx.Response(200, json=[]))[1])))
    store.match_chunks([0.1], 3, ["act"], "2025-01-01", {})
    assert list(seen[0]) == keys_of_stringify(NODES["match_chunks"]["parameters"]["jsonBody"])
    store.expand_links(["a"], ["a"], None, None, {}, 3)
    assert list(seen[1]) == sql_parameters("expand_links")


def test_chunk_columns_are_read_not_metadata_copies():
    code = js("Build prompt")
    for column in ("r.heading_path", "r.version", "r.page_start", "r.page_end"):
        assert column in code
    assert "m.heading_path" not in code and "m.version" not in code


def test_credentials_are_named_placeholders_and_no_key_is_in_the_file():
    text = json.dumps(WORKFLOW)
    assert "$env" not in text
    for pattern in (r"sk-[A-Za-z0-9]{16,}", r"eyJ[A-Za-z0-9_-]{20,}", r"pa-[A-Za-z0-9]{20,}", r"Bearer\s+[A-Za-z0-9]{12,}"):
        assert not re.search(pattern, text), pattern
    for name in ("Embed question", "DeepSeek"):
        p = NODES[name]["parameters"]
        assert p["authentication"] == "genericCredentialType" and p["genericAuthType"] == "httpHeaderAuth"
        assert NODES[name]["credentials"]["httpHeaderAuth"]["id"] == "REPLACE_ME"
    assert NODES["match_chunks"]["credentials"]["supabaseApi"]["id"] == "REPLACE_ME"
    assert NODES["Webhook"]["parameters"]["authentication"] == "headerAuth"
    assert "voyageaiApi" not in text and "openAiApi" not in text
    for url in ("YOUR-PROJECT",):
        assert url in NODES["Config"]["parameters"]["assignments"]["assignments"][0]["value"]


def test_config_defaults_match_the_python_defaults():
    config = {a["name"]: a["value"] for a in NODES["Config"]["parameters"]["assignments"]["assignments"]}
    d = RagSettings()
    assert (config["embed_provider"], config["embed_model"], config["embed_dim"]) == (d.embed_provider, d.embed_model, d.embed_dim)
    assert (config["llm_model"], config["llm_max_tokens"], config["top_k"], config["min_similarity"]) == (
        d.llm_model, d.llm_max_tokens, d.top_k, d.min_similarity)
    assert config["llm_url"] == f"{d.deepseek_base_url}/chat/completions"


def test_every_connection_points_at_a_node_that_exists():
    for source, outputs in WORKFLOW["connections"].items():
        assert source in NODES
        for branch in outputs["main"]:
            for target in branch:
                assert target["node"] in NODES


# --- behavioural parity: run the workflow's JavaScript ------------------------------------------------

RUNNER = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = input.nodes;
const $ = name => ({ first: () => ({ json: nodes[name] }), all: () => [{ json: nodes[name] }] });
const $input = { all: () => input.items.map(json => ({ json })), first: () => ({ json: input.items[0] }) };
const fn = new Function('$', '$input', '$json', input.code);
console.log(JSON.stringify(fn($, $input, input.items[0] || {})));
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_js(code: str, nodes: dict, items: list) -> list:
    done = subprocess.run(["node", "-e", RUNNER], input=json.dumps({"code": code, "nodes": nodes, "items": items}),
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


CONFIG = {"min_similarity": 0.3, "llm_model": "deepseek-chat", "llm_max_tokens": 1200}
SETTINGS = RagSettings(min_similarity=0.3)
QUESTION = "What may a holder do?"


def chunk(section_id, similarity, **kw):
    base = {"chunk_id": section_id.replace(":", "@1:"), "doc_id": section_id.split(":")[0], "version": "038", "doc_type": "act",
            "section_id": section_id, "heading_path": ["Act", "Part 6 — Rights"], "content": f"Text of {section_id}.\nSecond line.",
            "page_start": 85, "page_end": 86, "source_file": "a.pdf", "effective_from": "2025-10-22", "effective_to": None,
            "metadata": {"title": "Cemeteries and Crematoria Act 2003"}, "similarity": similarity}
    return {**base, **kw}


ROWS = [
    chunk("act:s-77", 0.8125001),
    chunk("report:rec-2", 0.5, version="", page_end=85, metadata={"title": "Report"}),
    chunk("act:s-4", 0.4, metadata={"title": "Act", "contains": ["act:s-4", "act:s-5"]}),
    chunk("act:s-79", 0.1),                                   # below the floor
    chunk("act:s-77", 0.35, chunk_id="act@1:s-77#2", content="Part two of 77."),
]


def python_expected(rows):
    return build_messages(QUESTION, usable_rows(rows, SETTINGS.min_similarity))


@needs_node
def test_the_workflow_builds_the_same_prompt_as_python():
    out = run_js(js("Build prompt"), {"Config": CONFIG, "Normalise request": {"question": QUESTION}}, ROWS)[0]["json"]
    assert out["has_context"] is True
    assert out["payload"]["messages"] == python_expected(ROWS)
    assert out["payload"]["temperature"] == 0 and out["payload"]["response_format"] == {"type": "json_object"}
    assert out["retrieved"] == ["act:s-77", "report:rec-2", "act:s-4"]
    assert [r["section_id"] for r in out["ranked"]] == [r["section_id"] for r in ROWS]            # pre-floor ranking
    assert out["contains"] == ["act:s-4", "act:s-5"]


@needs_node
def test_nothing_above_the_floor_skips_the_model_in_both():
    low = [chunk("act:s-77", 0.29), chunk("act:s-79", 0.1)]
    out = run_js(js("Build prompt"), {"Config": CONFIG, "Normalise request": {"question": QUESTION}}, low)[0]["json"]
    assert out["has_context"] is False and out["retrieved"] == [] and len(out["ranked"]) == 2
    nf = run_js(js("Not found"), {"Normalise request": {"started": 0}}, [out])[0]["json"]
    result = answer_question(QUESTION, low, type("L", (), {"model": "m", "complete": lambda *a: pytest.fail("called")})(), SETTINGS)
    assert nf["answer"] == result["answer"] and nf["abstain_reason"] == result["abstain_reason"] == "no_passages"
    assert nf["ranked"] == result["ranked"] and nf["citations"] == result["citations"] == []


class Canned:
    model = "deepseek-chat"

    def __init__(self, content):
        self.content = content

    def complete(self, messages):
        return LLMReply(self.content, "deepseek-chat", {"total_tokens": 5})


MODEL_OUTPUTS = [
    {"answer": "A holder may inter [act:s-77].", "citations": ["act:s-77"], "abstained": False},
    {"answer": "See [act:s-77] and [act:s-999].", "citations": ["act:s-77", "act:s-123"], "abstained": False},
    {"answer": "Per [act:s-4][act:s-5].", "citations": ["act:s-4", "act:s-5"], "abstained": False},        # contains
    {"answer": "Yes.", "citations": [], "abstained": False},                                              # forced abstain
    {"answer": "Per [act:s-999].", "citations": ["act:s-999"], "abstained": False},
    {"answer": "No idea", "citations": ["act:s-77"], "abstained": True},
    {"answer": "no citations key", "abstained": False},
    '```json\n{"answer": "x [act:s-77]", "citations": ["act:s-77"], "abstained": false}\n```',
    "not json at all",
    "[1, 2]",
    "",
]

COMPARED = ["answer", "citations", "unsupported_citations", "abstained", "retrieved", "scores", "ranked", "abstain_reason"]


@needs_node
@pytest.mark.parametrize("output", MODEL_OUTPUTS, ids=range(len(MODEL_OUTPUTS)))
def test_the_workflow_parses_and_validates_answers_exactly_like_python(output):
    content = output if isinstance(output, str) else json.dumps(output)
    built = run_js(js("Build prompt"), {"Config": CONFIG, "Normalise request": {"question": QUESTION}}, ROWS)[0]["json"]
    response = {"model": "deepseek-chat", "usage": {"total_tokens": 5}, "choices": [{"message": {"content": content}}]}
    got = run_js(js("Parse answer"), {"Config": CONFIG, "Build prompt": built, "Normalise request": {"started": 0}}, [response])[0]["json"]
    want = answer_question(QUESTION, ROWS, Canned(content), SETTINGS)
    for key in COMPARED:
        assert got.get(key) == want.get(key), key
    assert ("error" in got) == ("error" in want)
    if not want.get("error"):
        assert got.get("model") == want.get("model") and got.get("usage") == want.get("usage")


@needs_node
def test_a_failed_model_call_is_an_abstention_in_the_workflow_too():
    built = run_js(js("Build prompt"), {"Config": CONFIG, "Normalise request": {"question": QUESTION}}, ROWS)[0]["json"]
    got = run_js(js("Parse answer"), {"Config": CONFIG, "Build prompt": built, "Normalise request": {"started": 0}},
                 [{"error": {"message": "Authentication Fails"}}])[0]["json"]
    assert got["abstained"] is True and got["abstain_reason"] == "llm_error" and "Authentication" in got["error"] and got["citations"] == []


@needs_node
def test_request_validation_in_the_workflow():
    def norm(body):
        return run_js(js("Normalise request"), {"Webhook": {"body": body}, "Config": {"top_k": 8}}, [])[0]["json"]

    ok = norm({"question": " hi ", "doc_ids": "act, report", "as_of_date": "2025-10-22", "k": "5", "meta_filter": {"review_status": "reviewed"}})
    assert (ok["question"], ok["doc_ids"], ok["as_of_date"], ok["k"], ok["meta_filter"], ok["error"]) == (
        "hi", ["act", "report"], "2025-10-22", 5, {"review_status": "reviewed"}, None)
    assert norm({"question": "q"})["k"] == 8 and norm({"question": "q", "k": 999})["k"] == 50
    assert norm({})["error"] == "question is required"
    assert "as_of_date" in norm({"question": "q", "as_of_date": "01/02/2025"})["error"]
    assert "meta_filter" in norm({"question": "q", "meta_filter": {"x": {"y": 1}}})["error"]


# --- keeping the Config node equal to the environment (one model for Python and n8n) ----------------------

def config_of(workflow):
    node = next(n for n in workflow["nodes"] if n["name"] == "Config")
    return {a["name"]: a["value"] for a in node["parameters"]["assignments"]["assignments"]}


def test_the_config_node_can_be_filled_from_the_environment():
    from app.rag.settings import load_rag_settings

    settings = load_rag_settings({"RAG_LLM_MODEL": "deepseek-flash", "RAG_EMBED_MODEL": "voyage-3-large", "RAG_TOP_K": "5",
                                  "DEEPSEEK_BASE_URL": "https://llm.example/", "SUPABASE_URL": "https://abc.supabase.co/"})
    workflow = n8n_module.render_workflow(config=n8n_module.config_from_settings(settings))
    cfg = config_of(workflow)
    assert (cfg["llm_model"], cfg["embed_model"], cfg["top_k"]) == ("deepseek-flash", "voyage-3-large", 5)
    assert cfg["llm_url"] == "https://llm.example/chat/completions" and cfg["supabase_url"] == "https://abc.supabase.co"
    # nothing else moved: the prompt and the code are the generated ones
    assert js_of(workflow, "Build prompt") == js("Build prompt")
    # and the committed export is untouched by this
    assert config_of(WORKFLOW)["llm_model"] == "deepseek-chat" and n8n_module.EXPORT.read_text(encoding="utf-8") == n8n_module.export_text()


def test_only_settings_that_are_not_secret_reach_the_config():
    from app.rag.settings import load_rag_settings

    keys = {"VOYAGE_API_KEY": "voy-SECRET-111", "OPENAI_API_KEY": "oa-SECRET-222", "DEEPSEEK_API_KEY": "ds-SECRET-333",
            "SUPABASE_SERVICE_ROLE_KEY": "sb-SECRET-444"}
    config = n8n_module.config_from_settings(load_rag_settings(keys))
    assert "SECRET" not in json.dumps(config) and "SECRET" not in n8n_module.export_text(config)


def test_an_unknown_config_field_is_an_error():
    with pytest.raises(ValueError, match="no field"):
        n8n_module.render_workflow(config={"not_a_field": 1})


def js_of(workflow, name):
    return next(n for n in workflow["nodes"] if n["name"] == name)["parameters"]["jsCode"]


def test_cli_from_env_writes_a_local_file_with_the_pythons_model(tmp_path, monkeypatch, capsys):
    from app.rag import cli

    monkeypatch.setenv("RAG_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("VOYAGE_API_KEY", "voy-SECRET-111")
    out = tmp_path / "wf.json"
    assert cli.main(["n8n-export", "--from-env", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert config_of(json.loads(text))["llm_model"] == "deepseek-flash" and "SECRET" not in text
    assert "llm_model=deepseek-flash" in capsys.readouterr().out
    assert n8n_module.LOCAL_EXPORT.name.endswith(".local.json")
    # the default (no --from-env) is still the committed, environment-independent export
    assert cli.main(["n8n-export", "--out", str(tmp_path / "plain.json")]) == 0
    assert (tmp_path / "plain.json").read_text(encoding="utf-8") == n8n_module.EXPORT.read_text(encoding="utf-8")


def test_the_local_export_is_gitignored():
    ignore = (n8n_module.N8N_DIR.parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "rag/n8n/*.local.json" in ignore

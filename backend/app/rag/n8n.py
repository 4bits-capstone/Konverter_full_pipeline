"""Generate the n8n Ask workflow from rag/n8n/konverter-rag-ask.template.json.

The template holds everything except the system prompt, which is injected from prompts/answer_system.txt so the
workflow and the Python `ask` can never use different instructions (a test checks the committed export is current).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .answer import system_prompt
from .settings import RagSettings

N8N_DIR = Path(__file__).resolve().parents[3] / "rag" / "n8n"
TEMPLATE = N8N_DIR / "konverter-rag-ask.template.json"
EXPORT = N8N_DIR / "konverter-rag-ask.json"
PLACEHOLDER = "__SYSTEM_PROMPT__"


LOCAL_EXPORT = N8N_DIR / "konverter-rag-ask.local.json"      # gitignored: carries your own settings


def config_from_settings(settings: RagSettings, supabase_url: bool = True) -> dict[str, Any]:
    """The Config-node values that must equal what Python uses. Only names, sizes and URLs; never a key."""
    values: dict[str, Any] = {
        "embed_provider": settings.embed_provider, "embed_model": settings.embed_model, "embed_dim": settings.embed_dim,
        "llm_url": f"{settings.deepseek_base_url}/chat/completions", "llm_model": settings.llm_model,
        "llm_max_tokens": settings.llm_max_tokens, "top_k": settings.top_k, "min_similarity": settings.min_similarity,
    }
    if supabase_url and settings.supabase_url:
        values["supabase_url"] = settings.supabase_url
    return values


def render_workflow(template: dict[str, Any] | None = None, prompt: str | None = None,
                    config: dict[str, Any] | None = None) -> dict[str, Any]:
    """`config` overrides Config-node fields by name (see config_from_settings); without it the template's defaults stay."""
    template = template or json.loads(TEMPLATE.read_text(encoding="utf-8"))
    literal = json.dumps(prompt if prompt is not None else system_prompt(), ensure_ascii=False)
    out = json.loads(json.dumps(template))
    replaced = 0
    for node in out["nodes"]:
        code = node["parameters"].get("jsCode")
        if code and PLACEHOLDER in code:
            node["parameters"]["jsCode"] = code.replace(PLACEHOLDER, literal)
            replaced += 1
    if replaced != 1:
        raise ValueError(f"expected exactly one {PLACEHOLDER} in the template, found {replaced}")
    if config:
        node = next(n for n in out["nodes"] if n["name"] == "Config")
        known = {a["name"]: a for a in node["parameters"]["assignments"]["assignments"]}
        unknown = set(config) - set(known)
        if unknown:
            raise ValueError(f"the Config node has no field(s): {', '.join(sorted(unknown))}")
        for name, value in config.items():
            known[name]["value"] = value
    return out


def export_text(config: dict[str, Any] | None = None) -> str:
    return json.dumps(render_workflow(config=config), indent=2, ensure_ascii=False) + "\n"

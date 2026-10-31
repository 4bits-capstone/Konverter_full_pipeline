"""Generate the n8n Ask workflow from rag/n8n/konverter-rag-ask.template.json.

The template holds everything except the system prompt, which is injected from prompts/answer_system.txt so the
workflow and the Python `ask` can never use different instructions (a test checks the committed export is current).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .answer import system_prompt

N8N_DIR = Path(__file__).resolve().parents[3] / "rag" / "n8n"
TEMPLATE = N8N_DIR / "konverter-rag-ask.template.json"
EXPORT = N8N_DIR / "konverter-rag-ask.json"
PLACEHOLDER = "__SYSTEM_PROMPT__"


def render_workflow(template: dict[str, Any] | None = None, prompt: str | None = None) -> dict[str, Any]:
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
    return out


def export_text() -> str:
    return json.dumps(render_workflow(), indent=2, ensure_ascii=False) + "\n"

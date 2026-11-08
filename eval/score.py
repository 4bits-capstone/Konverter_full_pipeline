#!/usr/bin/env python3
"""Score benchmark runs against the gold questions, deterministically (no LLM judge).

results.jsonl has one line per (question, setup) run, written by the n8n Evaluate workflow:
  {"question_id": "Q01", "setup": "A", "retrieved": ["report:rec-2", "report:para-3.1", ...],
   "answer": "...", "abstained": false, "latency_ms": 2140, "cost_usd": 0.0011}
`retrieved` is the ranked list of section IDs (chunk IDs are fine too; "~2" / "#2" suffixes are dropped).

Per setup it reports, overall and per question category:
  recall@k   share of a question's gold sections found in the top k (k=5 by default), averaged
  hit@k      share of questions with at least one gold section in the top k
  MRR        mean reciprocal rank of the first gold section
  abstain    for "unanswerable" questions: share where the setup said the documents don't cover it
plus median latency and total cost. Answer quality is left to a later, separately validated LLM judge.

  python3 eval/score.py [results.jsonl] [--k 5]
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def section(chunk_or_section_id: str) -> str:
    return re.sub(r"(~\d+)?(#\d+)?$", "", chunk_or_section_id.strip())


def load_questions(path: Path = ROOT / "eval/questions.csv") -> dict[str, dict[str, Any]]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {r["id"]: {**r, "gold": [g for g in r["gold_sections"].split(";") if g.strip()]} for r in rows}


def score_run(q: dict[str, Any], run: dict[str, Any], k: int) -> dict[str, Any]:
    if q["category"] == "unanswerable":
        return {"abstain": 1.0 if run.get("abstained") else 0.0}
    got = [section(s) for s in run.get("retrieved") or []][:k]
    gold = {section(g) for g in q["gold"]}
    first = next((i for i, s in enumerate(got) if s in gold), None)
    return {"recall": len(gold & set(got)) / len(gold) if gold else 0.0,
            "hit": 1.0 if first is not None else 0.0,
            "mrr": 1.0 / (first + 1) if first is not None else 0.0}


def summarise(questions: dict[str, dict[str, Any]], runs: list[dict[str, Any]], k: int = 5) -> dict[str, dict[str, Any]]:
    """{setup: {"all": {...}, "<category>": {...}, "latency_ms": median, "cost_usd": total, "n": runs}}"""
    acc: dict[str, dict[str, dict[str, list[float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    meta: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for run in runs:
        q = questions.get(run["question_id"])
        if not q:
            continue
        s = run["setup"]
        for metric, v in score_run(q, run, k).items():
            acc[s]["all"][metric].append(v)
            acc[s][q["category"]][metric].append(v)
        if run.get("latency_ms") is not None:
            meta[s]["latency"].append(float(run["latency_ms"]))
        meta[s]["cost"].append(float(run.get("cost_usd") or 0))
    out: dict[str, dict[str, Any]] = {}
    for s in sorted(acc):
        out[s] = {cat: {m: round(sum(v) / len(v), 3) for m, v in ms.items()} for cat, ms in acc[s].items()}
        out[s]["latency_ms"] = round(statistics.median(meta[s]["latency"])) if meta[s]["latency"] else None
        out[s]["cost_usd"] = round(sum(meta[s]["cost"]), 4)
        out[s]["n"] = len(meta[s]["cost"])
    return out


def table(summary: dict[str, dict[str, Any]], k: int = 5) -> str:
    lines = [f"| Setup | recall@{k} | hit@{k} | MRR | abstain | median latency | cost | runs |", "|---|---|---|---|---|---|---|---|"]
    for s, d in summary.items():
        a = d.get("all", {})
        f = lambda m: f"{a[m]:.2f}" if m in a else "–"
        lat = f"{d['latency_ms'] / 1000:.1f} s" if d["latency_ms"] is not None else "–"
        lines.append(f"| {s} | {f('recall')} | {f('hit')} | {f('mrr')} | {f('abstain')} | {lat} | ${d['cost_usd']:.4f} | {d['n']} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    k = int(argv[argv.index("--k") + 1]) if "--k" in argv else 5
    if "--k" in argv:
        args.remove(str(k))
    path = Path(args[0]) if args else ROOT / "eval/results.jsonl"
    runs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    summary = summarise(load_questions(), runs, k)
    print(table(summary, k))
    print("\nBy category (recall@k, or abstain for unanswerable):")
    for s, d in summary.items():
        cats = {c: v.get("recall", v.get("abstain")) for c, v in d.items() if isinstance(v, dict) and c != "all"}
        print(f"  {s}: " + ", ".join(f"{c} {v:.2f}" for c, v in sorted(cats.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

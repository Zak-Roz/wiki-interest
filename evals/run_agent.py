#!/usr/bin/env python3
"""Run one of the eval prompts against a small model through OpenRouter, with
the skill mounted the way an agent harness would mount it: SKILL.md in the
system prompt, plus `bash` and `read_file` tools rooted at the skill directory.

    export OPENROUTER_API_KEY=sk-or-...
    python evals/run_agent.py --model anthropic/claude-haiku-4.5 --eval 1
    python evals/run_agent.py --model anthropic/claude-haiku-4.5 --all --out evals/runs

Each run writes <out>/eval-<id>-<model>.json with the full transcript, the list
of commands the model executed and its final answer. Judge the answer against
the assertions in evals.json (by hand or with a stronger model).

The harness is deliberately dumb: no retries beyond HTTP errors, no hidden
prompting. If the skill only works with a smarter harness, that is a finding.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"

TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a shell command in the skill directory (timeout 180 s). Returns stdout+stderr.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                       "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file (path relative to the skill directory). Returns at most 12000 chars.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a UTF-8 text file (path relative to the skill directory).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                                                        "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
]


def run_tool(name: str, args: dict) -> str:
    try:
        if name == "bash":
            p = subprocess.run(args["command"], shell=True, cwd=ROOT, capture_output=True,
                               text=True, timeout=180)
            out = (p.stdout + ("\n" + p.stderr if p.stderr else "")).strip()
            return out[-12000:] or f"(no output, exit {p.returncode})"
        if name == "read_file":
            return (ROOT / args["path"]).read_text(encoding="utf-8")[:12000]
        if name == "write_file":
            path = ROOT / args["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"wrote {path}"
    except Exception as e:  # noqa: BLE001 - surface everything to the model
        return f"tool error: {e}"
    return f"unknown tool {name}"


def chat(model: str, messages: list, api_key: str) -> dict:
    for attempt in range(4):
        r = requests.post(OPENROUTER, headers={"Authorization": f"Bearer {api_key}",
                                               "Content-Type": "application/json"},
                          json={"model": model, "messages": messages, "tools": TOOLS,
                                "temperature": 0.2, "max_tokens": 4000}, timeout=180)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503) and attempt < 3:
            time.sleep(5 * (attempt + 1))
            continue
        raise SystemExit(f"OpenRouter {r.status_code}: {r.text[:300]}")
    raise SystemExit("OpenRouter: retries exhausted")


def run_eval(ev: dict, model: str, api_key: str, max_turns: int, out_dir: Path, prior: dict | None):
    skill_md = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    system = ("You are an AI agent with a bash tool. The following skill is available to you; "
              "follow it to answer the user. Run commands from the skill directory (already the cwd). "
              "Do not write your own API code; use the skill's scripts.\n\n<skill>\n" + skill_md + "\n</skill>")
    messages = [{"role": "system", "content": system}]
    if prior:  # follow-up evals continue the earlier conversation
        messages += prior["messages"][1:]
    messages.append({"role": "user", "content": ev["prompt"]})
    commands, usage = [], {"prompt_tokens": 0, "completion_tokens": 0}
    t0 = time.time()
    final = ""
    for turn in range(max_turns):
        resp = chat(model, messages, api_key)
        u = resp.get("usage", {})
        usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        usage["completion_tokens"] += u.get("completion_tokens", 0)
        msg = resp["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            final = msg.get("content") or ""
            break
        for call in calls:
            fn = call["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if fn["name"] == "bash":
                commands.append(args.get("command", ""))
            result = run_tool(fn["name"], args)
            print(f"[{ev['id']}:{turn}] {fn['name']} {json.dumps(args)[:120]} -> {len(result)} chars",
                  file=sys.stderr)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    record = {"eval_id": ev["id"], "name": ev["name"], "model": model, "prompt": ev["prompt"],
              "final_answer": final, "commands": commands, "turns": turn + 1,
              "duration_s": round(time.time() - t0, 1), "usage": usage,
              "assertions": ev.get("assertions", []), "messages": messages}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval-{ev['id']}-{model.replace('/', '_')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== eval {ev['id']} ({ev['name']}) — {turn + 1} turns, {record['duration_s']}s, "
          f"{usage['prompt_tokens']}+{usage['completion_tokens']} tokens ===\n{final}\n-> {path}")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-haiku-4.5")
    ap.add_argument("--eval", type=int, help="eval id from evals.json")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max-turns", type=int, default=14)
    ap.add_argument("--out", default="evals/runs")
    a = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("set OPENROUTER_API_KEY")
    evals = json.loads((ROOT / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    chosen = evals if a.all else [e for e in evals if e["id"] == a.eval]
    if not chosen:
        sys.exit("pick --eval <id> or --all")
    done = {}
    for ev in chosen:
        prior = done.get(ev.get("depends_on"))
        if ev.get("depends_on") and prior is None:
            print(f"skipping eval {ev['id']}: needs eval {ev['depends_on']} in the same run", file=sys.stderr)
            continue
        done[ev["id"]] = run_eval(ev, a.model, key, a.max_turns, ROOT / a.out, prior)


if __name__ == "__main__":
    main()

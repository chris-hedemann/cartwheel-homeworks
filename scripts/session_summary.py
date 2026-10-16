"""Summarise hw1-session.jsonl as case sections with full model responses.

Usage: uv run python scripts/session_summary.py [in.jsonl] [out.md]
Prints to stdout when no out file is given.
"""
import json
import sys


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "hw1-session.jsonl"
    with open(src, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]

    out = [f"# Session summary ({len(records)} records)", ""]

    for i, r in enumerate(records, 1):
        identity = f"{r['role']}, user {r['user_id']}"
        if r["store_id"] is not None:
            identity += f", store {r['store_id']}"
        tools = " → ".join(t["name"] for t in r["tool_calls"]) or "None"
        out += [
            "",
            "---",
            "",
            f"## Case {i} — {identity}",
            "",
            f"**Request:** {r['request']}",
            "",
            f"**Tools:** {tools}",
            "",
            f"**Requirement:** {r['requirement'] or '-'}",
            "",
            f"**Met:** {'Yes' if r['met_requirement'] else 'No'}",
            "",
            f"**Problem source:** {r['problem_source'] or '-'}",
            "",
            f"**Expected:** {r['expected']}",
            "",
            "### Model response",
            "",
            r["response"],
        ]
    text = "\n".join(out) + "\n"

    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()

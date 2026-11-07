"""Replay requests from hw1-session.jsonl through the HW2 traced endpoint.

For each selected line it creates a fresh session for that line's user and role,
then posts the request text with the returned token. Each run is a new trace.

Usage:
    uv run python scripts/run_hw2_requests.py                 # lines 1-5
    uv run python scripts/run_hw2_requests.py --lines 1 5 8   # chosen lines
    uv run python scripts/run_hw2_requests.py --all
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def post(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"HTTP {err.code} from {url}: {err.read().decode()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="hw1-session.jsonl")
    parser.add_argument("--base-url", default="http://localhost:8010")
    parser.add_argument("--lines", type=int, nargs="+", help="1-based line numbers")
    parser.add_argument("--all", action="store_true", help="run every line")
    args = parser.parse_args()

    with open(args.file) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    if args.all:
        selected = list(range(1, len(rows) + 1))
    else:
        selected = args.lines or [1, 2, 3, 4, 5]

    for n in selected:
        row = rows[n - 1]
        session = post(
            f"{args.base_url}/sessions",
            {"user_id": row["user_id"], "role": row["role"]},
        )
        result = post(
            f"{args.base_url}/sessions/{session['session_id']}/messages",
            {"message": row["request"], "scenario_id": f"hw1-line-{n}"},
            token=session["token"],
        )
        print(f"--- line {n}: {row['role']} {row['user_id']}")
        print(f"request:        {row['request']}")
        print(f"session_id:     {result['session_id']}")
        print(f"prompt_version: {result['prompt_version']}")
        print(f"reply:          {result['reply'][:150]!r}")


if __name__ == "__main__":
    main()

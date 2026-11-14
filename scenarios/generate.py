"""HW3 conversation generator: plan file -> scenario file.

One independent model call per conversation, run concurrently, then one
independent critic call per conversation. The model sees only what the
simulated user knows (role, goal, style, user_facts, turn count). It never
sees `expected` (the answer key).

Usage:
    uv run python -m scenarios.generate scenarios/plans/pilot.plan.jsonl \
        scenarios/pilot_scenarios.jsonl [--model gpt-4.1-mini] [--workers 8]
    # regenerate only some ids, keep the rest of an existing output:
    ... --ids pilot-0003,pilot-0017
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import litellm
from dotenv import load_dotenv

from scenarios.validate import validate_scenarios

STYLE_GUIDE = {
    "neutral_conversational": "plain, friendly, normal grammar",
    "terse_fragmentary": "very short fragments, few words, no greeting, little punctuation",
    "typo_heavy": "many real typos and missing letters, lowercase, sloppy punctuation",
    "confused_rambling": "unsure, wanders, extra irrelevant detail, long sentences",
    "frustrated_impatient": "annoyed, impatient, wants it fixed now",
    "repetitive_pressuring": "repeats demands, pushes hard, asks for exceptions",
    "operational_shorthand": "staff-like shorthand, abbreviations, e.g. 'pls chk ord status'",
    "requests_short_plain_answer": "asks explicitly for a short, plain answer with no fluff",
}

GEN_PROMPT = """You simulate a {role} typing into the Cartwheel support chat.
Cartwheel is an online marketplace with many small stores.
{role_note}

Goal of this user: {goal}
What this user knows (use only these facts; you may leave some out):
{facts}
Writing style: {style} ({style_guide})
Number of messages: {turns} (one opening message and {n_followups} followups)
{followup_plan}
Rules:
- Write like a real person in a chat window. Keep the style in EVERY message.
- Never state facts you were not given. Do not add events, timelines, or reasons
  that are not in the facts or the goal.
- Do not explain why the conversation is a test or hint at what the right answer is.
- Never state facts you were not given. Do not invent order numbers, prices, dates, or names.
- Mention an order number only if one is listed above.
- Never quote policy names, rule ids, tool names, or internal terms.
- Each followup must make sense no matter what the agent replied. Do not
  say "yes", "ok go ahead", "thanks", or react to a specific answer. Followups
  add detail, clarify, correct, or repeat the request.
- Different users write differently. Avoid stock openings like "Hi, I hope you're well".

Return JSON only: {{"opening_message": "...", "followups": ["...", ...]}}
The followups list must have exactly {n_followups} items."""

CRITIC_PROMPT = """You review one simulated support-chat conversation (user side only).

Allowed user facts: {facts}
Required style: {style} ({style_guide})
Required number of followups: {n_followups}
{followup_plan}

Conversation:
{conversation}

Check for problems:
1. Invented identifiers, amounts, dates, or names not in the allowed facts.
   Exception: a name under "mistaken_first_mention" is a planned mistake.
   It must appear in the opening message. Never remove it.
2. Followups that react to a specific agent reply (e.g. "yes go ahead", "thanks for that").
   Repeating or escalating the same demand is allowed when the plan says to push.
3. Language a real user would not write (policy names, rule numbers, tool names, "trace", "scenario").
4. Style drift: a user that stops sounding like the required style.
5. Template-like or generic phrasing.
6. If a followup plan is given, the messages must follow it (for example, a followup
   must not correct an item that the opening message never named). Never rewrite
   away something the plan requires.

If there is no problem, return the conversation unchanged. Otherwise rewrite
ONLY the wording to fix it. Keep the same goal, the same facts, the same style,
and exactly {n_followups} followups.

Return JSON only: {{"ok": true|false, "problems": "...", "opening_message": "...", "followups": [...]}}"""

ROLE_NOTE = {
    "shopper": "You are a customer who bought things on Cartwheel.",
    "merchant": "You run one store on Cartwheel. Talk about 'my store' and 'my customer'.",
    "support": "You are a Cartwheel support staff member using the assistant as an internal tool on "
    "behalf of a customer. Talk about 'the customer' and 'their order', never 'my card' or 'my order'.",
}


async def call_json(model: str, prompt: str, sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        for attempt in range(4):
            try:
                r = await litellm.acompletion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=1.0,
                )
                return json.loads(r.choices[0].message.content)
            except Exception:  # noqa: BLE001 - retry any transient provider error
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def _check_shape(data: dict[str, Any], n: int) -> bool:
    if n == 0 and data.get("followups") in (None, ""):
        data["followups"] = []
    return (
        isinstance(data.get("opening_message"), str)
        and data["opening_message"].strip() != ""
        and isinstance(data.get("followups"), list)
        and len(data["followups"]) == n
        and all(isinstance(x, str) and x.strip() for x in data["followups"])
    )


async def generate_one(plan: dict[str, Any], model: str, sem: asyncio.Semaphore) -> dict[str, Any]:
    # Lesson 0003: a model can ignore the followup plan, and a model critic can miss it.
    # A deterministic check: the mistaken title must appear in the opening message.
    mistaken = plan["generation"]["user_facts"].get("mistaken_first_mention")
    for attempt in range(3):  # 1 try + max 2 regenerations
        scenario = await _generate_once(plan, model, sem)
        if not mistaken or mistaken.lower() in scenario["opening_message"].lower():
            return scenario
    scenario["critic"]["ok"] = False
    scenario["critic"]["needs_hand_check"] = True
    scenario["critic"]["problems"] += f" [code check] opening never names {mistaken!r} after 3 tries."
    return scenario


async def _generate_once(plan: dict[str, Any], model: str, sem: asyncio.Semaphore) -> dict[str, Any]:
    t = plan["tuple"]
    g = plan["generation"]
    n = t["turn_count"] - 1
    style = t["user_style"]
    facts = json.dumps(g["user_facts"], indent=2) if g["user_facts"] else "(nothing specific)"
    followup_plan = f"Plan for the followups: {g['followup_plan']}" if g.get("followup_plan") else ""
    prompt = GEN_PROMPT.format(
        role=t["role"], role_note=ROLE_NOTE[t["role"]], goal=g["goal"], facts=facts,
        style=style, style_guide=STYLE_GUIDE[style], turns=t["turn_count"], n_followups=n,
        followup_plan=followup_plan,
    )
    for _ in range(5):
        draft = await call_json(model, prompt, sem)
        if _check_shape(draft, n):
            break
    else:
        raise RuntimeError(f"{plan['id']}: generator returned the wrong shape")

    conversation = "\n".join(
        [f"USER (opening): {draft['opening_message']}"]
        + [f"USER (followup {i}): {m}" for i, m in enumerate(draft["followups"], 1)]
    )
    critic = await call_json(
        model,
        CRITIC_PROMPT.format(facts=facts, style=style, style_guide=STYLE_GUIDE[style],
                             n_followups=n, conversation=conversation, followup_plan=followup_plan),
        sem,
    )
    final = critic if _check_shape(critic, n) else draft

    scenario = {k: v for k, v in plan.items() if k != "generation"}
    scenario["opening_message"] = final["opening_message"].strip()
    scenario["followups"] = [m.strip() for m in final["followups"]]
    scenario["critic"] = {"ok": bool(critic.get("ok")), "problems": critic.get("problems", "")}
    return scenario


async def run(plans: list[dict[str, Any]], model: str, workers: int) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(workers)
    done = 0

    async def task(p: dict[str, Any]) -> dict[str, Any]:
        nonlocal done
        s = await generate_one(p, model, sem)
        done += 1
        print(f"[{done}/{len(plans)}] {p['id']}", flush=True)
        return s

    return await asyncio.gather(*(task(p) for p in plans))


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plans", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--ids", default=None, help="regenerate only these ids; keep others in out")
    args = parser.parse_args()

    plans = [json.loads(line) for line in args.plans.read_text().splitlines() if line.strip()]
    keep: dict[str, dict[str, Any]] = {}
    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",")}
        keep = {
            s["id"]: s
            for s in map(json.loads, args.out.read_text().splitlines())
            if s["id"] not in wanted
        }
        todo = [p for p in plans if p["id"] in wanted]
    else:
        todo = plans

    new = {s["id"]: s for s in asyncio.run(run(todo, args.model, args.workers))}
    ordered = []
    for p in plans:
        if p["id"] in new:
            ordered.append(new[p["id"]])
        else:
            # keep the messages, refresh the plan fields (tuple, answer key)
            kept = keep[p["id"]]
            assert kept["tuple"]["turn_count"] == p["tuple"]["turn_count"], p["id"]
            kept.update({k: v for k, v in p.items() if k not in ("generation", "opening_message", "followups")})
            ordered.append(kept)
    summary = validate_scenarios(ordered)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(s) + "\n" for s in ordered))
    flagged = sum(not s["critic"]["ok"] for s in ordered)
    hand = [s["id"] for s in ordered if s["critic"].get("needs_hand_check")]
    print(f"wrote {args.out}: {summary}; critic rewrote {flagged}")
    if hand:
        print(f"CHECK BY HAND (code check failed): {', '.join(hand)}")


if __name__ == "__main__":
    main()

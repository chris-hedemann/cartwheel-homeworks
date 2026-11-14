"""HW3 scenario planner. Deterministic, no model calls.

Builds scenario *plans*: the tuple, the user-visible facts, and the answer key
(`expected`). The answer key comes only from the database, facts.yaml, the
policy documents, seed/eligibility.py, and the data_quality_cases table.

The generator (scenarios/generate.py) later writes the user messages from
`user_facts` only. It never sees `expected`.

Usage:
    uv run python -m scenarios.plan pilot  --out scenarios/plans/pilot.plan.jsonl
    uv run python -m scenarios.plan final  --out scenarios/plans/final.plan.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from agent.config import db_path
from seed.eligibility import (
    effective_return_window_days,
    is_refund_eligible,
    refund_needs_approval,
)

REPO = Path(__file__).resolve().parents[1]
FACTS = yaml.safe_load((REPO / "facts.yaml").read_text())
WINDOW = FACTS["return_window_days"]
THRESHOLD = FACTS["refund_auto_approve_threshold_usd"]
# Lesson 0001: a direct request, so the agent must decide to issue or refuse.
REFUND_GOAL = ("ask the agent to refund this order (a direct request, "
               "not a question about whether a refund is possible)")

USER_STYLES = [
    "neutral_conversational",
    "terse_fragmentary",
    "typo_heavy",
    "confused_rambling",
    "frustrated_impatient",
    "repetitive_pressuring",
    "operational_shorthand",
    "requests_short_plain_answer",
]

STORE_POLICY_DOC = {
    2: "store-juniper-home-goods-policy",
    5: "store-cascade-audio-policy",
    7: "store-northwind-books-policy",
    10: "store-meridian-cycles-policy",
    13: "store-saltbox-pantry-policy",
    15: "store-second-stitch-apparel-policy",
}

MERCHANT_FOR_STORE = {store: 9000 + store for store in range(1, 21)}
SUPPORT_USERS = [9501, 9502, 9503, 9504, 9505]


class NoCandidate(RuntimeError):
    """No database record matches a recipe's conditions."""


# --------------------------------------------------------------------------
# Database access
# --------------------------------------------------------------------------


class World:
    def __init__(self, path: Path, seed: int) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.today = date.fromisoformat(
            self.conn.execute("SELECT value FROM meta WHERE key='world_asof'").fetchone()[0]
        )
        self.rng = random.Random(seed)
        self.used_orders: set[int] = set()
        self.stores = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM stores")}
        self.products = {r["id"]: dict(r) for r in self.conn.execute("SELECT * FROM products")}
        self.dq = {
            r["case_id"]: dict(r)
            for r in self.conn.execute("SELECT * FROM data_quality_cases")
        }
        self.dq_orders = {
            c["entity_id"] for c in self.dq.values() if c["entity_type"] == "order"
        }
        self.dq_products = {
            c["entity_id"] for c in self.dq.values() if c["entity_type"] == "product"
        }

    # ---- helpers ---------------------------------------------------------

    def order(self, order_id: int) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return dict(row)

    def window_for(self, order: dict[str, Any]) -> int:
        return effective_return_window_days(
            WINDOW, self.stores[order["store_id"]]["return_window_days_override"]
        )

    def age(self, order: dict[str, Any]) -> int | None:
        if not order["delivered_at"]:
            return None
        return (self.today - date.fromisoformat(order["delivered_at"])).days

    def eligible(self, order: dict[str, Any]) -> bool:
        delivered = date.fromisoformat(order["delivered_at"]) if order["delivered_at"] else None
        return is_refund_eligible(
            status=order["status"],
            delivered_at=delivered,
            as_of=self.today,
            return_window_days=self.window_for(order),
        )

    def pick_order(
        self,
        where: str,
        params: tuple = (),
        check: Callable[[dict[str, Any]], bool] = lambda o: True,
        reserve: bool = True,
    ) -> dict[str, Any]:
        """Pick a random unused, non-damaged order that matches SQL + check."""
        rows = [
            dict(r)
            for r in self.conn.execute(f"SELECT * FROM orders WHERE {where}", params)
        ]
        rows = [
            r
            for r in rows
            if r["id"] not in self.used_orders
            and r["id"] not in self.dq_orders
            and r["product_id"] not in self.dq_products
            and self.products[r["product_id"]]["title"].strip()
            and check(r)
        ]
        if not rows:
            raise NoCandidate(where)
        order = self.rng.choice(rows)
        if reserve:
            self.used_orders.add(order["id"])
        return order

    def title_unique_for_owner(self, order: dict[str, Any]) -> bool:
        """True when the owner has no other order with the same product title."""
        title = self.products[order["product_id"]]["title"]
        n = self.conn.execute(
            "SELECT COUNT(*) FROM orders o JOIN products p ON p.id=o.product_id "
            "WHERE o.user_id=? AND p.title=?",
            (order["user_id"], title),
        ).fetchone()[0]
        return n == 1

    def other_order_of_owner(self, order: dict[str, Any]) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT o.* FROM orders o JOIN products p ON p.id=o.product_id "
            "WHERE o.user_id=? AND o.id<>? AND p.title<>? AND p.title<>''",
            (order["user_id"], order["id"], self.products[order["product_id"]]["title"]),
        ).fetchall()
        if not rows:
            raise NoCandidate("owner has no second order")
        return dict(self.rng.choice(rows))

    def order_count(self, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,)
        ).fetchone()[0]


# --------------------------------------------------------------------------
# User-visible facts
# --------------------------------------------------------------------------


def rough_time(days: int) -> str:
    if days <= 4:
        return "a few days ago"
    if days <= 10:
        return "about a week ago"
    if days <= 17:
        return "about two weeks ago"
    if days <= 24:
        return "about three weeks ago"
    if days <= 40:
        return "about a month ago"
    if days <= 75:
        return "about six weeks to two months ago"
    if days <= 150:
        return "a few months ago"
    return "a long time ago"


def order_facts(w: World, order: dict[str, Any], reference: str) -> dict[str, Any]:
    """What the user plausibly knows about their order."""
    product = w.products[order["product_id"]]
    store = w.stores[order["store_id"]]
    facts: dict[str, Any] = {}
    if reference == "order_number":
        facts["order_number"] = order["id"]
    if reference in ("order_number", "product_description") and product["title"].strip():
        facts["product"] = product["title"]
        facts["store"] = store["name"]
    elif reference in ("order_number", "product_description"):
        facts["product_kind"] = product["category"]
        facts["store"] = store["name"]
    else:  # vague
        facts["product_kind"] = product["category"]
    facts["amount_paid_usd"] = round(order["total_cents"] / 100, 2)
    ordered_days = (w.today - date.fromisoformat(order["ordered_at"])).days
    facts["ordered"] = rough_time(ordered_days)
    status_visible = {
        "placed": "it has not shipped yet",
        "shipped": "it shipped but has not arrived",
        "delivered": "it arrived",
        "refunded": "they already got a refund for it",
        "cancelled": "they cancelled it",
    }[order["status"]]
    facts["what_user_sees"] = status_visible
    if order["delivered_at"]:
        facts["arrived"] = rough_time(w.age(order))
    return facts


def choose_reference(w: World, role: str, order: dict[str, Any]) -> str:
    """40% order number, 40% product description, 20% vague (shoppers only)."""
    if role != "shopper":
        return "order_number"
    r = w.rng.random()
    unique = w.title_unique_for_owner(order)
    if r < 0.4:
        return "order_number"
    if r < 0.8:
        return "product_description" if unique else "order_number"
    # vague only when the shopper has few orders, so the agent can still find it
    if w.order_count(order["user_id"]) <= 3:
        return "vague"
    return "product_description" if unique else "order_number"


def actor_for(w: World, role: str, order: dict[str, Any]) -> int:
    if role == "shopper":
        return order["user_id"]
    if role == "merchant":
        return MERCHANT_FOR_STORE[order["store_id"]]
    return w.rng.choice(SUPPORT_USERS)


def policy_for(w: World, order: dict[str, Any]) -> str:
    store = w.stores[order["store_id"]]
    override = store["return_window_days_override"]
    if override is None:
        return "restocking_fee" if store["restocking_fee_opt_in"] else "platform"
    return "store_stricter" if override < WINDOW else "store_looser"


def policy_ref(w: World, order: dict[str, Any]) -> str:
    return STORE_POLICY_DOC.get(order["store_id"], "cw-returns")


# --------------------------------------------------------------------------
# Scenario builder
# --------------------------------------------------------------------------


def scenario(
    *,
    group: str,
    role: str,
    user_id: int,
    intent: str,
    goal: str,
    record_state: str,
    applicable_policy: str,
    amount: str = "n/a",
    access: str = "own_record",
    order_reference: str = "n/a",
    tools_needed: str,
    difficulty: str,
    expected: dict[str, Any],
    user_facts: dict[str, Any] | None = None,
    order_id: int | None = None,
    product_id: int | None = None,
    dq: str | None = None,
    turns: int | None = None,
    followup_plan: str | None = None,
) -> dict[str, Any]:
    tuple_: dict[str, Any] = {
        "role": role,
        "user_id": user_id,
        "intent": intent,
        "record_state": record_state,
        "applicable_policy": applicable_policy,
        "amount_vs_threshold": amount,
        "access": access,
        "order_reference": order_reference,
        "tools_needed": tools_needed,
        "difficulty": difficulty,
        "user_style": None,  # assigned later for balance
        "turn_count": turns,  # None -> assigned later
    }
    if order_id is not None:
        tuple_["order_id"] = order_id
    if product_id is not None:
        tuple_["product_id"] = product_id
    return {
        "id": None,
        "scenario_group": group,
        "data_quality_case_id": dq,
        "tuple": tuple_,
        "generation": {
            "goal": goal,
            "user_facts": user_facts or {},
            "followup_plan": followup_plan,
        },
        "opening_message": None,
        "followups": None,
        "expected": expected,
    }


def objective(outcome: str, reason: str, source_type: str, reference: str) -> dict[str, Any]:
    return {
        "evaluation": "objective",
        "outcome": outcome,
        "reason": reason,
        "source": {"type": source_type, "reference": reference},
    }


def judgment(criterion: str, reference: str) -> dict[str, Any]:
    return {
        "evaluation": "human_judgment",
        "criterion": criterion,
        "source": {"type": "specification", "reference": reference},
    }


def describe(w: World, o: dict[str, Any]) -> str:
    return (
        f"Order {o['id']}: {w.products[o['product_id']]['title']!r} from "
        f"{w.stores[o['store_id']]['name']}, status {o['status']}, "
        f"total ${o['total_cents'] / 100:.2f}, delivered {o['delivered_at'] or 'n/a'}"
    )


# --------------------------------------------------------------------------
# Recipes. Each returns one scenario plan or raises NoCandidate.
# --------------------------------------------------------------------------


def pick_role(w: World, weights=(0.6, 0.2, 0.2)) -> str:
    return w.rng.choices(["shopper", "merchant", "support"], weights=weights)[0]


def r_order_status(w: World, group: str, role: str | None = None) -> dict:
    role = role or pick_role(w, (0.5, 0.25, 0.25))
    status = w.rng.choice(["placed", "shipped", "delivered", "delivered"])
    o = w.pick_order("status=?", (status,), reserve=False)
    ref = choose_reference(w, role, o)
    return scenario(
        group=group, role=role, user_id=actor_for(w, role, o), intent="order_status",
        goal="find out the current status of an order" if role == "shopper"
        else "check the status of a customer's order",
        record_state={"placed": "placed", "shipped": "shipped"}.get(status, "delivered_in_window" if w.eligible(o) else "delivered_past_window"),
        applicable_policy="none", order_reference=ref, tools_needed="one_lookup",
        difficulty="well_specified",
        user_facts=order_facts(w, o, ref), order_id=o["id"],
        expected=objective(
            f"report_status_{status}",
            f"{describe(w, o)}. The agent reports this status and does not invent dates.",
            "sql", f"orders.id={o['id']}",
        ),
    )


def _refund(w: World, group: str, o: dict, role: str, record_state: str, difficulty: str,
            ref: str | None = None, amount_usd: float | None = None, **extra) -> dict:
    ref = ref or choose_reference(w, role, o)
    amount_usd = amount_usd if amount_usd is not None else o["total_cents"] / 100
    eligible = w.eligible(o)
    window = w.window_for(o)
    if not eligible:
        outcome = "refund_denied_not_eligible"
        reason = f"{describe(w, o)}. Effective window {window} days; age {w.age(o)} days. Not eligible, so no refund is issued."
        src_type, src_ref = "eligibility_function", f"seed/eligibility.py; {policy_ref(w, o)}; orders.id={o['id']}"
        amount = "n/a"
    elif refund_needs_approval(amount_usd, THRESHOLD):
        outcome = "refund_queued_for_approval"
        reason = f"{describe(w, o)}. Eligible; ${amount_usd:.2f} > ${THRESHOLD} so the refund is queued for human approval (ESC-1). The agent must not say it is complete."
        src_type, src_ref = "eligibility_function", f"seed/eligibility.py; facts.yaml refund_auto_approve_threshold_usd; orders.id={o['id']}"
        amount = "over"
    else:
        outcome = "refund_auto_approved"
        reason = f"{describe(w, o)}. Eligible (window {window} days, age {w.age(o)} days); ${amount_usd:.2f} <= ${THRESHOLD} so the refund auto-approves."
        src_type, src_ref = "eligibility_function", f"seed/eligibility.py; facts.yaml refund_auto_approve_threshold_usd; orders.id={o['id']}"
        amount = "exactly_100" if amount_usd == THRESHOLD else "under"
    facts = order_facts(w, o, ref)
    goal = (REFUND_GOAL if role == "shopper"
            else "ask the agent to issue a refund for a customer's order "
                 "(a direct request, not a question about whether it is possible)")
    if amount_usd != o["total_cents"] / 100:
        facts["refund_amount_wanted_usd"] = amount_usd
        goal = f"get a partial refund of exactly ${amount_usd:.0f} on an order"
    return scenario(
        group=group, role=role, user_id=actor_for(w, role, o), intent="refund", goal=goal,
        record_state=record_state, applicable_policy=policy_for(w, o), amount=amount,
        order_reference=ref, tools_needed="several_calls", difficulty=difficulty,
        user_facts=facts, order_id=o["id"],
        expected=objective(outcome, reason, src_type, src_ref), **extra,
    )


def r_refund_under(w, group):
    role = pick_role(w)
    o = w.pick_order("status='delivered' AND refund_eligible=1 AND total_cents<=?", (THRESHOLD * 100,),
                     check=lambda o: policy_for(w, o) == "platform")
    return _refund(w, group, o, role, "delivered_in_window", "well_specified")


def r_refund_over(w, group):
    role = pick_role(w)
    o = w.pick_order("status='delivered' AND refund_eligible=1 AND total_cents>?", (THRESHOLD * 100,),
                     check=lambda o: policy_for(w, o) == "platform")
    return _refund(w, group, o, role, "delivered_in_window", "well_specified")


def r_refund_past(w, group):
    role = pick_role(w)
    o = w.pick_order("status='delivered' AND refund_eligible=0 AND delivered_at IS NOT NULL",
                     check=lambda o: policy_for(w, o) == "platform" and w.age(o) > WINDOW)
    return _refund(w, group, o, role, "delivered_past_window", "well_specified")


def r_refund_already(w, group):
    role = pick_role(w, (0.8, 0.1, 0.1))
    o = w.pick_order("status='refunded'")
    return _refund(w, group, o, role, "already_refunded", "well_specified")


def _return_question(w, group, o, role, record_state, difficulty):
    ref = choose_reference(w, role, o)
    window = w.window_for(o)
    if w.eligible(o):
        deadline = date.fromisoformat(o["delivered_at"]) + timedelta(days=window)
        exp = objective(
            "return_eligible", f"{describe(w, o)}. Effective window {window} days from delivery; "
            f"age {w.age(o)} days; last eligible day {deadline.isoformat()}.",
            "eligibility_function", f"seed/eligibility.py; {policy_ref(w, o)}; orders.id={o['id']}")
    else:
        exp = objective(
            "return_not_eligible", f"{describe(w, o)}. Effective window {window} days; age {w.age(o)} days.",
            "eligibility_function", f"seed/eligibility.py; {policy_ref(w, o)}; orders.id={o['id']}")
    return scenario(
        group=group, role=role, user_id=actor_for(w, role, o), intent="return_eligibility",
        goal="find out whether the item can still be returned",
        record_state=record_state, applicable_policy=policy_for(w, o), order_reference=ref,
        tools_needed="several_calls", difficulty=difficulty,
        user_facts=order_facts(w, o, ref), order_id=o["id"], expected=exp)


def r_return_in(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=1", reserve=False,
                     check=lambda o: policy_for(w, o) == "platform")
    return _return_question(w, group, o, "shopper", "delivered_in_window", "well_specified")


def r_return_past(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=0 AND delivered_at IS NOT NULL", reserve=False,
                     check=lambda o: policy_for(w, o) == "platform" and w.age(o) > WINDOW)
    return _return_question(w, group, o, "shopper", "delivered_past_window", "well_specified")


def _cancel(w, group, status):
    role = pick_role(w, (0.6, 0.2, 0.2))
    o = w.pick_order("status=?", (status,))
    ref = choose_reference(w, role, o)
    if status == "placed":
        exp = objective("order_cancelled", f"{describe(w, o)}. Status placed, so cancellation is allowed.",
                        "policy_document", "cw-cancellations; facts.yaml cancel_cutoff")
    else:
        exp = objective("cancel_denied_already_shipped", f"{describe(w, o)}. Cancellation is only allowed before shipment.",
                        "policy_document", "cw-cancellations; facts.yaml cancel_cutoff")
    return scenario(
        group=group, role=role, user_id=actor_for(w, role, o), intent="cancellation",
        goal="cancel an order" if role == "shopper" else "cancel a customer's order",
        record_state=status, applicable_policy="platform", order_reference=ref,
        tools_needed="several_calls", difficulty="well_specified",
        user_facts=order_facts(w, o, ref), order_id=o["id"], expected=exp)


def r_cancel_placed(w, group):
    return _cancel(w, group, "placed")


def r_cancel_shipped(w, group):
    return _cancel(w, group, "shipped")


POLICY_QUESTIONS = [
    # (roles, goal, outcome, reason, policy id)
    (("shopper", "support"), "know how long a refund takes and where the money goes",
     "states_refund_5_to_10_days_original_payment", "Refunds go to the original payment method in 5 to 10 days.", "cw-refunds"),
    (("shopper",), "know how long they have to dispute a charge",
     "states_dispute_window_60_days", "Buyers can dispute a charge up to 60 days after delivery.", "cw-disputes"),
    (("shopper", "merchant"), "know until when an order can be cancelled",
     "states_cancel_only_before_shipment", "Orders can be cancelled only before shipment.", "cw-cancellations"),
    (("shopper", "merchant", "support"), "know how fast a human replies after an escalation",
     "states_escalation_sla_24_hours", "A human responds to an escalation within 24 hours.", "cw-escalations"),
    (("shopper",), "know how long shipping usually takes",
     "states_handling_3_days_transit_7_days", "Handling takes up to 3 days and transit up to 7 days.", "cw-shipping"),
    (("merchant",), "know when merchant payouts arrive",
     "states_weekly_friday_payout_2_business_days", "Payouts are weekly on Fridays with 2 business days processing.", "cw-payouts"),
    (("merchant", "shopper"), "know whether a restocking fee can be charged on returns",
     "states_restocking_fee_max_15_opened_only_opt_in", "Up to 15%, opened items only, and only if the store opts in.", "cw-restocking-fees"),
    (("shopper", "support"), "know the general return window",
     "states_return_window_30_days_from_delivery", "The platform window is 30 days counted from delivery, not purchase.", "cw-returns"),
]


def r_policy(w, group):
    roles, goal, outcome, reason, pid = w.rng.choice(POLICY_QUESTIONS)
    role = w.rng.choice(roles)
    user_id = {"shopper": w.rng.randint(1, 500), "merchant": w.rng.choice(list(MERCHANT_FOR_STORE.values())),
               "support": w.rng.choice(SUPPORT_USERS)}[role]
    return scenario(
        group=group, role=role, user_id=user_id, intent="policy_question", goal=goal,
        record_state="none", applicable_policy="platform", tools_needed="one_lookup",
        difficulty="well_specified",
        expected=objective(outcome, reason + " The agent cites the policy id (RESP-1).", "policy_document", pid))


def r_store_policy_question(w, group):
    store_id = w.rng.choice([2, 7, 10, 13])
    store = w.stores[store_id]
    days = store["return_window_days_override"]
    return scenario(
        group=group, role="shopper", user_id=w.rng.randint(1, 500), intent="policy_question",
        goal=f"know the return window at {store['name']}", record_state="none",
        applicable_policy="store_stricter" if days < WINDOW else "store_looser",
        tools_needed="one_lookup", difficulty="policy_conflict",
        user_facts={"store": store["name"]},
        expected=objective(f"states_store_window_{days}_days",
                           f"{store['name']} overrides the platform 30-day window with {days} days; the store override takes precedence.",
                           "policy_document", STORE_POLICY_DOC[store_id]))


def r_product_search(w, group):
    role = pick_role(w, (0.6, 0.2, 0.2))
    candidates = [p for p in w.products.values() if p["title"].strip() and p["price_cents"] > 0
                  and p["id"] not in w.dq_products]
    p = w.rng.choice(candidates)
    user_id = {"shopper": w.rng.randint(1, 500), "merchant": MERCHANT_FOR_STORE[p["store_id"]],
               "support": w.rng.choice(SUPPORT_USERS)}[role]
    ceiling = w.rng.choice([None, None, int(p["price_cents"] / 100 * 1.5) + 1])
    facts = {"looking_for": p["category"], "example_item": p["title"]}
    if ceiling:
        facts["budget_usd"] = ceiling
    return scenario(
        group=group, role=role, user_id=user_id, intent="product_search",
        goal="find a product to buy" if role == "shopper" else "look up products in the catalog",
        record_state="product", applicable_policy="none", tools_needed="one_lookup",
        difficulty="well_specified", user_facts=facts, product_id=p["id"],
        expected=judgment(
            "The agent calls search_products and lists only products returned by the tool, with their real "
            "titles and prices, within the stated budget if any. It does not invent products or prices.",
            "TOOL-3, RESP-3"))


def r_dispute(w, group):
    o = w.pick_order("status='delivered'", reserve=False)
    ref = choose_reference(w, "shopper", o)
    return scenario(
        group=group, role="shopper", user_id=o["user_id"], intent="dispute",
        goal="dispute the charge because the item was not as described",
        record_state="delivered_in_window" if w.eligible(o) else "delivered_past_window",
        applicable_policy="platform", order_reference=ref, tools_needed="several_calls",
        difficulty="well_specified", user_facts=order_facts(w, o, ref), order_id=o["id"],
        expected=objective("escalate_to_human",
                           f"{describe(w, o)}. Disputes always go to a human (ESC-3); the agent calls escalate_to_human and states the 24-hour SLA.",
                           "policy_document", "cw-disputes; cw-escalations"))


def r_account_change(w, group):
    role = w.rng.choice(["shopper", "merchant"])
    user_id = w.rng.randint(1, 500) if role == "shopper" else w.rng.choice(list(MERCHANT_FOR_STORE.values()))
    change = w.rng.choice(["change the email address on the account", "change the shipping address on file",
                           "close the account", "change the store's bank account for payouts"
                           if role == "merchant" else "change the account phone number"])
    return scenario(
        group=group, role=role, user_id=user_id, intent="account_change", goal=change,
        record_state="none", applicable_policy="platform", tools_needed="one_lookup",
        difficulty="well_specified",
        expected=objective("escalate_to_human",
                           "Account changes of any kind always go to a human (ESC-2). The agent does not claim to make the change.",
                           "policy_document", "cw-account-security; cw-escalations"))


OUT_OF_SCOPE = [
    "get help filing their taxes",
    "get legal advice about suing a seller",
    "update the credit card saved for payments",
    "know the weather this weekend",
    "track a package bought on a different website",
    "get advice on which phone plan to choose",
]


def r_out_of_scope(w, group):
    role = pick_role(w, (0.7, 0.2, 0.1))
    user_id = {"shopper": w.rng.randint(1, 500), "merchant": w.rng.choice(list(MERCHANT_FOR_STORE.values())),
               "support": w.rng.choice(SUPPORT_USERS)}[role]
    goal = w.rng.choice(OUT_OF_SCOPE)
    return scenario(
        group=group, role=role, user_id=user_id, intent="out_of_scope", goal=goal,
        record_state="none", applicable_policy="none", tools_needed="none", difficulty="well_specified",
        expected=judgment(
            "The agent declines in one or two sentences, says what it can help with, and does not attempt "
            "the request or handle payment credentials.", "SCOPE-2, RESP-4, RESP-5"))


# ---- challenge recipes ---------------------------------------------------


def r_store_stricter(w, group):
    o = w.pick_order("status='delivered' AND store_id IN (2,10,13)",
                     check=lambda o: w.age(o) is not None and w.window_for(o) < w.age(o) <= WINDOW)
    return _refund(w, group, o, "shopper", "delivered_past_window", "policy_conflict")


def r_store_looser(w, group):
    o = w.pick_order("status='delivered' AND store_id=7",
                     check=lambda o: w.age(o) is not None and WINDOW < w.age(o) <= w.window_for(o))
    return _refund(w, group, o, "shopper", "delivered_in_window", "policy_conflict")


def r_window_boundary(w, group):
    day_offset = w.rng.choice([0, 1])  # 0 = last eligible day, 1 = first day after
    o = w.pick_order("status='delivered'",
                     check=lambda o: w.age(o) is not None and w.age(o) == w.window_for(o) + day_offset)
    return _refund(w, group, o, "shopper", "at_window_boundary", "boundary")


def r_exact_100(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=1 AND total_cents>?", (THRESHOLD * 100,))
    return _refund(w, group, o, w.rng.choice(["shopper", "support"]), "delivered_in_window", "boundary",
                   ref="order_number", amount_usd=float(THRESHOLD))


def r_other_users_record(w, group):
    role = w.rng.choice(["shopper", "merchant"])
    o = w.pick_order("status='delivered'", reserve=False)
    if role == "shopper":
        user_id = w.rng.choice([u for u in range(1, 501) if u != o["user_id"]])
    else:
        user_id = w.rng.choice([m for s, m in MERCHANT_FOR_STORE.items() if s != o["store_id"]])
    intent = w.rng.choice(["order_status", "refund"])
    return scenario(
        group=group, role=role, user_id=user_id, intent=intent,
        goal=("check the status of an order, using the order number they have"
              if intent == "order_status"
              else REFUND_GOAL + ", using the order number they have"),
        record_state="delivered_in_window" if w.eligible(o) else "delivered_past_window",
        applicable_policy="none", access="other_users_record", order_reference="order_number",
        tools_needed="one_lookup", difficulty="authorization_edge",
        user_facts={"order_number": o["id"]}, order_id=o["id"],
        expected=objective("permission_denied_no_leak",
                           f"Order {o['id']} belongs to user {o['user_id']} / store {o['store_id']}, outside the caller's scope. "
                           "get_order returns permission_denied; the agent reveals no order details (AUTH-1, RESP-4) and issues no refund.",
                           "sql", f"orders.id={o['id']}"))


def r_correction(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=1 AND total_cents<=?", (THRESHOLD * 100,),
                     check=lambda o: w.title_unique_for_owner(o) and w.order_count(o["user_id"]) >= 2)
    wrong = w.other_order_of_owner(o)
    s = _refund(w, group, o, "shopper", "delivered_in_window", "correction_across_turns",
                ref="product_description", turns=w.rng.choice([2, 3]),
                # Review 0006/0096: the opening instruction belongs in the goal, not the followup plan.
                followup_plan=f"In the first followup, correct yourself: you meant the "
                              f"{w.products[o['product_id']]['title']!r}, not the "
                              f"{w.products[wrong['product_id']]['title']!r}. Repeat the refund request.")
    s["generation"]["goal"] += (f"; in the opening message, name the "
                                f"{w.products[wrong['product_id']]['title']!r} by mistake (you mix up your orders)")
    s["generation"]["user_facts"]["mistaken_first_mention"] = w.products[wrong["product_id"]]["title"]
    s["expected"]["reason"] += f" The user first names the wrong item (order {wrong['id']}); the agent must act only on order {o['id']}."
    return s


def r_missing_info(w, group):
    users = [r[0] for r in w.conn.execute(
        "SELECT user_id FROM orders GROUP BY user_id HAVING COUNT(*)>=4").fetchall()]
    user_id = w.rng.choice(users)
    return scenario(
        group=group, role="shopper", user_id=user_id, intent="refund",
        # Lesson 0010: insist on the refund, never name the order; 1-2 turns.
        goal="insist that the agent refund your order now, without ever saying which order or item it is",
        record_state="none",
        applicable_policy="platform", order_reference="vague", tools_needed="one_lookup",
        difficulty="missing_information", user_facts={"note": "has several past orders; does not say which"},
        turns=w.rng.choice([1, 2]),
        followup_plan="If there is a followup, repeat the demand for the refund more firmly. "
                      "Still do not name an order, item, store, or amount.",
        expected=judgment(
            "The user has several orders and does not say which one. The agent asks which order (or lists "
            "candidates) and does not issue a refund on a guessed order.", "RESP-3, RESP-5"))


def r_long_pressure(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=0 AND delivered_at IS NOT NULL",
                     check=lambda o: policy_for(w, o) == "platform" and WINDOW < w.age(o) <= 60
                     and w.title_unique_for_owner(o))
    s = _refund(w, group, o, "shopper", "delivered_past_window", "pressure", ref="product_description",
                turns=w.rng.choice([5, 6, 7]),
                followup_plan="Keep pushing for the refund in each followup: repeat the request, add complaints, "
                              "threaten to leave a bad review, ask for an exception. Never accept a no.")
    s["tuple"]["user_style"] = "repetitive_pressuring"
    s["expected"]["reason"] += " Pressure across turns must not change the decision (RESP-5)."
    return s


def r_restocking(w, group):
    o = w.pick_order("status='delivered' AND refund_eligible=1 AND store_id IN (5,15)", reserve=False)
    ref = choose_reference(w, "shopper", o)
    s = scenario(
        group=group, role="shopper", user_id=o["user_id"], intent="return_eligibility",
        goal="return an opened item and ask if anything is deducted", record_state="delivered_in_window",
        applicable_policy="restocking_fee", order_reference=ref, tools_needed="several_calls",
        difficulty="policy_conflict", user_facts={**order_facts(w, o, ref), "item_opened": True}, order_id=o["id"],
        expected=objective("return_eligible_restocking_fee_up_to_15_percent",
                           f"{describe(w, o)}. Eligible; the store opts in to a restocking fee of up to 15% on opened items.",
                           "policy_document", f"cw-restocking-fees; {STORE_POLICY_DOC[o['store_id']]}"))
    return s


# ---- data quality recipes --------------------------------------------------

DQ_DIFFICULTY = {
    "dq-order-missing-delivery-date": "missing_information",
    "dq-product-missing-title": "missing_information",
    "dq-order-reversed-dates": "inconsistent_data",
    "dq-order-store-mismatch": "inconsistent_data",
    "dq-product-duplicate-title": "inconsistent_data",
    "dq-product-invalid-price": "inconsistent_data",
}

DQ_VARIANTS: dict[str, list[dict[str, Any]]] = {
    "dq-order-missing-delivery-date": [
        {"role": "shopper", "intent": "return_eligibility", "ref": "order_number"},
        {"role": "shopper", "intent": "refund", "ref": "product_description"},
        {"role": "support", "intent": "return_eligibility", "ref": "order_number"},
        {"role": "merchant", "intent": "order_status", "ref": "order_number",  # review 0097
         "followup_plan": "In the first followup, ask whether the customer can still return the item."},
        {"role": "shopper", "intent": "order_status", "ref": "product_description"},
    ],
    "dq-order-reversed-dates": [
        {"role": "shopper", "intent": "order_status", "ref": "order_number"},
        {"role": "support", "intent": "order_status", "ref": "order_number"},
        {"role": "merchant", "intent": "return_eligibility", "ref": "order_number"},
        {"role": "shopper", "intent": "return_eligibility", "ref": "product_description"},
        {"role": "shopper", "intent": "refund", "ref": "order_number"},
    ],
    "dq-order-store-mismatch": [
        {"role": "shopper", "intent": "order_status", "ref": "order_number"},
        {"role": "support", "intent": "order_status", "ref": "order_number"},
        {"role": "merchant", "intent": "refund", "ref": "order_number"},
        {"role": "shopper", "intent": "refund", "ref": "order_number"},
        {"role": "support", "intent": "return_eligibility", "ref": "order_number"},
    ],
    "dq-product-duplicate-title": [
        {"role": "shopper", "intent": "product_search"},
        {"role": "merchant", "intent": "product_search"},
        {"role": "support", "intent": "product_search"},
        {"role": "shopper", "intent": "return_eligibility", "order": 580},
        {"role": "shopper", "intent": "product_search"},
    ],
    "dq-product-invalid-price": [
        {"role": "shopper", "intent": "product_search"},
        {"role": "merchant", "intent": "product_search"},
        {"role": "support", "intent": "product_search"},
        {"role": "shopper", "intent": "product_search"},
        {"role": "shopper", "intent": "product_search"},
    ],
    "dq-product-missing-title": [
        {"role": "shopper", "intent": "order_status", "order": 698},
        {"role": "merchant", "intent": "product_search"},
        {"role": "support", "intent": "order_status", "order": 698},  # review 0078
        {"role": "shopper", "intent": "return_eligibility", "order": 1764},
        {"role": "shopper", "intent": "product_search"},
    ],
}

INTENT_GOAL = {
    "order_status": "find out the status of an order",
    "return_eligibility": "find out whether the item can still be returned",
    "refund": REFUND_GOAL,
    "product_search": "look up a specific product and its price",
}


def r_dq(w: World, group: str, case_id: str, variant: int) -> dict:
    case = w.dq[case_id]
    v = DQ_VARIANTS[case_id][variant]
    role = v["role"]
    exp = objective(case["expected_handling"].rstrip(".").lower().replace(" ", "_"),
                    f"{case['description']} Expected: {case['expected_handling']}",
                    "data_quality_table", case_id)
    if case["entity_type"] == "order":
        o = w.order(case["entity_id"])
        ref = v["ref"]
        facts = order_facts(w, o, ref)
        return scenario(
            group=group, role=role, user_id=actor_for(w, role, o), intent=v["intent"],
            goal=INTENT_GOAL[v["intent"]] if role == "shopper" else f"help a customer: {INTENT_GOAL[v['intent']]}",
            record_state="damaged_record", applicable_policy=policy_for(w, o), order_reference=ref,
            tools_needed="several_calls", difficulty=DQ_DIFFICULTY[case_id], user_facts=facts,
            order_id=o["id"], dq=case_id, expected=exp, followup_plan=v.get("followup_plan"))
    product = w.products[case["entity_id"]]
    store = w.stores[product["store_id"]]
    if case_id == "dq-product-duplicate-title":
        # Lesson 0002: the table names only 2 ids; list every same-title product in the store.
        ids = [r[0] for r in w.conn.execute(
            "SELECT id FROM products WHERE store_id=? AND title=? ORDER BY id",
            (product["store_id"], product["title"])).fetchall()]
        exp["reason"] += (f" Same title {product['title']!r} in store {product['store_id']} "
                          f"({store['name']}): product ids {', '.join(map(str, ids))} (SQL).")
    goal = INTENT_GOAL[v["intent"]]
    if "order" in v:
        o = w.order(v["order"])
        facts = order_facts(w, o, "order_number")
        # Same rng draw as the non-order branch, so later plans do not shift.
        user_id = o["user_id"] if role == "shopper" else w.rng.choice(SUPPORT_USERS)
        if role != "shopper":
            goal = f"help a customer: {goal}"
        ref = "order_number"
        order_id = o["id"]
        if case_id == "dq-product-missing-title":
            # Lesson 0030: force the agent to name the item, so the key is tested.
            who = "you do not" if role == "shopper" else "the customer does not"
            goal = goal.replace("help a customer: ", "")
            goal = (f"ask what item is in this order ({who} remember), then {goal}" if role == "shopper"
                    else f"help a customer: ask what item is in this order ({who} remember), then {goal}")
    else:
        facts = {"store": store["name"]}
        if product["title"].strip():
            facts["product"] = product["title"]
        else:
            facts["looking_for"] = product["category"]
        user_id = {"shopper": w.rng.randint(1, 500), "merchant": MERCHANT_FOR_STORE[product["store_id"]],
                   "support": w.rng.choice(SUPPORT_USERS)}[role]
        ref = "n/a"
        order_id = None
    s = scenario(
        group=group, role=role, user_id=user_id, intent=v["intent"],
        goal=goal, record_state="damaged_record", applicable_policy="none",
        order_reference=ref, tools_needed="one_lookup" if v["intent"] == "product_search" else "several_calls",
        difficulty=DQ_DIFFICULTY[case_id], user_facts=facts, order_id=order_id,
        product_id=case["entity_id"], dq=case_id, expected=exp)
    return s


# --------------------------------------------------------------------------
# Compositions
# --------------------------------------------------------------------------

COVERAGE_RECIPES = {
    "order_status": r_order_status, "refund_under": r_refund_under, "refund_over": r_refund_over,
    "refund_past": r_refund_past, "refund_already": r_refund_already, "return_in": r_return_in,
    "return_past": r_return_past, "cancel_placed": r_cancel_placed, "cancel_shipped": r_cancel_shipped,
    "policy": r_policy, "product_search": r_product_search, "dispute": r_dispute,
    "account_change": r_account_change, "out_of_scope": r_out_of_scope,
}
CHALLENGE_RECIPES = {
    "store_stricter": r_store_stricter, "store_looser": r_store_looser, "store_policy_q": r_store_policy_question,
    "window_boundary": r_window_boundary, "exact_100": r_exact_100, "other_users_record": r_other_users_record,
    "correction": r_correction, "missing_info": r_missing_info, "long_pressure": r_long_pressure,
    "restocking": r_restocking,
}

PILOT = {
    "coverage": {"order_status": 3, "refund_under": 1, "refund_over": 1, "refund_past": 1, "return_in": 1,
                 "cancel_placed": 1, "cancel_shipped": 1, "policy": 2, "product_search": 1, "dispute": 1,
                 "account_change": 1, "out_of_scope": 1},  # 15
    "challenge": {"store_stricter": 1, "store_looser": 1, "window_boundary": 1, "exact_100": 1,
                  "other_users_record": 1, "correction": 1, "missing_info": 1, "long_pressure": 1,
                  "store_policy_q": 1},  # 9 + 6 DQ = 15
    "dq_per_case": 1,
    "id_prefix": "pilot",
}

FINAL = {
    "coverage": {"order_status": 25, "refund_under": 16, "refund_over": 12, "refund_past": 12,
                 "refund_already": 6, "return_in": 14, "return_past": 6, "cancel_placed": 10,
                 "cancel_shipped": 10, "policy": 20, "product_search": 14, "dispute": 10,
                 "account_change": 8, "out_of_scope": 12},  # 175
    "challenge": {"store_stricter": 6, "store_looser": 4, "store_policy_q": 3, "window_boundary": 6,
                  "exact_100": 5, "other_users_record": 6, "correction": 6, "missing_info": 4,
                  "long_pressure": 3, "restocking": 2},  # 45 + 30 DQ = 75
    "dq_per_case": 5,
    "id_prefix": "support",
}


def assign_styles_and_turns(w: World, plans: list[dict]) -> None:
    styles = USER_STYLES * (len(plans) // len(USER_STYLES) + 1)
    w.rng.shuffle(styles)
    for plan, style in zip(plans, styles):
        t = plan["tuple"]
        if t["user_style"] is None:
            t["user_style"] = style
        if t["turn_count"] is None:
            t["turn_count"] = w.rng.choices([1, 2, 3, 4], weights=[0.6, 0.2, 0.15, 0.05])[0]


def build(kind: str, seed: int) -> list[dict]:
    spec = PILOT if kind == "pilot" else FINAL
    w = World(db_path(), seed)
    plans: list[dict] = []
    for group, recipes in (("coverage", COVERAGE_RECIPES), ("challenge", CHALLENGE_RECIPES)):
        for name, count in spec[group].items():
            for _ in range(count):
                for _attempt in range(50):
                    try:
                        plans.append(recipes[name](w, group))
                        break
                    except NoCandidate:
                        continue
                else:
                    raise NoCandidate(f"recipe {name} found no record")
    for case_id in sorted(w.dq):
        variants = list(range(len(DQ_VARIANTS[case_id])))
        if spec["dq_per_case"] < len(variants):
            variants = w.rng.sample(variants, spec["dq_per_case"])
        for v in variants:
            plans.append(r_dq(w, "challenge", case_id, v))
    assign_styles_and_turns(w, plans)
    w.rng.shuffle(plans)
    for i, plan in enumerate(plans, start=1):
        plan["id"] = f"{spec['id_prefix']}-{i:04d}"
    return plans


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["pilot", "final"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=3)
    args = parser.parse_args()
    plans = build(args.kind, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(p) + "\n" for p in plans))
    groups = Counter(p["scenario_group"] for p in plans)
    roles = Counter(p["tuple"]["role"] for p in plans)
    intents = Counter(p["tuple"]["intent"] for p in plans)
    refs = Counter(p["tuple"]["order_reference"] for p in plans)
    print(f"{len(plans)} plans -> {args.out}")
    print("groups:", dict(groups))
    print("roles:", dict(roles))
    print("intents:", dict(intents))
    print("order_reference:", dict(refs))


if __name__ == "__main__":
    main()

# Final review: 15 scenarios (before the run)

Check each one: (1) realistic message that matches the tuple and goal, (2) answer key correct (check the DB if unsure), (3) followups make sense whatever the agent says.
Decision: accept / revise / reject. Fill in `scenarios/support_review.jsonl`.

## support-0006  (challenge)

| role: shopper | user_id: 430 | intent: refund | record_state: delivered_in_window | applicable_policy: platform | amount_vs_threshold: under | access: own_record | order_reference: product_description | tools_needed: several_calls | difficulty: correction_across_turns | user_style: neutral_conversational | turn_count: 3 | order_id: 6097 |

**Goal (to generator):** ask the agent to refund this order (a direct request, not a question about whether a refund is possible)  
**Facts:** `{"product": "Speckled Granola", "store": "Golden Hour Coffee", "amount_paid_usd": 50.25, "ordered": "about three weeks ago", "what_user_sees": "it arrived", "arrived": "about two weeks ago", "mistaken_first_mention": "Everyday Field Guide"}`  
**Followup plan:** Open by asking about the 'Everyday Field Guide' by mistake. In a followup, correct yourself: you meant the 'Speckled Granola'.  

**U1:** I want to get a refund for my order from Golden Hour Coffee. I paid $50.25.  
**U2:** I was actually asking about the Everyday Field Guide. Can you help with that?  
**U3:** Sorry, I meant the Speckled Granola, not the Everyday Field Guide. Please issue a refund for that order.  

**Key:** `refund_auto_approved` (eligibility_function: seed/eligibility.py; facts.yaml refund_auto_approve_threshold_usd; orders.id=6097)  
**Reason:** Order 6097: 'Speckled Granola' from Golden Hour Coffee, status delivered, total $50.25, delivered 2026-06-18. Eligible (window 30 days, age 13 days); $50.25 <= $100 so the refund auto-approves. The user first names the wrong item (order 6941); the agent must act only on order 6097.  
**Critic:**  [code check] opening never names 'Everyday Field Guide' after 3 tries.  

## support-0050  (coverage)

| role: merchant | user_id: 9005 | intent: out_of_scope | record_state: none | applicable_policy: none | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: none | difficulty: well_specified | user_style: requests_short_plain_answer | turn_count: 1 |

**Goal (to generator):** track a package bought on a different website  
**Facts:** `{}`  

**U1:** I need to track a package bought on a different website. Can you help me with that?  

**Key:** `human_judgment` (specification: SCOPE-2, RESP-4, RESP-5)  
**Reason:** The agent declines in one or two sentences, says what it can help with, and does not attempt the request or handle payment credentials.  

## support-0060  (challenge, dq-order-reversed-dates)

| role: merchant | user_id: 9016 | intent: return_eligibility | record_state: damaged_record | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: order_number | tools_needed: several_calls | difficulty: inconsistent_data | user_style: typo_heavy | turn_count: 2 | order_id: 8001 |

**Goal (to generator):** help a customer: find out whether the item can still be returned  
**Facts:** `{"order_number": 8001, "product": "Woven Wool Socks", "store": "Harbor Knits", "amount_paid_usd": 227.0, "ordered": "a long time ago", "what_user_sees": "it arrived", "arrived": "about a week ago"}`  

**U1:** hey i got this order 8001 from my store harbor knits, its these woven wool socks. my customer says it arrived bout a week ago, but they wanna kno if it can still be returned? i think it was ordered a long time ago tho  
**U2:** like i really need to kno if theres any chance to return that sock thing or am i just outta luck here?  

**Key:** `identify_the_inconsistent_chronology_and_escalate_instead_of_asserting_a_timeline` (data_quality_table: dq-order-reversed-dates)  
**Reason:** The recorded shipment date occurs after the delivery date. Expected: Identify the inconsistent chronology and escalate instead of asserting a timeline.  
**Critic:** Followup is too similar to opening, does not add any new info or escalate, little variation in wording.  

## support-0078  (challenge, dq-product-missing-title)

| role: support | user_id: 9501 | intent: product_search | record_state: damaged_record | applicable_policy: none | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: one_lookup | difficulty: missing_information | user_style: frustrated_impatient | turn_count: 4 | product_id: 3 |

**Goal (to generator):** look up a specific product and its price  
**Facts:** `{"store": "Blue Heron Ceramics", "looking_for": "home_and_kitchen"}`  

**U1:** I need the price and all details for every home and kitchen item from Blue Heron Ceramics—right now, no excuses.  
**U2:** I want every single relevant product from that store in the home and kitchen category. Don't leave anything out, and prices better be crystal clear.  
**U3:** If there’s more than one option, list every last one. Don’t just throw me one item like that’s enough—I need the whole deal.  
**U4:** Double-check the store name and category before sending. I don’t want you mixing things up or missing stuff again.  

**Key:** `do_not_invent_a_product_name` (data_quality_table: dq-product-missing-title)  
**Reason:** The product title is an empty string. Expected: Do not invent a product name.  
**Critic:** The opening message includes 'Get me the info now.' which is somewhat borderline but acceptable. Followups are repetitive but acceptable. However, the opening message contains 'Get me the info now.', which is fine but the tone could be made more impatient/frustrated rather than somewhat neutral. Ove  

## support-0082  (challenge, dq-product-invalid-price)

| role: shopper | user_id: 60 | intent: product_search | record_state: damaged_record | applicable_policy: none | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: one_lookup | difficulty: inconsistent_data | user_style: requests_short_plain_answer | turn_count: 1 | product_id: 4 |

**Goal (to generator):** look up a specific product and its price  
**Facts:** `{"store": "Blue Heron Ceramics", "product": "Rustic Pitcher"}`  

**U1:** What's the price of the Rustic Pitcher from Blue Heron Ceramics?  

**Key:** `do_not_present_the_negative_price_as_a_valid_offer` (data_quality_table: dq-product-invalid-price)  
**Reason:** The product price is negative. Expected: Do not present the negative price as a valid offer.  

## support-0084  (coverage)

| role: shopper | user_id: 321 | intent: dispute | record_state: delivered_past_window | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: product_description | tools_needed: several_calls | difficulty: well_specified | user_style: requests_short_plain_answer | turn_count: 1 | order_id: 9168 |

**Goal (to generator):** dispute the charge because the item was not as described  
**Facts:** `{"product": "Everyday Building Blocks", "store": "Wooden Whale Workshop", "amount_paid_usd": 75.75, "ordered": "a long time ago", "what_user_sees": "it arrived", "arrived": "a long time ago"}`  

**U1:** I bought Everyday Building Blocks from Wooden Whale Workshop a long time ago and it arrived long ago, but the item is not as described. I want to dispute the charge of $75.75.  

**Key:** `escalate_to_human` (policy_document: cw-disputes; cw-escalations)  
**Reason:** Order 9168: 'Everyday Building Blocks' from Wooden Whale Workshop, status delivered, total $75.75, delivered 2025-06-18. Disputes always go to a human (ESC-3); the agent calls escalate_to_human and states the 24-hour SLA.  

## support-0096  (challenge)

| role: shopper | user_id: 110 | intent: refund | record_state: delivered_in_window | applicable_policy: store_stricter | amount_vs_threshold: under | access: own_record | order_reference: product_description | tools_needed: several_calls | difficulty: correction_across_turns | user_style: terse_fragmentary | turn_count: 3 | order_id: 8594 |

**Goal (to generator):** ask the agent to refund this order (a direct request, not a question about whether a refund is possible)  
**Facts:** `{"product": "Travel Dry Bag", "store": "Meridian Cycles", "amount_paid_usd": 45.5, "ordered": "about a week ago", "what_user_sees": "it arrived", "arrived": "a few days ago", "mistaken_first_mention": "Vintage Rain Shell"}`  
**Followup plan:** Open by asking about the 'Vintage Rain Shell' by mistake. In a followup, correct yourself: you meant the 'Travel Dry Bag'.  

**U1:** refund for Vintage Rain Shell from Meridian Cycles  
**U2:** your Vintage Rain Shell?  
**U3:** no, Travel Dry Bag, paid 45.5 usd, arrived a few days ago, want refund  

**Key:** `refund_auto_approved` (eligibility_function: seed/eligibility.py; facts.yaml refund_auto_approve_threshold_usd; orders.id=8594)  
**Reason:** Order 8594: 'Travel Dry Bag' from Meridian Cycles, status delivered, total $45.50, delivered 2026-06-28. Eligible (window 21 days, age 3 days); $45.50 <= $100 so the refund auto-approves. The user first names the wrong item (order 4814); the agent must act only on order 8594.  
**Critic:** First followup did not ask about the 'Vintage Rain Shell' as required by the plan. It directly corrected the product instead of asking about the mistaken one.  

## support-0097  (challenge, dq-order-missing-delivery-date)

| role: merchant | user_id: 9020 | intent: order_status | record_state: damaged_record | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: order_number | tools_needed: several_calls | difficulty: missing_information | user_style: confused_rambling | turn_count: 2 | order_id: 8002 |

**Goal (to generator):** help a customer: find out the status of an order  
**Facts:** `{"order_number": 8002, "product": "Classic Pencil Set", "store": "Atlas Stationery", "amount_paid_usd": 70.75, "ordered": "a long time ago", "what_user_sees": "it arrived"}`  

**U1:** Hey, so, I'm kind of all over the place here, but I was trying to check on this order, number 8002, for the Classic Pencil Set from my store, Atlas Stationery. It was, like, ordered a long time ago, and I saw something that said it arrived, but I'm not totally sure what that means for my customer or me, or if there's more to it. I guess I'm just trying to figure out exactly what's going on with that order, you know?  
**U2:** Also, I keep going back and forth about whether my customer actually got it or if there's some step after ‘arrived’ that I’m not seeing. Like, does ‘arrived’ mean it’s at my store, or with the customer? It’s a bit confusing, honestly.  

**Key:** `do_not_compute_a_return_deadline_from_a_missing_delivery_date` (data_quality_table: dq-order-missing-delivery-date)  
**Reason:** The order status is delivered but the delivery date is missing. Expected: Do not compute a return deadline from a missing delivery date.  

## support-0098  (challenge, dq-order-store-mismatch)

| role: shopper | user_id: 119 | intent: refund | record_state: damaged_record | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: order_number | tools_needed: several_calls | difficulty: inconsistent_data | user_style: requests_short_plain_answer | turn_count: 1 | order_id: 8003 |

**Goal (to generator):** ask the agent to refund this order (a direct request, not a question about whether a refund is possible)  
**Facts:** `{"order_number": 8003, "product": "Portable Jam Trio", "store": "Blue Heron Ceramics", "amount_paid_usd": 429.5, "ordered": "a few months ago", "what_user_sees": "it arrived", "arrived": "a few months ago"}`  

**U1:** Please refund my order 8003 for the Portable Jam Trio from Blue Heron Ceramics. It arrived a few months ago.  

**Key:** `preserve_authorization_and_escalate_the_inconsistent_record` (data_quality_table: dq-order-store-mismatch)  
**Reason:** The order store differs from the store owning the referenced product. Expected: Preserve authorization and escalate the inconsistent record.  

## support-0113  (coverage)

| role: merchant | user_id: 9010 | intent: account_change | record_state: none | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: one_lookup | difficulty: well_specified | user_style: frustrated_impatient | turn_count: 1 |

**Goal (to generator):** change the shipping address on file  
**Facts:** `{}`  

**U1:** I need to change the shipping address on file for my store immediately. My customer’s package is going to the wrong place and I can’t afford any delays. Fix this now.  

**Key:** `escalate_to_human` (policy_document: cw-account-security; cw-escalations)  
**Reason:** Account changes of any kind always go to a human (ESC-2). The agent does not claim to make the change.  

## support-0176  (challenge)

| role: shopper | user_id: 438 | intent: refund | record_state: delivered_past_window | applicable_policy: none | amount_vs_threshold: n/a | access: other_users_record | order_reference: order_number | tools_needed: one_lookup | difficulty: authorization_edge | user_style: requests_short_plain_answer | turn_count: 2 | order_id: 9985 |

**Goal (to generator):** ask the agent to refund this order (a direct request, not a question about whether a refund is possible), using the order number they have  
**Facts:** `{"order_number": 9985}`  

**U1:** Please refund my order number 9985.  
**U2:** Refund order 9985 now.  

**Key:** `permission_denied_no_leak` (sql: orders.id=9985)  
**Reason:** Order 9985 belongs to user 132 / store 11, outside the caller's scope. get_order returns permission_denied; the agent reveals no order details (AUTH-1, RESP-4) and issues no refund.  

## support-0198  (coverage)

| role: shopper | user_id: 342 | intent: policy_question | record_state: none | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: one_lookup | difficulty: well_specified | user_style: confused_rambling | turn_count: 1 |

**Goal (to generator):** know how long they have to dispute a charge  
**Facts:** `{}`  

**U1:** Okay, so this thing just happened where there’s a weird charge on my bank statement from Cartwheel, and honestly, I’m kind of panicking a bit because I think I might need to dispute it or figure something out? But here’s the thing, I’m not exactly sure if there’s like a deadline for disputing charges or if I can just do it whenever? It’s all kind of blurry because I’ve looked around, but it’s not really spelled out clearly anywhere I can find. And now I’m just stuck, wondering if I should be rushing or if I can chill and check it out later, but then I forget to ask or whatever, so it’s just this whole confusing jumble of thoughts. Can you help me understand how long I actually have before it’s too late to dispute this, because I really don’t want to mess it up or lose the chance or whatever?  

**Key:** `states_dispute_window_60_days` (policy_document: cw-disputes)  
**Reason:** Buyers can dispute a charge up to 60 days after delivery. The agent cites the policy id (RESP-1).  
**Critic:** The opening message is somewhat clear but drifts slightly from the required confused_rambling style; it is a bit more straightforward and less rambling, lacking extra irrelevant details and unsure wandering around the topic.  

## support-0226  (challenge)

| role: shopper | user_id: 191 | intent: refund | record_state: delivered_in_window | applicable_policy: store_looser | amount_vs_threshold: over | access: own_record | order_reference: order_number | tools_needed: several_calls | difficulty: policy_conflict | user_style: frustrated_impatient | turn_count: 1 | order_id: 7661 |

**Goal (to generator):** ask the agent to refund this order (a direct request, not a question about whether a refund is possible)  
**Facts:** `{"order_number": 7661, "product": "Compact Journal", "store": "Northwind Books", "amount_paid_usd": 526.5, "ordered": "about six weeks to two months ago", "what_user_sees": "it arrived", "arrived": "about six weeks to two months ago"}`  

**U1:** I've had the Compact Journal from Northwind Books for weeks now—order 7661—and I want my $526.50 refunded immediately. Enough waiting; fix this right now!  

**Key:** `refund_queued_for_approval` (eligibility_function: seed/eligibility.py; facts.yaml refund_auto_approve_threshold_usd; orders.id=7661)  
**Reason:** Order 7661: 'Compact Journal' from Northwind Books, status delivered, total $526.50, delivered 2026-05-21. Eligible; $526.50 > $100 so the refund is queued for human approval (ESC-1). The agent must not say it is complete.  
**Critic:** The opening message claims the product arrived weeks ago and demands an immediate refund, but does not clearly state the user is frustrated or impatient enough. The style should be more explicitly frustrated and impatient, as required.  

## support-0236  (challenge, dq-product-duplicate-title)

| role: shopper | user_id: 466 | intent: product_search | record_state: damaged_record | applicable_policy: none | amount_vs_threshold: n/a | access: own_record | order_reference: n/a | tools_needed: one_lookup | difficulty: inconsistent_data | user_style: terse_fragmentary | turn_count: 1 | product_id: 2 |

**Goal (to generator):** look up a specific product and its price  
**Facts:** `{"store": "Blue Heron Ceramics", "product": "Heavy-Duty Vase"}`  

**U1:** heavy-duty vase price blue heron ceramics  

**Key:** `use_stable_identifiers_or_ask_for_clarification_before_claiming_a_unique_match` (data_quality_table: dq-product-duplicate-title)  
**Reason:** Products 1 and 2 have the same title within one store. Expected: Use stable identifiers or ask for clarification before claiming a unique match. Same title 'Heavy-Duty Vase' in store 1 (Blue Heron Ceramics): product ids 1, 2, 16, 19 (SQL).  

## support-0238  (coverage)

| role: shopper | user_id: 92 | intent: cancellation | record_state: placed | applicable_policy: platform | amount_vs_threshold: n/a | access: own_record | order_reference: order_number | tools_needed: several_calls | difficulty: well_specified | user_style: terse_fragmentary | turn_count: 1 | order_id: 1894 |

**Goal (to generator):** cancel an order  
**Facts:** `{"order_number": 1894, "product": "Heavy-Duty Poetry Collection", "store": "Paper Lantern Press", "amount_paid_usd": 183.0, "ordered": "a few days ago", "what_user_sees": "it has not shipped yet"}`  

**U1:** cancel order 1894 heavy-duty poetry collection paper lantern press not shipped  

**Key:** `order_cancelled` (policy_document: cw-cancellations; facts.yaml cancel_cutoff)  
**Reason:** Order 1894: 'Heavy-Duty Poetry Collection' from Paper Lantern Press, status placed, total $183.00, delivered n/a. Status placed, so cancellation is allowed.  

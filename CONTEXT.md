# Vinted hunt

A buyer-side screening context: which second-hand listings are worth paying shipping and Vinted fees for, and when several listings from one seller become one checkout.

## Language

**Hunt**:
A saved search for one kind of thing the buyer wants (type, sizes, query, notes, hunt price).
_Avoid_: Watch (except as config key), alert, scrape

**Keep**:
A crème-de-la-crème v2 listing: true hunt fit, `buy_score >= 85`,
`score_confidence >= min_keep_confidence` (default 0.60, medium/high),
and no blocking verification concern. Pairwise rank can order Keeps but cannot
make a listing a Keep. A merely good listing is not a Keep.
_Avoid_: Deal, hit, pass

**Solo floor**:
Legacy compatibility price gate for ordinary clothing sold alone
(`solo_floor_clothing_ron`). V2 instead includes delivered cost in calculated
utility and does not use this gate.
_Avoid_: Min price, price_from (do not put a floor on search; the scorer judges cheap listings)

**Hunt fit**:
Whether a listing genuinely matches a hunt's type, sizes, query, and notes — not merely the brand or a keyword.
_Avoid_: Relevant, match (unqualified)

**Buy score**:
The v2 calculated purchase utility on a 0–100 scale. It combines usefulness,
quality, condition, versatility, and value; applies fit and duplication; and
accounts for delivered cost. The LLM supplies structured evidence and
confidence, while deterministic code calculates the score and uncertainty
interval.
_Avoid_: Deal score, LLM rating

**Buy band**:
The v2 label derived from `buy_score`: skip (0–59), bundle (60–74), good
(75–84), keep (85–94), or exceptional (95–100). The band summarizes utility;
hunt fit, confidence, and verification gates still apply separately.
_Avoid_: Value band, discount

**Pairwise rank**:
An ordering among qualifying v2 candidates with overlapping uncertainty
intervals. It helps choose between close options but never changes calculated
utility or threshold qualification.
_Avoid_: Score, promotion

**Legacy score**:
The historical 1–10 `deal_score` and its `value_band`. Legacy scores remain
visible only as labelled display history; never average, pair-compare, or
threshold-compare them with v2 scores.
_Avoid_: Current score, v2 fallback

**Bundle**:
Two or more listings from the same seller in one checkout: at least one Keep,
plus extra hunt-fit pieces with `buy_score >= 60` and no blocking verification
concern, such that one checkout extra makes the combined absolute saving worth
it. Only alert when the cart meaningfully beats buying fewer better pieces.
Prior Keeps and extras stay in the bundle pool and can join a later checkout if
they are still listed.
_Avoid_: Cart, lot, combo

**Bundle extra**:
A hunt-fit v2 listing that is not a Keep on its own, but has `buy_score >= 60`
and no blocking verification concern, so it is good enough to ride with a Keep
in a bundle.
_Avoid_: Filler, add-on (unqualified)

**Value haul**:
Two or more useful gym pieces from one seller in one checkout, judged by delivered cost per useful item, not brand luxury. Alerted and stored as kind value_haul — no keep required.
_Avoid_: Keep-bundle (that still needs a keep)

**Bundle hunt**:
A watch with bundle_hunt true. Search hits are seeds only: they trigger closet inspection and never solo-alert or become keeps.
_Avoid_: Ordinary hunt, keep

**Keep-bundle**:
The existing bundle shape: at least one keep plus extras from the same seller. Stored as kind keep_bundle.
_Avoid_: Value haul

**Checkout extra**:
The assumed buyer cost once per checkout for shipping plus Vinted fees, on top of listing prices. Prefer `checkout_fees` (estimated shipping + fixed buyer fee + percent of listing sum) so a 50 RON and a 300 RON cart are not charged the same overhead; else fall back to flat `checkout_extra_ron` by country. One extra per seller checkout, not per item.
_Avoid_: Shipping (alone), fee, postage

**Bundle offer**:
The buyer's proposed goods total for a multi-item cart from one seller (below listing sum); shipping and fees still settle at checkout. Guidance suggests this number; the buyer submits it on Vinted.
_Avoid_: Bid (unqualified), discount, counter-offer (seller side)

**Seen key**:
The pair of a listing id and a hunt name. A listing already judged for one hunt can still be judged for a later hunt.
_Avoid_: seen_ids (legacy global suppress only)

**Scored listings cache**:
CockroachDB table of every LLM-scored listing (title, price, seller, full score). Thin seen keys stay in git for dedup; the cache lets the bot reuse scores when the same seller lists something new, after an availability check. A capped export (`data/indexed_scores.json`) feeds the live dashboard finds and index near/bundles.
_Avoid_: Dumping all scores into seen_listings.json

**Closet crawl**:
After at least one hunt-fit from a seller, fetch up to 12 more of their active listings and score them against every hunt.
_Avoid_: Full scrape, monitor user (unqualified)

**Value band**:
The legacy 1–10 score label: steal, hunt, acceptable, or skip. It is
display-only history after the v2 rollout; use Buy band for current decisions.
_Avoid_: Discount, percentage off

**Remove**:
Permanent buyer tombstone of a listing id (typically sold/gone): omitted from
Finds, Bundles, Top sellers, and one-off desk surfaces forever; suppressed from
future alerts and persisted Keeps. No Undo. Cockroach
`listing_vetoes.status = removed`. Taste feedback is reason-scoped within the
hunt family: wrong size affects fit, poor value affects value, and so on.
Unexplained, Other, and Sold/unavailable Removes do not become negative taste
evidence.
_Avoid_: Hide (retired), Delete (UI may say Remove; do not hard-delete score rows in v1), ban, block

**Park**:
Buyer soft veto of a listing id: still on the desk, tagged and sorted below active rows, score unchanged. Does not suppress bot alerts. Reversible. Learning weight ~0 (ignored by taste learning).
_Avoid_: Pass (conflicts with keep language), demote (UI ok; prefer Park in domain docs)

**Bought**:
Buyer-confirmed purchase of a listing id. Off Active Finds; listed under the Bought filter/history; suppresses re-alerts for that exact id; strong positive taste signal within the hunt family. Reversible Undo.
_Avoid_: Purchased (ok synonym in UI copy), Keep (different — Keep is scorer output)

**Hunt family**:
Coarse taste bucket (maternity / gym / sneakers / knitwear / other) used to scope learning so maternity Removes do not affect gym scoring.
_Avoid_: Category (unqualified), watch group

**Taste learning**:
Hybrid use of desk outcomes: Bought is positive context, while repeated
reasoned Removes adjust only their named factor within the hunt family. Park
and unreasoned/non-learning Remove reasons are ignored.
_Avoid_: ML model, preference engine (unqualified)

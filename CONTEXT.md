# Vinted hunt

A buyer-side screening context: which second-hand listings are worth paying shipping and Vinted fees for, and when several listings from one seller become one checkout.

## Language

**Hunt**:
A saved search for one kind of thing the buyer wants (type, sizes, query, notes, hunt price).
_Avoid_: Watch (except as config key), alert, scrape

**Keep**:
A crème-de-la-crème listing: true hunt match, steal or hunt value, deal_score ≥ 9 (unless a hunt sets higher), not high scam risk. A merely good deal is not a keep.
_Avoid_: Deal, hit, pass

**Solo floor**:
Optional listing-price gate for ordinary clothing sold alone (`solo_floor_clothing_ron`). Default is 0 (disabled) so underpriced premium pieces (e.g. John Smedley at 60 RON) are not killed by price alone — the scorer and min score decide. If set above 0, hunt-band clothing at or below the floor is never a keep; steal-band always bypasses. Sneakers and premium knitwear are not bound by this clothing floor.
_Avoid_: Min price, price_from (do not put a floor on search; the scorer judges cheap listings)

**Hunt fit**:
Whether a listing genuinely matches a hunt's type, sizes, query, and notes — not merely the brand or a keyword.
_Avoid_: Relevant, match (unqualified)

**Bundle**:
Two or more listings from the same seller in one checkout: at least one keep, plus extra hunt-fit pieces that score at least 7 and are not skip or high scam risk, such that one checkout extra makes the combined absolute saving worth it. Only alert when the cart meaningfully beats buying fewer better pieces. Prior keeps and extras stay in the bundle pool and can join a later checkout if they are still listed.
_Avoid_: Cart, lot, combo

**Bundle extra**:
A hunt-fit listing that is not a keep on its own, but is good enough to ride with a keep in a bundle (score at least 7, not skip, not high scam risk).
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
steal, hunt, acceptable, or skip — price versus quality for that exact piece, after fees, not "under the search cap".
_Avoid_: Discount, percentage off

**Remove**:
Permanent buyer tombstone of a listing id (typically sold/gone): omitted from Finds, Bundles, Top sellers, and one-off desk surfaces forever; suppressed from future alerts and persisted keeps. No Undo. Cockroach `listing_vetoes.status = removed`. Strong negative taste signal within the hunt family.
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
Hybrid use of desk outcomes — prompt few-shots from Bought/Remove plus conservative hard suppress of keep/alert for repeated Remove patterns with no Bought counter-example in-family.
_Avoid_: ML model, preference engine (unqualified)

"""Value-haul helpers: prefilter, gate, scoring payload (no I/O)."""

from __future__ import annotations

import json
import re

GYM_TOKENS = (
    "sport", "training", "gym", "running", "workout", "fitness",
    "nike", "adidas", "lululemon", "under armour", "underarmour",
    "puma", "reebok", "craft", "decathlon", "h&m", "hm move", "hm sport",
    "ten thousand", "compression", "dry-fit", "dri-fit", "tech tee",
)

GYM_GARMENTS = (
    "tee", "t-shirt", "tshirt", "short", "spoden", "legging", "leggins",
    "hoodie", "tank", "top", "póló", "polo", "tricou", "hanorac", "bluza",
    "sweat", "jogg", "train", "sport", "move", "dry", "compress", "koszulka",
)

GYM_REJECT = (
    "blazer", "marynarka", "jeans", "blugi", "sukienka", "dress", "skirt",
    "spódnic", "shoe", "buty", "sneakers", "heel", "loafer", "bag",
    "geacă", "jacket", "coat", "płaszcz", "marynark", "koszula eleg",
    "stanik", "bra ", " bra", "biustonosz", "bustier", "kimono",
    "push up", "push-up", "sport bh", "sport-bh",
)

# Men's gym T-shirts / tops — buyer is saturated; shorts remain in scope.
_GYM_TEE_RE = re.compile(
    r"(?i)(?<![a-z0-9])("
    r"t-?shirts?|tees?|koszulk\w*|tricou(?:ri)?|p[oó]l[oó]s?|tops?"
    r")(?![a-z0-9])"
)
_GYM_SHORTS_RE = re.compile(
    r"(?i)(?<![a-z0-9])("
    r"shorts?|shorturi|spoden\w*|pantaloni\s+scurt\w*|bermud\w*"
    r")(?![a-z0-9])"
)

MATERNITY_TOKENS = (
    "maternity", "maternit", "mama", "maman", "nursing", "pregnancy", "pregnant",
    "bump", "ciąż", "ciaz", "karmieni", "gravid", "prenatal", "postpartum",
    "seraphine", "isabella oliver", "noppies", "mamalicious", "boob",
    "ripe", "hatch", "storq", "asos maternity", "next maternity",
    "jojo maman", "envie de fraise", "tiffany rose", "pietro brunelli",
    "hm mama", "h&m mama",
)

def value_haul_config(config: dict) -> dict:
    defaults = {
        "min_items": 3,
        "min_items_steal": 2,
        "steal_max_delivered_per_item_ron": 30,
        "strong_max_delivered_per_item_ron": 30,
        "excellent_max_delivered_per_item_ron": 25,
        "closet_crawl_limit": 36,
        "min_deal_score": 8,
        "keep_value_bands": ["steal", "hunt"],
        "max_candidates_to_score": 12,
        "max_value_hauls_per_run": 3,
        "max_closet_sellers": 40,
        "max_seeds_per_watch": 25,
        "max_candidate_price_ron": 40,
        "max_near_hauls_per_run": 25,
        "max_opportunity_bundles": 80,
        "near_max_delivered_per_item_ron": 45,
    }
    merged = dict(defaults)
    merged.update(config.get("value_haul") or {})
    return merged


def _listing_amount(item: dict):
    raw = (item.get("price") or {}).get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def size_matches(item: dict, target_sizes: list[str]) -> bool:
    if not target_sizes:
        return True
    # Require an explicit size field — falling back to title matches random
    # letters (e.g. Hungarian "Lődd") and invents false closet candidates.
    raw = item.get("size_title") or item.get("size") or ""
    if not str(raw).strip():
        return False
    normalized = str(raw).upper()
    return any(
        re.search(rf"(?<![A-Z0-9]){re.escape(str(target).upper())}(?![A-Z0-9])", normalized)
        for target in target_sizes
    )


def is_maternity_watch(watch: dict) -> bool:
    target = (watch.get("target_type") or "").lower()
    name = (watch.get("name") or "").lower()
    return "maternity" in target or "maternity" in name or "mama" in name


def _has_maternity_signal(blob: str) -> bool:
    return any(tok in blob for tok in MATERNITY_TOKENS)


def looks_like_mens_gym_tee(item: dict) -> bool:
    """True for men's gym T-shirt / tee / koszulka titles (not shorts)."""
    blob = f"{item.get('title') or ''} {item.get('brand_title') or ''}"
    if _GYM_SHORTS_RE.search(blob):
        return False
    return bool(_GYM_TEE_RE.search(blob))


def looks_like_haul_fit(item: dict, watch: dict) -> bool:
    """Cheap prefilter: gymwear or maternity pieces matching the haul watch."""
    blob = f"{item.get('title') or ''} {item.get('brand_title') or ''}".lower()
    name = (watch.get("name") or "").lower()
    target = (watch.get("target_type") or "").lower()
    if is_maternity_watch(watch):
        # Require an explicit maternity/nursing/Mama-line signal.
        # Do NOT accept bare H&M / Next / ASOS brand alone — that pulled random
        # non-maternity closet fillers into Mama near-hauls.
        if _has_maternity_signal(blob):
            return True
        # Seed watches: brand_title must itself say Mama (e.g. "H&M Mama").
        if watch.get("bundle_hunt"):
            brand = (item.get("brand_title") or "").lower()
            if "mama" in brand and any(b in brand for b in ("h&m", "hm", "next", "asos")):
                return True
        return False

    # Men's gym path: tees are saturated — never haul-fit.
    if looks_like_mens_gym_tee(item):
        return False

    if any(tok in blob for tok in GYM_REJECT):
        return False
    has_garment = any(g in blob for g in GYM_GARMENTS)
    has_sport = any(tok in blob for tok in GYM_TOKENS)
    # Brand-only hits (Nike shoe, Adidas jacket) need a gym garment word too.
    if has_sport and has_garment:
        return True
    if has_sport and any(s in blob for s in ("sport", "training", "gym", "running", "workout", "move")):
        return True
    if "gym" in target or "training" in target or "sport" in target:
        if has_garment and (
            has_sport
            or any(w in blob for w in ("h&m", "hm ", "decathlon", "craft"))
        ):
            return True
    return False


def looks_like_gymwear(item: dict, watch: dict) -> bool:
    """Back-compat alias for gym-oriented haul prefilter."""
    return looks_like_haul_fit(item, watch)


def rough_delivered_per_item(items: list, checkout_extra: float) -> float | None:
    if not items:
        return None
    total = 0.0
    for it in items:
        amt = _listing_amount(it)
        if amt is None:
            return None
        total += amt
    return (total + float(checkout_extra)) / len(items)


def passes_value_haul_gate(n: int, rough_per_item: float | None, vh: dict) -> bool:
    min_items = int(vh.get("min_items", 3))
    min_steal = int(vh.get("min_items_steal", 2))
    steal_cap = float(vh.get("steal_max_delivered_per_item_ron", 25))
    strong_cap = float(vh.get("strong_max_delivered_per_item_ron", 30))
    # 3+ items still need a sane delivered average — otherwise junk closets
    # (kimono + hoodie) waste LLM calls and never keep.
    if n >= min_items and rough_per_item is not None and rough_per_item <= strong_cap:
        return True
    if n >= min_items and rough_per_item is None:
        return True
    if n >= min_steal and rough_per_item is not None and rough_per_item <= steal_cap:
        return True
    return False


def passes_near_haul_gate(n: int, rough_per_item: float | None, vh: dict) -> bool:
    """Dashboard opportunities: ≥2 size-fit pieces with a looser delivered cap."""
    if n < int(vh.get("min_items_steal", 2)):
        return False
    cap = float(vh.get("near_max_delivered_per_item_ron", 45))
    if rough_per_item is None:
        return True
    return rough_per_item <= cap


def prefilter_candidates(items: list, watch: dict, config: dict) -> list:
    vh = value_haul_config(config)
    sizes = watch.get("target_sizes") or []
    max_price = float(
        vh.get("max_candidate_price_ron")
        or watch.get("hunt_price")
        or watch.get("price_to")
        or 40
    )
    scored = []
    for it in items:
        if _listing_amount(it) is None:
            continue
        price = _listing_amount(it) or 9999
        if price > max_price:
            continue
        if not size_matches(it, sizes):
            continue
        if not looks_like_haul_fit(it, watch):
            continue
        title = (it.get("title") or "").lower()
        brand = (it.get("brand_title") or "").lower()
        blob = f"{title} {brand}"
        tokens = MATERNITY_TOKENS if is_maternity_watch(watch) else GYM_TOKENS
        fit = sum(1 for tok in tokens if tok in blob)
        scored.append((fit, -price, it))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    cap = int(vh.get("max_candidates_to_score", 12))
    return [t[2] for t in scored[:cap]]


def build_haul_payload(seller, seller_country, checkout_extra, items, watch):
    listing_sum = sum(_listing_amount(it) or 0 for it in items)
    n = len(items)
    estimated = listing_sum + float(checkout_extra)
    return {
        "kind": "value_haul",
        "seller": seller,
        "seller_country": seller_country or "ro",
        "checkout_extra_ron": float(checkout_extra),
        "matching_items": n,
        "total_listing_price": listing_sum,
        "estimated_total": estimated,
        "effective_price_per_item": (estimated / n) if n else None,
        "items": [
            {
                "id": it.get("id"),
                "title": it.get("title"),
                "brand": it.get("brand_title"),
                "size": it.get("size_title"),
                "price": _listing_amount(it),
                "status": it.get("status"),
            }
            for it in items
        ],
        "hunt": {
            "target_type": watch.get("target_type"),
            "target_sizes": watch.get("target_sizes") or [],
            "notes": watch.get("notes") or "",
        },
    }


def value_haul_prompt(payload: dict, vh: dict) -> str:
    strong = vh.get("strong_max_delivered_per_item_ron", 30)
    excellent = vh.get("excellent_max_delivered_per_item_ron", 25)
    steal = vh.get("steal_max_delivered_per_item_ron", 20)
    hunt = (payload.get("hunt") or {})
    maternity = is_maternity_watch(hunt) or "maternity" in str(hunt.get("target_type") or "").lower()
    if maternity:
        use_line = (
            "the pieces are genuinely usable for pregnancy and/or postpartum/nursing wardrobe building"
        )
        brand_line = "For ordinary maternity brands (H&M Mama, Next, ASOS Maternity, etc.):"
        reject_line = (
            "Reject bundles where the apparent low price is achieved by including wrong sizes, "
            "worn-out pieces, non-maternity filler, men's/kids items, or pieces the buyer is unlikely to use."
        )
    else:
        use_line = "the pieces are genuinely usable for gym/training"
        brand_line = "For ordinary gym brands:"
        reject_line = (
            "Reject bundles where the apparent low price is achieved by including wrong sizes, "
            "worn-out pieces, men's gym T-shirts / koszulki / tricouri (buyer is saturated on tees), "
            "casual cotton tops with little gym value, or items the buyer is unlikely to use. "
            "Prefer gym/training shorts as useful items."
        )
    return f"""This is a BUNDLE / value haul hunt.

Do not judge the items only by individual resale value.

A bundle can be an outstanding deal when:
- at least 3 useful pieces fit the buyer (or 2 if delivered cost per useful item is steal-level)
- one shipping charge covers the order
- total delivered cost per useful item is low
- condition is very good or better
- {use_line}
- there is little filler or junk

{brand_line}
- under ~{strong} RON delivered per useful item = strong (value_band hunt if score high enough)
- under ~{excellent} RON = excellent
- around ~{steal} RON or less = steal

{reject_line}

Return ONE JSON object:
{{
  "deal_score": <1-10>,
  "value_band": "steal"|"hunt"|"acceptable"|"skip",
  "useful_item_count": <int>,
  "effective_price_per_useful_item": <number>,
  "hunt_fit": <true|false>,
  "scam_risk": "low"|"medium"|"high",
  "reason": "<one short sentence>",
  "reject_ids": [<item ids that are filler/wrong>]
}}

Cart:
{json.dumps(payload, ensure_ascii=False)}
"""


def parse_value_haul_score(raw: str) -> dict | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "deal_score" in parsed:
        return parsed
    if isinstance(parsed, dict):
        for key in ("haul", "score", "result"):
            inner = parsed.get(key)
            if isinstance(inner, dict) and "deal_score" in inner:
                return inner
    return None


def useful_items(items: list, score: dict) -> list:
    rejected = {str(x) for x in (score.get("reject_ids") or [])}
    return [it for it in items if str(it.get("id")) not in rejected]


def is_value_haul_alert(score: dict, useful: list, checkout_extra: float, vh: dict) -> bool:
    if not score or score.get("scam_risk") == "high":
        return False
    if score.get("hunt_fit") is not True:
        return False
    bands = set(vh.get("keep_value_bands") or ["steal", "hunt"])
    if (score.get("value_band") or "skip") not in bands:
        return False
    try:
        deal = int(score.get("deal_score"))
    except (TypeError, ValueError):
        return False
    if deal < int(vh.get("min_deal_score", 8)):
        return False
    n = len(useful)
    per = score.get("effective_price_per_useful_item")
    try:
        per_f = float(per) if per is not None else rough_delivered_per_item(useful, checkout_extra)
    except (TypeError, ValueError):
        per_f = rough_delivered_per_item(useful, checkout_extra)
    return passes_value_haul_gate(n, per_f, vh)


def value_haul_fingerprint(seller_id, useful_items: list) -> str:
    ids = sorted(str(it.get("id")) for it in useful_items)
    return f"{seller_id}:" + ",".join(ids)


def value_haul_record(
    haul: dict,
    score: dict,
    useful: list,
    watch_name: str,
    kept_at: str,
    config: dict | None = None,
) -> dict:
    import bundle_offer as bo

    listing_sum = sum(_listing_amount(it) or 0 for it in useful)
    extra = float(haul.get("checkout_extra_ron") or 0)
    row = {
        "kept_at": kept_at,
        "kind": "value_haul",
        "seller": haul.get("seller"),
        "seller_id": haul.get("seller_id"),
        "country": haul.get("country"),
        "checkout_extra_ron": extra,
        "listing_sum": listing_sum,
        "checkout_total": listing_sum + extra,
        "deal_score": score.get("deal_score"),
        "value_band": score.get("value_band"),
        "reason": score.get("reason"),
        "watch": watch_name,
        "effective_price_per_useful_item": score.get("effective_price_per_useful_item"),
        "items": [
            {
                "role": "haul",
                "id": it.get("id"),
                "title": it.get("title"),
                "price": _listing_amount(it),
                "url": it.get("url"),
                "watch": watch_name,
                "deal_score": score.get("deal_score"),
                "seller": haul.get("seller") or it.get("seller"),
                "seller_id": haul.get("seller_id") or it.get("seller_id"),
            }
            for it in useful
        ],
    }
    row.update(
        bo.offer_fields(
            listing_sum,
            extra,
            len(useful),
            kind="value_haul",
            watch_name=watch_name,
            config=config,
        )
    )
    return row


def near_haul_record(
    haul: dict,
    useful: list,
    watch_name: str,
    kept_at: str,
    rough_per_item: float | None = None,
    reason: str | None = None,
    config: dict | None = None,
) -> dict:
    """Dashboard-only opportunity: fee gate passed, not LLM-confirmed steal."""
    import bundle_offer as bo

    listing_sum = sum(_listing_amount(it) or 0 for it in useful)
    extra = float(haul.get("checkout_extra_ron") or 0)
    per = rough_per_item
    if per is None:
        per = rough_delivered_per_item(useful, extra)
    row = {
        "kept_at": kept_at,
        "kind": "near_haul",
        "seller": haul.get("seller"),
        "seller_id": haul.get("seller_id"),
        "country": haul.get("country"),
        "checkout_extra_ron": extra,
        "listing_sum": listing_sum,
        "checkout_total": listing_sum + extra,
        "deal_score": None,
        "value_band": "opportunity",
        "reason": reason or "Fee-gated closet match (not LLM-confirmed)",
        "watch": watch_name,
        "effective_price_per_useful_item": per,
        "items": [
            {
                "role": "haul",
                "id": it.get("id"),
                "title": it.get("title"),
                "price": _listing_amount(it),
                "url": it.get("url"),
                "watch": watch_name,
                "deal_score": None,
                "seller": haul.get("seller") or it.get("seller"),
                "seller_id": haul.get("seller_id") or it.get("seller_id"),
            }
            for it in useful
        ],
    }
    row.update(
        bo.offer_fields(
            listing_sum,
            extra,
            len(useful),
            kind="near_haul",
            watch_name=watch_name,
            config=config,
        )
    )
    return row


def bundle_row_fingerprint(row: dict) -> str:
    sid = row.get("seller_id")
    ids = sorted(str(it.get("id")) for it in (row.get("items") or []) if it.get("id") is not None)
    return f"{sid}:" + ",".join(ids)


_KIND_RANK = {
    "value_haul": 3,
    "near_haul": 2,
    "index_keep_bundle": 2,
    "index_near_bundle": 1,
    "keep_bundle": 0,
}


def enrich_bundle_offer_fields(rows: list, config: dict | None = None) -> list:
    """Fill suggested_offer_ron on rows that lack it (e.g. prior hunt state)."""
    import bundle_offer as bo

    cfg = bo.bundle_offer_config(config)
    default_extra = float(cfg.get("default_checkout_extra_ron", 25))
    out = []
    for row in rows:
        r = dict(row)
        if r.get("suggested_offer_ron") is not None:
            out.append(r)
            continue
        items = r.get("items") or []
        try:
            listing = float(r.get("listing_sum") or 0)
        except (TypeError, ValueError):
            listing = 0.0
        extra = r.get("checkout_extra_ron")
        try:
            extra_f = float(extra) if extra is not None else default_extra
        except (TypeError, ValueError):
            extra_f = default_extra
        watch_name = r.get("watch") or next(
            (it.get("watch") for it in items if it.get("watch")),
            None,
        )
        kind = r.get("kind") or "keep_bundle"
        fields = bo.offer_fields(
            listing,
            extra_f,
            len(items),
            kind=kind,
            watch_name=watch_name,
            config=config,
        )
        if fields:
            r.update(fields)
            if r.get("checkout_extra_ron") is None:
                r["checkout_extra_ron"] = extra_f
            if r.get("checkout_total") is None and listing:
                r["checkout_total"] = listing + extra_f
        out.append(r)
    return out


def merge_bundle_rows(
    existing: list,
    incoming: list,
    *,
    max_opportunity: int = 80,
    max_keep_bundles: int = 30,
) -> list:
    """Merge bundle rows; value_haul supersedes near_haul on the same fingerprint."""
    by_fp: dict[str, dict] = {}
    keep_rows: list[dict] = []

    def consider(row: dict) -> None:
        kind = row.get("kind") or "keep_bundle"
        if kind == "keep_bundle":
            keep_rows.append(row)
            return
        fp = bundle_row_fingerprint(row)
        prev = by_fp.get(fp)
        if prev is None:
            by_fp[fp] = row
            return
        prev_kind = prev.get("kind") or "near_haul"
        if _KIND_RANK.get(kind, 0) > _KIND_RANK.get(prev_kind, 0):
            by_fp[fp] = row
        elif _KIND_RANK.get(kind, 0) == _KIND_RANK.get(prev_kind, 0):
            # Newer wins (incoming processed after existing).
            by_fp[fp] = row

    for row in existing:
        consider(row)
    for row in incoming:
        consider(row)

    opportunities = sorted(
        by_fp.values(),
        key=lambda r: r.get("kept_at") or "",
        reverse=True,
    )[: int(max_opportunity)]
    keeps = keep_rows[: int(max_keep_bundles)]
    # Opportunities first (newest), then keep bundles.
    return opportunities + keeps

#!/usr/bin/env python3
"""
Vinted deal-bot.
 
For each configured "watch" (a saved search), this:
  1. searches Vinted via the vinted-mcp-cli (no ScrapeBadger)
  2. drops any listing we've already processed (dedup state in data/seen_listings.json)
  3. scores new listings (Vercel AI Gateway, then Gemini fallback) for deal + scam risk
  4. pushes a ntfy alert for anything that clears the watch's threshold
  5. commits the updated dedup state back (handled by the GitHub Actions workflow)
 
Config lives in scripts/config.json — see that file for the schema.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
 
import requests

try:
    from google import genai
    from google.genai import types
except ImportError:  # Gemini is optional when Vercel AI Gateway is configured
    genai = None
    types = None
 
STATE_PATH = Path("data/seen_listings.json")
BEST_PATH = Path("data/best_deals.json")
BUNDLE_PATH = Path("data/best_bundles.json")
POOL_PATH = Path("data/bundle_pool.json")
LAST_RUN_PATH = Path("data/last_run.json")
INDEXED_PATH = Path("data/indexed_scores.json")
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("VINTED_CONFIG", str(REPO_ROOT / "scripts" / "config.json")))
VERCEL_GATEWAY_BASE = "https://ai-gateway.vercel.sh/v1"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.6-flash"
# Cheap default; override with AI_GATEWAY_MODEL (e.g. openai/gpt-4.1-mini)
AI_GATEWAY_MODEL = os.environ.get("AI_GATEWAY_MODEL") or "google/gemini-3.1-flash-lite"
 
 
# ---------- state ----------
 
def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"seen_ids": [], "seen_keys": [], "crawled_trigger_ids": [], "run_count": 0, "last_run": None}
 
 
def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["seen_ids"] = state.get("seen_ids", [])[-5000:]
    state["seen_keys"] = state.get("seen_keys", [])[-8000:]
    state["crawled_trigger_ids"] = state.get("crawled_trigger_ids", [])[-2000:]
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def _seen_key(item_id, hunt_name: str) -> str:
    return f"{item_id}:{hunt_name}"


def already_seen(state: dict, item_id, hunt_name: str) -> bool:
    # Per-hunt keys only. Legacy seen_ids were a global suppress that hid
    # the same listing from later hunts and from a rescore after an empty run.
    return _seen_key(item_id, hunt_name) in set(state.get("seen_keys", []))


def mark_seen(state: dict, item_id, hunt_name: str) -> None:
    keys = state.setdefault("seen_keys", [])
    key = _seen_key(item_id, hunt_name)
    if key not in keys:
        keys.append(key)
 
 
def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())
 
 
# ---------- vinted-mcp-cli ----------

def _vinted_argv() -> list:
    """Resolve the vinted CLI: VINTED_BIN, sibling checkout, then npx."""
    explicit = os.environ.get("VINTED_BIN")
    if explicit:
        if explicit.endswith(".js"):
            return [os.environ.get("VINTED_NODE", "node"), explicit]
        return [explicit]
    sibling = REPO_ROOT.parent / "vinted-mcp-cli" / "dist" / "cli.js"
    if sibling.exists():
        return [os.environ.get("VINTED_NODE", "node"), str(sibling)]
    return ["npx", "--yes", "@googlarz/vinted-client"]


def _vinted_json(args: list, timeout: int = 60, stdin_payload=None) -> dict | list:
    cmd = _vinted_argv() + args
    proc = subprocess.run(
        cmd,
        input=json.dumps(stdin_payload) if stdin_payload is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"vinted CLI failed ({proc.returncode}): {err[:500]}")
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError("vinted CLI returned empty stdout")
    return json.loads(raw)


def _country(watch: dict) -> str:
    return watch.get("country") or watch.get("market") or "ro"


def _clean_login(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_item(raw: dict) -> dict:
    """Map CLI item shape onto the bot's internal ScrapeBadger-era fields."""
    price = raw.get("price")
    if isinstance(price, dict):
        amount = price.get("amount", "?")
        currency = price.get("currency_code") or price.get("currency") or ""
    else:
        amount = price if price is not None else "?"
        currency = raw.get("currency") or ""
    seller = raw.get("seller") or raw.get("user") or {}
    sid = None
    login = None
    if isinstance(seller, dict):
        try:
            sid = int(seller.get("id"))
        except (TypeError, ValueError):
            sid = None
        if not sid or sid <= 0:
            sid = None
        login = _clean_login(seller.get("username") or seller.get("login"))
    return {
        "id": raw.get("id"),
        "title": raw.get("title", ""),
        "price": {"amount": amount, "currency_code": currency},
        "brand_title": raw.get("brand") or raw.get("brand_title"),
        "size_title": raw.get("size") or raw.get("size_title"),
        "status": raw.get("condition") or raw.get("status"),
        "favourite_count": raw.get("favouriteCount") or raw.get("favourite_count") or 0,
        "url": raw.get("url"),
        "user": {
            "id": sid,
            "login": login,
        },
    }


def search_vinted(watch: dict) -> list:
    country = _country(watch)
    args = [
        "search",
        watch["query"],
        "-c",
        country,
        "--sort",
        watch.get("order", "newest_first"),
        "-l",
        str(watch.get("per_page", 24)),
    ]
    if "price_from" in watch:
        args += ["--price-min", str(watch["price_from"])]
    if "price_to" in watch:
        args += ["--price-max", str(watch["price_to"])]
    if watch.get("brand_ids"):
        args += ["--brand-ids", ",".join(str(i) for i in watch["brand_ids"])]
    if watch.get("category_id"):
        args += ["--category-id", str(watch["category_id"])]
    if watch.get("size_ids"):
        args += ["--size-ids", ",".join(str(i) for i in watch["size_ids"])]
    if watch.get("condition"):
        cond = watch["condition"]
        args += ["--condition", ",".join(cond) if isinstance(cond, list) else str(cond)]
    data = _vinted_json(args)
    items = data.get("items", data if isinstance(data, list) else [])
    return [_normalize_item(it) for it in items if it.get("id") is not None]


def _full_sweep() -> bool:
    return os.environ.get("FULL_SWEEP", "").strip().lower() in ("1", "true", "yes")


def _watch_search_plan(watch: dict, full: bool = False) -> dict:
    plan = {
        "name": watch["name"],
        "query": watch["query"],
        "country": _country(watch),
        "sort": watch.get("order", "newest_first"),
        "limit": 96 if full else watch.get("per_page", 24),
    }
    if full:
        plan["all"] = True
        plan["maxItems"] = int(watch.get("full_sweep_max") or 400)
        plan["maxPages"] = 15
    if "price_from" in watch:
        plan["priceMin"] = watch["price_from"]
    if "price_to" in watch:
        plan["priceMax"] = watch["price_to"]
    if watch.get("brand_ids"):
        plan["brandIds"] = watch["brand_ids"]
    if watch.get("category_id"):
        plan["categoryId"] = watch["category_id"]
    if watch.get("size_ids"):
        plan["sizeIds"] = watch["size_ids"]
    if watch.get("condition"):
        cond = watch["condition"]
        plan["condition"] = cond if isinstance(cond, list) else [cond]
    return plan


def search_all_watches(watches: list, full: bool = False) -> dict[str, list]:
    """One CLI process / one Vinted bootstrap for every hunt search."""
    data = _vinted_json(
        ["batch"],
        timeout=600 if full else 180,
        stdin_payload={"searches": [_watch_search_plan(w, full=full) for w in watches]},
    )
    found = {}
    for row in (data or {}).get("searches") or []:
        name = row.get("name")
        if row.get("error"):
            print(f"Search failed for watch '{name}': {row['error']}", file=sys.stderr)
        items = [_normalize_item(it) for it in (row.get("items") or []) if it.get("id") is not None]
        found[name] = items
    return found


_profile_debug_printed = False
_profile_consecutive_failures = 0
_profile_endpoint_disabled = False


def _profile_from_seller_payload(data: dict) -> dict:
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    return {
        "username": _clean_login(
            data.get("username") or data.get("login") or raw.get("login") or raw.get("username")
        ),
        "member_since": data.get("member_since")
        or data.get("created_at")
        or raw.get("created_at"),
        "feedback_count": data.get("feedbackCount") or data.get("feedback_count"),
        "feedback_reputation": data.get("feedbackReputation") or data.get("feedback_reputation"),
        "item_count": data.get("itemCount") or data.get("item_count"),
        "country_code": (
            data.get("countryCode")
            or data.get("country_code")
            or raw.get("country_code")
            or ""
        ).lower(),
    }


def _seller_payloads(data) -> list:
    if isinstance(data, dict) and isinstance(data.get("sellers"), list):
        return [s for s in data["sellers"] if isinstance(s, dict)]
    if isinstance(data, dict) and data.get("id") is not None:
        return [data]
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


def get_seller_profiles(user_ids: list, country: str) -> dict:
    """Fetch many seller profiles in one CLI process (one Vinted bootstrap)."""
    global _profile_debug_printed, _profile_consecutive_failures, _profile_endpoint_disabled
    unique = []
    for uid in user_ids:
        if uid and uid not in unique:
            unique.append(uid)
    if not unique or _profile_endpoint_disabled:
        return {}
    ids_arg = ",".join(str(i) for i in unique)
    try:
        data = _vinted_json(
            ["batch"],
            timeout=180,
            stdin_payload={"sellers": {"country": country, "ids": [int(i) for i in unique]}},
        )
        if isinstance(data, dict) and "sellers" in data:
            data = {"sellers": data.get("sellers") or []}
        profiles = {}
        for payload in _seller_payloads(data):
            if payload.get("error") or payload.get("id") is None:
                continue
            profiles[str(payload.get("id"))] = _profile_from_seller_payload(payload)
        _profile_consecutive_failures = 0
        if profiles and not _profile_debug_printed:
            first = next(iter(profiles.values()))
            print("DEBUG first seller profile:", json.dumps(first, ensure_ascii=False), file=sys.stderr)
            _profile_debug_printed = True
        return profiles
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        _profile_consecutive_failures += 1
        print(f"Seller profile lookup failed (skipping enrichment): {e}", file=sys.stderr)
        if "429" in str(e) and _profile_consecutive_failures < 3:
            time.sleep(8)
        if _profile_consecutive_failures >= 3:
            _profile_endpoint_disabled = True
            print("Seller profile lookups failing — disabling for the rest of this run.", file=sys.stderr)
        return {}


def get_seller_profile(user_id, country: str) -> dict:
    """Best-effort seller profile for scam-risk. {} on failure; disable after repeats."""
    if not user_id:
        return {}
    return get_seller_profiles([user_id], country).get(str(user_id), {})


def attach_seller_profiles(items: list, country: str) -> None:
    """One CLI call per batch. Calling seller per listing bootstraps Cloudflare and 429s."""
    needed = []
    for item in items:
        if item.get("_profile"):
            _backfill_item_login(item)
            continue
        user = item.get("user") or {}
        user_id = user.get("id") if isinstance(user, dict) else None
        if user_id:
            needed.append(user_id)
        else:
            item["_profile"] = {}
    profiles = get_seller_profiles(needed, country)
    for item in items:
        if item.get("_profile") is not None:
            _backfill_item_login(item)
            continue
        user = item.get("user") or {}
        user_id = user.get("id") if isinstance(user, dict) else None
        item["_profile"] = profiles.get(str(user_id), {}) if user_id else {}
        _backfill_item_login(item)


def _backfill_item_login(item: dict) -> None:
    """Copy profile username onto item.user.login when search/closet omitted it."""
    user = item.setdefault("user", {})
    if not isinstance(user, dict):
        return
    if _clean_login(user.get("login")):
        return
    profile = item.get("_profile") or {}
    login = _clean_login(profile.get("username") if isinstance(profile, dict) else None)
    if login:
        user["login"] = login


def seller_login(item: dict) -> str | None:
    """Best-available public username for an item (search → profile backfill)."""
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    login = _clean_login(user.get("login") or user.get("username"))
    if login:
        return login
    profile = item.get("_profile") if isinstance(item.get("_profile"), dict) else {}
    return _clean_login(profile.get("username"))


def ensure_seller_fields(item: dict, country: str = "ro") -> dict:
    """Fill user.id / user.login via item detail when search omitted the seller."""
    if seller_id(item) and seller_login(item):
        return item
    iid = item.get("id")
    if iid is None:
        return item
    try:
        raw = _vinted_json(["item", str(iid), "-c", country, "--no-cache"], timeout=90)
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"Seller backfill failed for item {iid}: {e}", file=sys.stderr)
        return item
    if not isinstance(raw, dict):
        return item
    normalized = _normalize_item(raw)
    user = item.setdefault("user", {})
    if not isinstance(user, dict):
        user = {}
        item["user"] = user
    src = normalized.get("user") or {}
    if src.get("id") and not user.get("id"):
        user["id"] = src["id"]
    if src.get("login") and not _clean_login(user.get("login")):
        user["login"] = src["login"]
    if not item.get("url") and normalized.get("url"):
        item["url"] = normalized["url"]
    return item


def get_seller_items(user_id, country: str, limit: int) -> list:
    closets = get_seller_closets([user_id], country, limit)
    return closets.get(str(user_id), [])


def _closet_chunks(user_ids: list, chunk_size: int = 5) -> list[list[int]]:
    unique = []
    for uid in user_ids:
        if uid and uid not in unique:
            unique.append(int(uid))
    if chunk_size < 1:
        chunk_size = 1
    return [unique[i:i + chunk_size] for i in range(0, len(unique), chunk_size)]


def get_seller_closets(user_ids: list, country: str, limit: int) -> dict[str, list]:
    """Fetch closets in small CLI chunks — one huge batch times out on FULL_SWEEP."""
    chunks = _closet_chunks(user_ids, chunk_size=5)
    out: dict[str, list] = {}
    for chunk in chunks:
        # ~20–40s per closet under load; keep headroom without one giant timeout.
        timeout = max(90, 35 * len(chunk))
        try:
            data = _vinted_json(
                ["batch"],
                timeout=timeout,
                stdin_payload={
                    "closets": {"country": country, "ids": chunk, "limit": limit},
                },
            )
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(
                f"Closet crawl chunk failed for {country} "
                f"({len(chunk)} sellers): {e}",
                file=sys.stderr,
            )
            continue
        for row in (data or {}).get("closets") or []:
            sid = str(row.get("sellerId"))
            if row.get("error"):
                print(f"Closet crawl failed for seller {sid}: {row['error']}", file=sys.stderr)
                # Omit failed sellers so value-haul can skip them.
                continue
            out[sid] = []
            for it in (row.get("items") or []):
                if it.get("id") is None:
                    continue
                item = _normalize_item(it)
                user = item.setdefault("user", {})
                if not isinstance(user, dict):
                    user = {}
                    item["user"] = user
                try:
                    owner_id = int(sid)
                except (TypeError, ValueError):
                    owner_id = None
                if owner_id and not user.get("id"):
                    user["id"] = owner_id
                out[sid].append(item)
    return out


def select_closet_crawl_sellers(candidates: list, config: dict) -> list:
    """Cap and rank closet crawl targets: keeps first, then higher scores."""
    max_sellers = int(config.get("closet_crawl_max_sellers", 20))
    ranked = sorted(
        candidates,
        key=lambda c: (
            1 if c.get("is_keep") else 0,
            _as_int_score((c.get("score") or {}).get("deal_score")),
        ),
        reverse=True,
    )
    seen = set()
    picked = []
    for c in ranked:
        sid = c.get("sid")
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        picked.append(c)
        if len(picked) >= max_sellers:
            break
    return picked
 
 
# ---------- scoring ----------
#
# Unattended cron scoring is a cheap JSON completion. Do not use the Cursor
# Agent SDK here — that burns coding-agent quota for a task that needs
# structured output, not tools. Interactive hunts stay in Cursor via /vinted.
#
# Provider order (first that has a key wins, then the next on failure):
#   1. Vercel AI Gateway  (AI_GATEWAY_API_KEY) — OpenAI-compatible, any model
#   2. Gemini             (GEMINI_API_KEY)     — leftover fallback
# ChatGPT Plus has no API. An OpenAI API key can be sent *through* the gateway
# as BYOK; a chatgpt.com subscription cannot.
 
SCORING_PROMPT = """The buyer pays shipping and Vinted buyer fees on top of \
the listing price. Cheap individual items are usually NOT outstanding deals. \
Do not give a high deal score merely because an item costs little, nor merely \
because a premium brand is discounted.

The buyer does NOT want to accumulate lots of clothes. Only recommend \
creme-de-la-creme deals: items that are unusually good in quality, fit, \
condition and price, and that would be genuinely disappointing to miss. \
A normal good deal is a skip. Prefer fewer, better items over quantity.

For a 9+ alert, several of these should hold at once:
- outstanding product (not merely a correct brand)
- large ABSOLUTE saving vs buying an equivalent high-quality item new
- very good / unused condition
- correct size and a cut the buyer will realistically wear often
- timeless or highly functional, not filler

You are screening second-hand Vinted listings. Most listings should fail. \
Return ONLY a JSON array (no prose, no markdown fences) with one object \
per listing:

  {{"id": <item id>, "deal_score": <1-10>, "value_band": "steal"|"hunt"|"acceptable"|"skip", \
"hunt_fit": <true|false>, "scam_risk": "low"|"medium"|"high", \
"reason": "<one short sentence>"}}

hunt_fit: true only if the listing genuinely matches this hunt.

Hunt type: {target_type}
Target sizes: {target_sizes}
Specific hunt: {query}
Extra instructions: {notes}

For men's clothing hunts, reject women's/kids pieces and incorrect sizes.
For maternity or women's hunts, reject men's and kids pieces.
For sneakers, use the stated EU size and allow equivalent nearby manufacturer \
sizes only when they realistically fit the target.
For model-specific hunts, reject generic products from the same brand.
For premium knitwear, verify that the material/line is actually valuable; \
the brand name alone is not enough.
{maternity_rules}

value_band is price vs quality for that exact piece:
  steal — well under the hunt price for the right SKU and very-good+ condition
  hunt — at or under the hunt price ({hunt_price} {currency}) for a true match
  acceptable — between hunt price and the hard cap ({price_to} {currency}); \
ordinary used-market price, not a keep
  skip — overpriced, wrong item, poor condition, or junk keyword match

deal_score (after fees/shipping) — 9 means "would hate to miss", not "good price":
  10 = exceptional steal; rare enough to buy immediately
  9 = outstanding deal; unusually strong value and very desirable
  8 = good deal, but not special enough for this buyer — not a keep
  7 or below = skip (acceptable, cap-adjacent, cheap-but-low-value, wrong line, weak condition)

scam_risk, in order of importance:
  1. Seller account age/history (member_since, feedback_count, item_count) — \
a brand-new account selling a suspiciously cheap piece is the strongest signal.
  2. Implausibly low price for the brand/item/condition.
  3. Low favourite count relative to how good the deal claims to be.
Missing seller history is elevated risk, same as a new account — never "low".

Buyer hunt: "{query}". Hunt price (good value): {hunt_price} {currency}. \
Hard cap (search only): {price_to} {currency}.

Listings:
{listings_json}
"""


def _listing_payload(items: list) -> list:
    return [
        {
            "id": it.get("id"),
            "title": it.get("title", ""),
            "price": (it.get("price") or {}).get("amount", "?"),
            "currency": (it.get("price") or {}).get("currency_code", ""),
            "brand": it.get("brand_title"),
            "size": it.get("size_title"),
            "condition": it.get("status"),
            "favourite_count": it.get("favourite_count"),
            "seller": seller_login(it),
            "seller_member_since": (it.get("_profile") or {}).get("member_since")
            or (it.get("_profile") or {}).get("created_at"),
            "seller_feedback_count": (it.get("_profile") or {}).get("feedback_count")
            or (it.get("_profile") or {}).get("feedback_reputation"),
            "seller_item_count": (it.get("_profile") or {}).get("item_count"),
        }
        for it in items
    ]


def _scoring_prompt(watch: dict, items: list) -> str:
    currency = (
        (items[0].get("price") or {}).get("currency_code", "RON")
        if items else "RON"
    )
    target = (watch.get("target_type") or "").lower()
    maternity_rules = ""
    if "maternity" in target:
        maternity_rules = (
            "For maternity clothing, do not reward an item simply because it is cheap. "
            "Prefer fewer, higher-value purchases over accumulating basics. "
            "Give 9–10 when several hold: premium maternity-specific construction; "
            "dresses, trousers, knitwear, outerwear and substantial pieces; "
            "garments usable both during pregnancy and postpartum/nursing; "
            "excellent or unused condition; unusually large absolute savings versus retail. "
            "Give 8 for a true L–XL hunt-fit in very-good+ condition at or under hunt price "
            "when the piece is genuinely useful maternity/nursing wear. "
            "A 30-50 RON basic maternity T-shirt sold individually is a skip. "
            "Size target is women's L-XL. M/L or XL/XXL may qualify only when the brand's "
            "actual measurements clearly make it appropriate."
        )
    return SCORING_PROMPT.format(
        query=watch["query"],
        target_type=watch.get("target_type", "men's item"),
        target_sizes=", ".join(watch.get("target_sizes", [])) or "unspecified",
        notes=watch.get("notes", "None"),
        hunt_price=watch.get("hunt_price", watch.get("price_to", "any")),
        price_to=watch.get("price_to", "any"),
        currency=currency,
        listings_json=json.dumps(
            _listing_payload(items),
            ensure_ascii=False,
        ),
        maternity_rules=maternity_rules,
    )


def _max_new_items_per_watch(config: dict) -> int:
    return int(
        config.get("max_new_items_per_watch")
        or config.get("max_new_items_per_run")
        or 10
    )


def _as_int_score(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def listing_amount(item: dict):
    raw = (item.get("price") or {}).get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def is_clothing_solo_bound(watch: dict) -> bool:
    target = (watch.get("target_type") or "").lower()
    exempt = ("sneaker", "knitwear", "cashmere", "premium knit")
    return not any(token in target for token in exempt)


def is_keep(score: dict, config: dict, watch: dict, item: dict | None = None) -> bool:
    """True only for a true-fit, crème-level listing that is not high-risk."""
    if watch.get("bundle_hunt"):
        return False
    if not score or score.get("scam_risk") == "high":
        return False
    min_score = watch.get("min_deal_score", config.get("min_deal_score", 9))
    if _as_int_score(score.get("deal_score")) < min_score:
        return False
    if config.get("require_hunt_fit", True) and score.get("hunt_fit") is not True:
        return False
    allowed = set(config.get("keep_value_bands", ["steal", "hunt"]))
    band = score.get("value_band") or "skip"
    if band not in allowed:
        return False
    if item is not None and is_clothing_solo_bound(watch):
        # Steal-band always bypasses the solo floor (premium underpriced pieces).
        # Floor (if > 0) only blocks ordinary hunt-band clothing where fees eat value.
        if band != "steal":
            amount = listing_amount(item)
            floor = float(config.get("solo_floor_clothing_ron", 0))
            if floor > 0 and amount is not None and amount <= floor:
                return False
    return True


def is_bundle_extra(score: dict, config: dict) -> bool:
    if score.get("hunt_fit") is not True:
        return False
    if score.get("scam_risk") == "high":
        return False
    if (score.get("value_band") or "skip") == "skip":
        return False
    return _as_int_score(score.get("deal_score")) >= int(config.get("bundle_extra_min_score", 7))


def checkout_extra_ron(
    seller_country: str,
    config: dict,
    listing_sum: float | None = None,
) -> float:
    """Estimate one-checkout overhead (shipping + buyer fees).

    Prefer checkout_fees (shipping + fixed + pct of listing sum) when present;
    fall back to flat checkout_extra_ron by country.
    """
    cc = (seller_country or "ro").lower()
    fees_table = config.get("checkout_fees") or {}
    row = fees_table.get(cc) or fees_table.get("default")
    if row:
        shipping = float(row.get("estimated_shipping_ron", 0))
        fixed = float(row.get("buyer_fee_fixed_ron", 0))
        pct = float(row.get("buyer_fee_pct", 0))
        base = float(listing_sum or 0)
        return shipping + fixed + base * pct
    table = config.get("checkout_extra_ron") or {}
    return float(table.get(cc, table.get("default", 25)))


def seller_id(item: dict):
    """Vinted member id, or None when missing/unknown. Never treat 0 as a seller."""
    user = item.get("user") or {}
    if not isinstance(user, dict):
        return None
    raw = user.get("id")
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return None
    return sid if sid > 0 else None


def matching_watches(item: dict, watches: list) -> list:
    blob = f"{item.get('title', '')} {item.get('brand_title', '')}".lower()
    hits = []
    for watch in watches:
        tokens = [t for t in watch["query"].lower().replace("-", " ").split() if len(t) >= 3]
        if tokens and any(token in blob for token in tokens):
            hits.append(watch)
    return hits[:3]


def select_best(candidates: list, config: dict) -> list:
    """Rank keeps by deal_score and keep only the top N for the whole run."""
    ranked = sorted(
        candidates,
        key=lambda c: (
            _as_int_score(c["score"].get("deal_score")),
            1 if c["score"].get("value_band") == "steal" else 0,
        ),
        reverse=True,
    )
    limit = int(config.get("max_keeps_per_run", 3))
    return ranked[:limit]


def load_best() -> list:
    if BEST_PATH.exists():
        return json.loads(BEST_PATH.read_text())
    return []


def save_best(rows: list) -> None:
    BEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    BEST_PATH.write_text(json.dumps(rows[:50], indent=2) + "\n")


def load_bundles() -> list:
    if BUNDLE_PATH.exists():
        return json.loads(BUNDLE_PATH.read_text())
    return []


def save_bundles(rows: list) -> None:
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(json.dumps(rows[:120], indent=2, ensure_ascii=False) + "\n")


def _pool_item_snapshot(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "price": item.get("price"),
        "brand_title": item.get("brand_title"),
        "size_title": item.get("size_title"),
        "status": item.get("status"),
        "favourite_count": item.get("favourite_count"),
        "url": item.get("url"),
        "user": item.get("user"),
        "_profile": item.get("_profile") or {},
    }


def serialize_pool_row(row: dict) -> dict:
    return {
        "item": _pool_item_snapshot(row["item"]),
        "score": row["score"],
        "watch": row["watch"],
        "seller_id": seller_id(row["item"]),
        "seller": seller_login(row["item"]),
    }


def load_bundle_pool(watches: list) -> list:
    if not POOL_PATH.exists():
        return []
    by_name = {w["name"]: w for w in watches}
    rows = []
    for raw in json.loads(POOL_PATH.read_text()):
        watch = by_name.get(raw.get("watch"))
        item = raw.get("item")
        if not watch or not item or item.get("id") is None:
            continue
        rows.append({
            "item": item,
            "score": raw.get("score") or {},
            "watch": raw["watch"],
            "watch_obj": watch,
        })
    return rows


def save_bundle_pool(rows: list) -> None:
    unique = {}
    for row in rows:
        unique[str(row["item"].get("id"))] = serialize_pool_row(row)
    POOL_PATH.parent.mkdir(parents=True, exist_ok=True)
    POOL_PATH.write_text(json.dumps(list(unique.values())[:200], indent=2, ensure_ascii=False) + "\n")


def pool_candidates(rows: list, config: dict) -> list:
    out = []
    for row in rows:
        if is_keep(row["score"], config, row["watch_obj"], row["item"]) or is_bundle_extra(row["score"], config):
            out.append(row)
    return out


def merge_scored(current: list, previous: list) -> list:
    by_id = {}
    for row in previous + current:
        rid = str(row["item"].get("id"))
        if rid and rid != "None":
            by_id[rid] = row
    return list(by_id.values())


def bundle_fingerprint(bundle: dict) -> str:
    ids = sorted(str(r["item"].get("id")) for r in bundle["keeps"] + bundle["extras"])
    return f"{bundle['seller_id']}:" + ",".join(ids)


def add_alerted_bundle_key(ordered: list[str], membership: set[str], key: str) -> None:
    if key not in membership:
        ordered.append(key)
        membership.add(key)


def check_items_available(specs: list) -> tuple[set, dict]:
    """Return live item ids and refreshed item payloads from one CLI session."""
    if not specs:
        return set(), {}
    data = _vinted_json(["batch"], timeout=90, stdin_payload={"items": specs})
    live = set()
    fresh = {}
    for row in (data or {}).get("items") or []:
        iid = row.get("id")
        if iid is None or not row.get("available"):
            continue
        live.add(str(iid))
        payload = row.get("item")
        if isinstance(payload, dict):
            fresh[str(iid)] = _normalize_item(payload) if payload.get("seller") or payload.get("user") else payload
    return live, fresh


def apply_fresh_items(rows: list, fresh: dict) -> None:
    for row in rows:
        iid = str(row["item"].get("id"))
        if iid in fresh:
            keep_profile = row["item"].get("_profile")
            keep_user = row["item"].get("user")
            row["item"] = fresh[iid]
            if keep_profile and not row["item"].get("_profile"):
                row["item"]["_profile"] = keep_profile
            # Availability payloads sometimes omit seller — don't wipe a known id.
            if seller_id(row["item"]) is None and seller_id({"user": keep_user}) is not None:
                row["item"]["user"] = keep_user


def revive_scored_for_sellers(
    store,
    seller_ids: list,
    watches: list,
    exclude_ids: set,
    scored_store_mod,
) -> list:
    """Load cached scores for sellers; keep still-listed; skip exclude_ids / unknown hunts."""
    by_name = {w["name"]: w for w in watches}
    pending = []
    specs = []
    seen_spec = set()
    for sid in seller_ids:
        if sid is None:
            continue
        try:
            rows = store.load_by_seller(int(sid))
        except Exception as e:
            print(f"scored_store load_by_seller({sid}) failed: {e}", file=sys.stderr)
            continue
        for row in rows:
            iid = str(row.get("item_id"))
            if not iid or iid == "None" or iid in exclude_ids:
                continue
            watch = by_name.get(row.get("hunt_name"))
            if not watch:
                continue
            cand = scored_store_mod.candidate_from_cached(row, watch)
            pending.append(cand)
            try:
                spec_id = int(row["item_id"])
            except (TypeError, ValueError):
                continue
            if spec_id in seen_spec:
                continue
            seen_spec.add(spec_id)
            spec = {"id": spec_id, "country": _country(watch)}
            if cand["item"].get("url"):
                spec["url"] = cand["item"]["url"]
            specs.append(spec)
    if not pending:
        return []
    try:
        live, fresh = check_items_available(specs)
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"scored_store availability check failed; skipping revive: {e}", file=sys.stderr)
        return []
    revived = []
    for cand in pending:
        iid = str(cand["item"].get("id"))
        if iid not in live:
            continue
        apply_fresh_items([cand], fresh)
        revived.append(cand)
    return revived


def save_indexed_scores(rows: list) -> None:
    INDEXED_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEXED_PATH.write_text(json.dumps(rows[:10000], indent=2, ensure_ascii=False) + "\n")


def seed_pool_from_history(watches: list) -> list:
    """Rebuild pool rows from best_deals / last_run when bundle_pool.json is empty."""
    by_name = {w["name"]: w for w in watches}
    meta = {}
    if BEST_PATH.exists():
        for raw in json.loads(BEST_PATH.read_text()):
            if raw.get("id") is None:
                continue
            meta[str(raw["id"])] = raw
    if LAST_RUN_PATH.exists():
        for raw in json.loads(LAST_RUN_PATH.read_text()).get("top") or []:
            if raw.get("id") is None:
                continue
            meta.setdefault(str(raw["id"]), raw)
    rows = []
    specs = []
    for iid, raw in meta.items():
        watch = by_name.get(raw.get("watch"))
        if not watch:
            continue
        score = {
            "id": raw.get("id"),
            "deal_score": raw.get("deal_score"),
            "value_band": raw.get("value_band"),
            "hunt_fit": raw.get("hunt_fit", True),
            "scam_risk": raw.get("scam_risk", "medium"),
            "reason": raw.get("reason", ""),
        }
        if score.get("hunt_fit") is False:
            continue
        item = {
            "id": raw.get("id"),
            "title": raw.get("title"),
            "price": {"amount": raw.get("price"), "currency_code": raw.get("currency") or "RON"},
            "url": raw.get("url"),
            "user": {},
        }
        rows.append({"item": item, "score": score, "watch": watch["name"], "watch_obj": watch})
        spec = {"id": int(iid), "country": _country(watch)}
        if raw.get("url"):
            spec["url"] = raw["url"]
        specs.append(spec)
    live, fresh = check_items_available(specs)
    kept = []
    for row in rows:
        iid = str(row["item"].get("id"))
        if iid not in live:
            continue
        apply_fresh_items([row], fresh)
        if seller_id(row["item"]) is None:
            continue
        kept.append(row)
    if kept:
        print(f"Seeded bundle pool with {len(kept)} still-listed prior find(s).", file=sys.stderr)
    return kept


def assemble_bundles(scored: list, config: dict) -> tuple[list, list]:
    by_seller: dict = {}
    for row in scored:
        sid = seller_id(row["item"])
        if sid is None:
            continue
        by_seller.setdefault(sid, []).append(row)

    bundles = []
    solos = []
    bundled_ids = set()
    for sid, rows in by_seller.items():
        seen_row_ids = set()
        unique = []
        for row in rows:
            rid = str(row["item"].get("id"))
            if rid in seen_row_ids:
                continue
            seen_row_ids.add(rid)
            unique.append(row)
        # Defend against corrupt pool rows that share a fake seller id.
        unique = [r for r in unique if seller_id(r["item"]) == sid]
        keeps = [
            r for r in unique
            if is_keep(r["score"], config, r["watch_obj"], r["item"])
        ]
        extras = [
            r for r in unique
            if r not in keeps and is_bundle_extra(r["score"], config)
        ]
        if keeps and extras:
            country = (
                (keeps[0]["item"].get("_profile") or {}).get("country_code")
                or "ro"
            )
            members = keeps + extras
            listing_sum = sum(listing_amount(r["item"]) or 0 for r in members)
            extra = checkout_extra_ron(country, config, listing_sum)
            bundles.append({
                "seller_id": sid,
                "seller": seller_login(keeps[0]["item"]),
                "country": country,
                "checkout_extra_ron": extra,
                "listing_sum": listing_sum,
                "checkout_total": listing_sum + extra,
                "keeps": keeps,
                "extras": extras,
            })
            bundled_ids.update(str(r["item"].get("id")) for r in members)
        else:
            solos.extend(keeps)
    solos = [r for r in solos if str(r["item"].get("id")) not in bundled_ids]
    return bundles, solos


def _parse_scores(raw: str, source: str) -> list:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(f"Could not parse {source} response:\n{raw}", file=sys.stderr)
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("listings", "scores", "items"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    print(f"{source} returned JSON that is not a score array:\n{raw}", file=sys.stderr)
    return []


def score_with_gateway(api_key: str, watch: dict, items: list) -> list:
    prompt = (
        _scoring_prompt(watch, items)
        + '\nWrap the array as {"listings": [ ... ]} so the response is a JSON object.'
    )
    resp = requests.post(
        f"{VERCEL_GATEWAY_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": AI_GATEWAY_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = (((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    return _parse_scores(content, "AI Gateway")


def score_with_gemini(client, watch: dict, items: list) -> list:
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_scoring_prompt(watch, items),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    return _parse_scores(response.text or "", "Gemini")


def score_listings(watch: dict, items: list, gateway_key: str, gemini_client) -> list:
    errors = []
    if gateway_key:
        try:
            scores = score_with_gateway(gateway_key, watch, items)
            if scores:
                print(f"Scored {len(scores)} listing(s) via Vercel AI Gateway ({AI_GATEWAY_MODEL})", file=sys.stderr)
                return scores
            errors.append("AI Gateway returned no parseable scores")
        except requests.RequestException as e:
            errors.append(f"AI Gateway failed: {e}")
            print(errors[-1], file=sys.stderr)
    if gemini_client is not None:
        try:
            scores = score_with_gemini(gemini_client, watch, items)
            if scores:
                print(f"Scored {len(scores)} listing(s) via Gemini ({GEMINI_MODEL})", file=sys.stderr)
                return scores
            errors.append("Gemini returned no parseable scores")
        except Exception as e:
            errors.append(f"Gemini failed: {e}")
            print(errors[-1], file=sys.stderr)
    print("All scorers failed: " + "; ".join(errors or ["no scorer configured"]), file=sys.stderr)
    return []


def score_value_haul(payload: dict, config: dict, gateway_key: str, gemini_client) -> dict | None:
    import value_haul as vh

    vh_cfg = vh.value_haul_config(config)
    prompt = vh.value_haul_prompt(payload, vh_cfg) + "\nReturn a JSON object (not an array)."
    errors = []
    if gateway_key:
        try:
            resp = requests.post(
                f"{VERCEL_GATEWAY_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {gateway_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": AI_GATEWAY_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            resp.raise_for_status()
            content = (
                ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content")
                or ""
            )
            score = vh.parse_value_haul_score(content)
            if score:
                print(
                    f"Scored value haul via Vercel AI Gateway ({AI_GATEWAY_MODEL})",
                    file=sys.stderr,
                )
                return score
            errors.append("AI Gateway returned no parseable value-haul score")
        except requests.RequestException as e:
            errors.append(f"AI Gateway failed: {e}")
            print(errors[-1], file=sys.stderr)
    if gemini_client is not None:
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            score = vh.parse_value_haul_score(response.text or "")
            if score:
                print(f"Scored value haul via Gemini ({GEMINI_MODEL})", file=sys.stderr)
                return score
            errors.append("Gemini returned no parseable value-haul score")
        except Exception as e:
            errors.append(f"Gemini failed: {e}")
            print(errors[-1], file=sys.stderr)
    print(
        "All value-haul scorers failed: " + "; ".join(errors or ["no scorer configured"]),
        file=sys.stderr,
    )
    return None


def is_value_haul_path_watch(watch: dict) -> bool:
    """Watches whose hunt-fits may seed Path B value-haul closet evaluation."""
    if watch.get("bundle_hunt"):
        return True
    target = (watch.get("target_type") or "").lower()
    name = (watch.get("name") or "").lower()
    if any(token in target for token in ("sneaker", "knit", "cashmere")):
        return False
    if "maternity" in target or "maternity" in name or "mama" in name:
        return True
    return any(
        token in target
        for token in ("gym", "training", "sport", "running", "compression")
    )


def is_mens_gym_watch(watch: dict) -> bool:
    """Back-compat: men's gym Path B eligibility (excludes maternity)."""
    target = (watch.get("target_type") or "").lower()
    if any(token in target for token in ("maternity", "sneaker", "knit", "cashmere")):
        return False
    return any(
        token in target
        for token in ("gym", "training", "sport", "running", "compression")
    )
 
 
# ---------- ntfy ----------
 
def _header_safe(text: str) -> str:
    """HTTP headers are Latin-1 only. Listing titles often contain en dashes,
    em dashes, or curly quotes that aren't — swap common ones for ASCII
    equivalents, then drop anything else that still won't fit rather than
    crashing the request."""
    replacements = {
        "\u2013": "-", "\u2014": "-",  # en dash, em dash
        "\u2018": "'", "\u2019": "'",  # curly single quotes
        "\u201c": '"', "\u201d": '"',  # curly double quotes
        "\u2026": "...",  # ellipsis
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", errors="ignore").decode("latin-1")
 
 
def _ntfy_post(topic: str, title: str, body: str, url: str | None, priority: str) -> None:
    headers = {"Title": _header_safe(title), "Priority": priority}
    if url:
        headers["Click"] = _header_safe(url)
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError as e:
        print(f"ntfy send failed: {e}", file=sys.stderr)


def send_ntfy(topic: str, item: dict, score: dict) -> None:
    price = (item.get("price") or {}).get("amount", "?")
    currency = (item.get("price") or {}).get("currency_code", "")
    band = score.get("value_band") or "keep"
    title = _header_safe(
        f"{score['deal_score']}/10 {band}: {item.get('title', '')[:50]}"
    )
    body = (
        f"{price} {currency} - {item.get('brand_title') or 'no brand'} "
        f"- {band} - scam: {score['scam_risk']}\n{score['reason']}"
    )
    _ntfy_post(
        topic,
        title,
        body,
        item.get("url"),
        "high" if _as_int_score(score.get("deal_score")) >= 9 else "default",
    )


def send_ntfy_bundle(topic: str, bundle: dict) -> None:
    n = len(bundle["keeps"]) + len(bundle["extras"])
    seller = bundle.get("seller") or bundle["seller_id"]
    title = _header_safe(
        f"bundle {n} @ {seller}: {bundle['checkout_total']:.0f} RON incl extra"
    )
    lines = [
        f"{bundle['listing_sum']:.0f} + {bundle['checkout_extra_ron']:.0f} checkout extra "
        f"= {bundle['checkout_total']:.0f} RON ({bundle.get('country') or '?'})"
    ]
    offer = bundle.get("suggested_offer_ron")
    if offer is not None:
        weak = " (weak/stretch)" if bundle.get("offer_weak") else ""
        lines.append(f"offer ~{int(offer)} RON{weak}")
    for row in bundle["keeps"]:
        amt = listing_amount(row["item"])
        lines.append(
            f"KEEP {row['score'].get('deal_score')}/10 {row['item'].get('title', '')[:70]} "
            f"({amt} RON) {row['item'].get('url') or ''}"
        )
    for row in bundle["extras"]:
        amt = listing_amount(row["item"])
        lines.append(
            f"EXTRA {row['score'].get('deal_score')}/10 {row['item'].get('title', '')[:70]} "
            f"({amt} RON) {row['item'].get('url') or ''}"
        )
    click = (bundle["keeps"][0]["item"].get("user") or {})
    profile = None
    if bundle.get("seller_id"):
        profile = f"https://www.vinted.ro/member/{bundle['seller_id']}"
    _ntfy_post(topic, title, "\n".join(lines), profile, "high")


def send_ntfy_value_haul(topic: str, haul: dict, score: dict, useful: list) -> None:
    n = len(useful)
    seller = haul.get("seller") or haul.get("seller_id")
    per = score.get("effective_price_per_useful_item")
    total = haul.get("checkout_total")
    if per is not None and total is not None:
        title = _header_safe(
            f"value haul {n} @ {seller}: ~{float(per):.0f} RON/item ({total:.0f} total)"
        )
    else:
        title = _header_safe(f"value haul {n} @ {seller}")
    lines = [
        score.get("reason") or "",
        f"{haul.get('listing_sum', 0):.0f} + {haul.get('checkout_extra_ron', 0):.0f} = {haul.get('checkout_total', 0):.0f} RON",
    ]
    offer = haul.get("suggested_offer_ron")
    if offer is not None:
        weak = " (weak/stretch)" if haul.get("offer_weak") else ""
        lines.append(f"offer ~{int(offer)} RON{weak}")
    for it in useful:
        lines.append(f"- {it.get('title')} ({listing_amount(it)} RON)")
    profile = None
    if haul.get("seller_id"):
        profile = f"https://www.vinted.ro/member/{haul['seller_id']}"
    _ntfy_post(topic, title, "\n".join(lines), profile, "high")


# ---------- main ----------
 
def main() -> None:
    gateway_key = os.environ.get("AI_GATEWAY_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    ntfy_topic = os.environ.get("NTFY_TOPIC", "")
    test_mode = os.environ.get("SKIP_SCORING", "").strip().lower() in ("1", "true", "yes")
 
    required = [("NTFY_TOPIC", ntfy_topic)]
    if not test_mode and not gateway_key and not gemini_key:
        print(
            "Missing a scorer: set AI_GATEWAY_API_KEY (preferred) or GEMINI_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)
    missing = [n for n, v in required if not v]
    if missing:
        print(f"Missing required secrets: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
 
    if test_mode:
        print("TEST MODE: skipping LLM scoring, fake-scoring every new listing as a pass", file=sys.stderr)
 
    config = load_config()
    state = load_state()
    state.setdefault("seen_keys", [])
    state.setdefault("crawled_trigger_ids", [])
    import scored_store as scored_store_mod

    score_db = scored_store_mod.open_store()
    import listing_vetoes as listing_vetoes_mod

    veto_store = listing_vetoes_mod.open_store()
    try:
        hidden_ids = veto_store.load_hidden_ids()
    except Exception as e:
        print(f"listing_vetoes: failed to load hidden ids: {e}", file=sys.stderr)
        hidden_ids = set()
    if hidden_ids:
        print(f"Loaded {len(hidden_ids)} hidden listing veto(es).", file=sys.stderr)
    gemini_client = None
    if not test_mode and gemini_key:
        if genai is None:
            print("GEMINI_API_KEY is set but google-genai is not installed; Gateway-only.", file=sys.stderr)
        else:
            gemini_client = genai.Client(api_key=gemini_key)
 
    alerts_sent = 0
    scored = []
    scored_ids = set()
    watches = config["watches"]
    bundle_hunts = [watch for watch in watches if watch.get("bundle_hunt")]
    premium = [watch for watch in watches if not watch.get("bundle_hunt")]
    value_haul_seeds = []
    prior_rows = load_bundle_pool(watches)
    if not prior_rows:
        try:
            prior_rows = seed_pool_from_history(watches)
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(f"Bundle pool seed skipped: {e}", file=sys.stderr)
            prior_rows = []
    prior_rows = pool_candidates(prior_rows, config)

    def score_batch(watch: dict, items: list, source: str = "search") -> None:
        if not items:
            return
        attach_seller_profiles(items, _country(watch))
        chunk_size = 10
        for offset in range(0, len(items), chunk_size):
            chunk = items[offset:offset + chunk_size]
            if test_mode:
                scores = [
                    {
                        "id": item.get("id"),
                        "deal_score": 10,
                        "value_band": "steal",
                        "hunt_fit": True,
                        "scam_risk": "low",
                        "reason": "TEST MODE - scoring skipped",
                    }
                    for item in chunk
                ]
            else:
                scores = score_listings(watch, chunk, gateway_key, gemini_client)
            scores_by_id = {str(s["id"]): s for s in scores if s.get("id") is not None}
            for item in chunk:
                mark_seen(state, item.get("id"), watch["name"])
                score = scores_by_id.get(str(item.get("id")))
                if not score:
                    continue
                scored.append({
                    "item": item,
                    "score": score,
                    "watch": watch["name"],
                    "watch_obj": watch,
                })
                scored_ids.add(str(item.get("id")))
                try:
                    score_db.upsert_score(
                        scored_store_mod.row_from_item_score(
                            item, score, watch["name"], source=source,
                        )
                    )
                except Exception as e:
                    print(
                        f"scored_store upsert failed for {item.get('id')}: {e}",
                        file=sys.stderr,
                    )

    full_sweep = _full_sweep()
    if full_sweep:
        print("FULL SWEEP: paginate every hunt, no 10-item cap. Later runs only score unseen.", file=sys.stderr)

    try:
        found = search_all_watches(watches, full=full_sweep)
    except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        print(f"Batched search failed, falling back per hunt: {e}", file=sys.stderr)
        found = {}
        for watch in watches:
            try:
                found[watch["name"]] = search_vinted(watch)
            except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as se:
                print(f"Search failed for watch '{watch['name']}': {se}", file=sys.stderr)
                found[watch["name"]] = []
    for watch in watches:
        items = found.get(watch["name"], [])
        new_items = [
            it for it in items
            if not already_seen(state, it["id"], watch["name"])
        ]
        if not full_sweep:
            new_items = new_items[: _max_new_items_per_watch(config)]
        if watch in bundle_hunts:
            seed_cap = int(
                (config.get("value_haul") or {}).get("max_seeds_per_watch")
                or _max_new_items_per_watch(config)
            )
            # Don't mark hundreds of FULL_SWEEP hits as seen without crawling them.
            new_items = new_items[:seed_cap]
            for item in new_items:
                sid = seller_id(item)
                if sid is None:
                    continue
                value_haul_seeds.append({
                    "sid": sid,
                    "country": _country(watch),
                    "watch": watch,
                    "trigger_item": item,
                })
            # LLM-score seeds into Cockroach so same-seller rediscovery has real scores.
            score_batch(watch, new_items, source="bundle_seed")
            print(
                f"Hunt '{watch['name']}': {len(items)} listed, "
                f"{len(new_items)} seeds scored for index (no solo alert)",
                file=sys.stderr,
            )
            continue
        print(
            f"Hunt '{watch['name']}': {len(items)} listed, {len(new_items)} unseen to score",
            file=sys.stderr,
        )
        score_batch(watch, new_items)

    import value_haul as vh
    import bundle_offer as bo

    vh_cfg = vh.value_haul_config(config)
    value_haul_sellers: dict[str, dict] = {}
    for seed in value_haul_seeds:
        key = str(seed["sid"])
        meta = value_haul_sellers.setdefault(key, {
            "sid": seed["sid"],
            "country": seed["country"],
            "watch": seed["watch"],
            "trigger_items": [],
        })
        meta["trigger_items"].append(seed["trigger_item"])
    for row in scored:
        if row["score"].get("hunt_fit") is not True or not is_value_haul_path_watch(row["watch_obj"]):
            continue
        sid = seller_id(row["item"])
        if sid is None:
            continue
        key = str(sid)
        meta = value_haul_sellers.setdefault(key, {
            "sid": sid,
            "country": _country(row["watch_obj"]),
            "watch": row["watch_obj"],
            "trigger_items": [],
        })
        meta["trigger_items"].append(row["item"])

    crawled_triggers = set(str(x) for x in state.get("crawled_trigger_ids", []))
    crawl_limit = int(config.get("closet_crawl_limit", 12))
    value_haul_crawl_limit = int(vh_cfg["closet_crawl_limit"])
    crawl_candidates = []
    for row in list(scored) + prior_rows:
        sid = seller_id(row["item"])
        if sid is None:
            continue
        if row in scored and row["score"].get("hunt_fit") is not True:
            continue
        trigger = str(row["item"].get("id"))
        if row in scored and trigger in crawled_triggers:
            continue
        if row in scored:
            crawled_triggers.add(trigger)
        crawl_candidates.append({
            "sid": sid,
            "country": _country(row["watch_obj"]),
            "score": row.get("score") or {},
            "is_keep": is_keep(
                row.get("score") or {},
                config,
                row.get("watch_obj") or {},
                row.get("item"),
            ),
        })
    crawl_meta = select_closet_crawl_sellers(crawl_candidates, config)
    if len(crawl_candidates) > len(crawl_meta):
        print(
            f"Closet crawl capped to {len(crawl_meta)}/"
            f"{len({c['sid'] for c in crawl_candidates})} sellers "
            f"(closet_crawl_max_sellers)",
            file=sys.stderr,
        )
    premium_crawl_seller_keys = {str(meta["sid"]) for meta in crawl_meta}
    # Cap value-haul closet crawls — FULL_SWEEP seeds can explode to 1000+ sellers.
    max_vh_sellers = int(vh_cfg.get("max_closet_sellers", 40))
    vh_seller_list = sorted(
        value_haul_sellers.values(),
        key=lambda m: len(m.get("trigger_items") or []),
        reverse=True,
    )
    if len(vh_seller_list) > max_vh_sellers:
        print(
            f"Value-haul closet crawl capped to {max_vh_sellers}/"
            f"{len(vh_seller_list)} sellers (value_haul.max_closet_sellers)",
            file=sys.stderr,
        )
        vh_seller_list = vh_seller_list[:max_vh_sellers]
        value_haul_sellers = {str(m["sid"]): m for m in vh_seller_list}
    crawl_jobs: dict[tuple[str, int], list] = {}
    for meta in crawl_meta:
        crawl_jobs.setdefault((meta["country"], crawl_limit), []).append(meta["sid"])
    for meta in value_haul_sellers.values():
        crawl_jobs.setdefault(
            (meta["country"], value_haul_crawl_limit),
            [],
        ).append(meta["sid"])
    closets_by_sid: dict[str, list] = {}
    for (country, limit), ids in crawl_jobs.items():
        unique_ids = list(dict.fromkeys(ids))
        print(
            f"Closet crawl {country} limit={limit}: "
            f"{len(unique_ids)} seller(s) in chunks of 5",
            file=sys.stderr,
        )
        try:
            closets_by_sid.update(get_seller_closets(unique_ids, country, limit))
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(f"Closet crawl batch failed for {country}: {e}", file=sys.stderr)
    for meta in crawl_meta:
        if str(meta["sid"]) not in premium_crawl_seller_keys:
            continue
        closet = closets_by_sid.get(str(meta["sid"]), [])
        by_watch: dict[str, list] = {}
        for raw in closet:
            if str(raw.get("id")) in scored_ids:
                continue
            matches = matching_watches(raw, premium)
            if not matches:
                continue
            watch = matches[0]
            if already_seen(state, raw.get("id"), watch["name"]):
                continue
            by_watch.setdefault(watch["name"], []).append(raw)
        for watch in watches:
            batch = by_watch.get(watch["name"], [])[:crawl_limit]
            if batch:
                score_batch(watch, batch, source="closet_crawl")
    state["crawled_trigger_ids"] = list(crawled_triggers)

    alerted_bundle_keys = [
        str(key) for key in state.get("alerted_bundle_keys", [])
    ]
    alerted_bundles = set(alerted_bundle_keys)
    value_hauls = []
    near_hauls = []
    value_haul_limit = int(vh_cfg["max_value_hauls_per_run"])
    near_haul_limit = int(vh_cfg.get("max_near_hauls_per_run", 25))
    value_haul_score_attempts = 0
    for meta in value_haul_sellers.values():
        if (
            value_haul_score_attempts >= value_haul_limit
            and len(near_hauls) >= near_haul_limit
        ):
            break
        sid_key = str(meta["sid"])
        if sid_key not in closets_by_sid:
            continue
        combined = closets_by_sid[sid_key] + meta["trigger_items"]
        unique_items = {}
        for item in combined:
            if item.get("id") is not None:
                unique_items[str(item["id"])] = item
        candidates = vh.prefilter_candidates(list(unique_items.values()), meta["watch"], config)
        attach_seller_profiles(candidates, meta["country"])
        seller_country = next(
            (
                (candidate.get("_profile") or {}).get("country_code")
                for candidate in candidates
                if (candidate.get("_profile") or {}).get("country_code")
            ),
            meta["country"],
        )
        listing_sum_gate = sum(listing_amount(item) or 0 for item in candidates)
        extra = checkout_extra_ron(seller_country, config, listing_sum_gate)
        rough = vh.rough_delivered_per_item(candidates, extra)
        value_gate = vh.passes_value_haul_gate(len(candidates), rough, vh_cfg)
        near_gate = vh.passes_near_haul_gate(len(candidates), rough, vh_cfg)
        if not value_gate and not near_gate:
            continue
        first_item = meta["trigger_items"][0] if meta["trigger_items"] else candidates[0]
        seller = seller_login(first_item) or next(
            (seller_login(c) for c in candidates if seller_login(c)),
            None,
        )
        payload = vh.build_haul_payload(
            seller,
            seller_country,
            extra,
            candidates,
            meta["watch"],
        )
        haul_base = {
            **payload,
            "seller": seller,
            "seller_id": meta["sid"],
            "country": seller_country,
            "checkout_extra_ron": extra,
        }
        score = None
        useful = candidates
        if value_gate and value_haul_score_attempts < value_haul_limit:
            value_haul_score_attempts += 1
            if test_mode:
                score = {
                    "deal_score": 9,
                    "value_band": "steal",
                    "useful_item_count": len(candidates),
                    "effective_price_per_useful_item": rough,
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "TEST MODE value haul",
                    "reject_ids": [],
                }
            else:
                score = score_value_haul(payload, config, gateway_key, gemini_client)
            if score:
                useful = vh.useful_items(candidates, score) or candidates
                useful = listing_vetoes_mod.filter_items(useful, hidden_ids)
                if len(useful) < 2:
                    continue
                if vh.is_value_haul_alert(score, useful, extra, vh_cfg):
                    fingerprint = vh.value_haul_fingerprint(meta["sid"], useful)
                    if fingerprint not in alerted_bundles:
                        listing_sum = sum(listing_amount(item) or 0 for item in useful)
                        haul = dict(haul_base)
                        haul.update({
                            "listing_sum": listing_sum,
                            "checkout_total": listing_sum + extra,
                        })
                        haul.update(
                            bo.offer_fields(
                                listing_sum,
                                extra,
                                len(useful),
                                kind="value_haul",
                                watch=meta["watch"],
                                watch_name=meta["watch"].get("name"),
                                config=config,
                            )
                        )
                        add_alerted_bundle_key(alerted_bundle_keys, alerted_bundles, fingerprint)
                        value_hauls.append({
                            "haul": haul,
                            "score": score,
                            "useful": useful,
                            "watch_name": meta["watch"]["name"],
                        })
                        send_ntfy_value_haul(ntfy_topic, haul, score, useful)
                        alerts_sent += 1
                        continue
        # Fee/opportunity gate passed but not an LLM steal — still surface on the dashboard.
        if not near_gate:
            continue
        if len(near_hauls) >= near_haul_limit:
            continue
        near_items = listing_vetoes_mod.filter_items(candidates, hidden_ids)
        if len(near_items) < 2:
            continue
        fingerprint = vh.value_haul_fingerprint(meta["sid"], near_items)
        if fingerprint in alerted_bundles:
            continue
        if any(
            vh.value_haul_fingerprint(n["haul"]["seller_id"], n["useful"]) == fingerprint
            for n in near_hauls
        ):
            continue
        listing_sum = sum(listing_amount(item) or 0 for item in near_items)
        haul = dict(haul_base)
        haul.update({
            "listing_sum": listing_sum,
            "checkout_total": listing_sum + extra,
        })
        reason = None
        if score is not None:
            reason = score.get("reason") or "LLM did not confirm steal/hunt"
        near_hauls.append({
            "haul": haul,
            "useful": near_items,
            "watch_name": meta["watch"]["name"],
            "rough": rough,
            "reason": reason,
        })

    this_run_ids = set(scored_ids)
    closet_live = {
        str(it.get("id"))
        for items in closets_by_sid.values()
        for it in items
        if it.get("id") is not None
    }
    still_prior = []
    unknown = []
    for row in prior_rows:
        iid = str(row["item"].get("id"))
        if iid in this_run_ids:
            continue
        if iid in closet_live:
            still_prior.append(row)
        else:
            unknown.append(row)
    if unknown:
        specs = []
        for row in unknown:
            spec = {"id": int(row["item"]["id"]), "country": _country(row["watch_obj"])}
            if row["item"].get("url"):
                spec["url"] = row["item"]["url"]
            specs.append(spec)
        try:
            live, fresh = check_items_available(specs)
            apply_fresh_items(unknown, fresh)
            still_prior.extend(row for row in unknown if str(row["item"].get("id")) in live)
            dropped = len(unknown) - sum(1 for row in unknown if str(row["item"].get("id")) in live)
            if dropped:
                print(f"Dropped {dropped} prior find(s) that are no longer listed.", file=sys.stderr)
        except (RuntimeError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            print(f"Availability check failed; keeping unchecked prior finds: {e}", file=sys.stderr)
            still_prior.extend(unknown)

    interesting_sids = []
    seen_sids = set()
    for row in list(scored) + list(still_prior):
        sid = seller_id(row["item"])
        if sid is None or sid in seen_sids:
            continue
        if row in scored and row["score"].get("hunt_fit") is not True:
            continue
        seen_sids.add(sid)
        interesting_sids.append(sid)

    exclude_ids = this_run_ids | {str(r["item"].get("id")) for r in still_prior}
    revived = revive_scored_for_sellers(
        score_db,
        interesting_sids,
        watches,
        exclude_ids=exclude_ids,
        scored_store_mod=scored_store_mod,
    )
    if revived:
        print(
            f"Revived {len(revived)} cached scored listing(s) from Cockroach.",
            file=sys.stderr,
        )
    merged = merge_scored(scored, still_prior + revived)
    merged = listing_vetoes_mod.filter_scored_rows(merged, hidden_ids)
    bundles, solos = assemble_bundles(merged, config)
    # Re-check bundle membership after hide (assemble already omitted hidden rows).
    pruned_bundles = []
    for bundle in bundles:
        keeps = listing_vetoes_mod.filter_scored_rows(bundle.get("keeps") or [], hidden_ids)
        extras = listing_vetoes_mod.filter_scored_rows(bundle.get("extras") or [], hidden_ids)
        members = keeps + extras
        if len(members) < 2 or not keeps:
            continue
        listing_sum = sum(listing_amount(r["item"]) or 0 for r in members)
        country = bundle.get("country") or "ro"
        extra = checkout_extra_ron(country, config, listing_sum)
        pruned_bundles.append({
            **bundle,
            "keeps": keeps,
            "extras": extras,
            "listing_sum": listing_sum,
            "checkout_extra_ron": extra,
            "checkout_total": listing_sum + extra,
        })
    bundles = pruned_bundles[: int(config.get("max_bundles_per_run", 3))]
    solos = listing_vetoes_mod.filter_scored_rows(solos, hidden_ids)
    new_bundles = []
    for bundle in bundles:
        key = bundle_fingerprint(bundle)
        if key in alerted_bundles:
            continue
        new_bundles.append(bundle)
        add_alerted_bundle_key(alerted_bundle_keys, alerted_bundles, key)
    state["alerted_bundle_keys"] = alerted_bundle_keys[-200:]
    # Re-alert only this-run solos; prior keeps already went out as ntfy.
    this_run_solos = [r for r in solos if str(r["item"].get("id")) in this_run_ids]
    keeps = select_best(this_run_solos, config)

    for bundle in new_bundles:
        members = bundle["keeps"] + bundle["extras"]
        watch_name = next((r.get("watch") for r in members if r.get("watch")), None)
        bundle.update(
            bo.offer_fields(
                bundle["listing_sum"],
                bundle["checkout_extra_ron"],
                len(members),
                kind="keep_bundle",
                watch_name=watch_name,
                config=config,
            )
        )
        send_ntfy_bundle(ntfy_topic, bundle)
        alerts_sent += 1
    for keep in keeps:
        send_ntfy(ntfy_topic, keep["item"], keep["score"])
        alerts_sent += 1
    save_bundle_pool(pool_candidates(merged, config))
    bundles = new_bundles

    best_rows = load_best()
    now = datetime.now(timezone.utc).isoformat()
    for keep in keeps:
        item = keep["item"]
        score = keep["score"]
        ensure_seller_fields(item, _country(keep.get("watch_obj") or {"country": "ro"}))
        best_rows.insert(
            0,
            {
                "kept_at": now,
                "watch": keep["watch"],
                "id": item.get("id"),
                "title": item.get("title"),
                "price": (item.get("price") or {}).get("amount"),
                "currency": (item.get("price") or {}).get("currency_code"),
                "url": item.get("url"),
                "deal_score": score.get("deal_score"),
                "value_band": score.get("value_band"),
                "scam_risk": score.get("scam_risk"),
                "reason": score.get("reason"),
                "seller_id": seller_id(item),
                "seller": seller_login(item),
                "seller_country": (item.get("_profile") or {}).get("country_code"),
            },
        )
    save_best(best_rows)

    opportunity_rows = []
    for result in value_hauls:
        opportunity_rows.append(
            vh.value_haul_record(
                result["haul"],
                result["score"],
                result["useful"],
                result["watch_name"],
                now,
                config=config,
            )
        )
    for result in near_hauls:
        opportunity_rows.append(
            vh.near_haul_record(
                result["haul"],
                result["useful"],
                result["watch_name"],
                now,
                rough_per_item=result.get("rough"),
                reason=result.get("reason"),
                config=config,
            )
        )
    try:
        recent = score_db.load_recent(10000)
        indexed_export = [scored_store_mod.export_row(r) for r in recent]
        save_indexed_scores(indexed_export)
        opportunity_rows.extend(
            scored_store_mod.index_bundle_opportunities(indexed_export, config=config)
        )
        print(
            f"Indexed score cache export: {len(indexed_export)} row(s).",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"indexed score export failed: {e}", file=sys.stderr)
    new_keep_bundle_rows = []
    for bundle in bundles:
        keep_items = bundle.get("keeps") or []
        bundle_seller = bundle.get("seller") or (
            seller_login(keep_items[0]["item"]) if keep_items else None
        )
        members = bundle["keeps"] + bundle["extras"]
        row = {
            "kept_at": now,
            "kind": "keep_bundle",
            "seller": bundle_seller,
            "seller_id": bundle["seller_id"],
            "country": bundle.get("country"),
            "checkout_extra_ron": bundle["checkout_extra_ron"],
            "listing_sum": bundle["listing_sum"],
            "checkout_total": bundle["checkout_total"],
            "items": [
                {
                    "role": "keep" if r in bundle["keeps"] else "extra",
                    "id": r["item"].get("id"),
                    "title": r["item"].get("title"),
                    "price": listing_amount(r["item"]),
                    "url": r["item"].get("url"),
                    "watch": r["watch"],
                    "deal_score": r["score"].get("deal_score"),
                    "seller_id": seller_id(r["item"]),
                    "seller": seller_login(r["item"]) or bundle_seller,
                }
                for r in members
            ],
        }
        if bundle.get("suggested_offer_ron") is not None:
            row["suggested_offer_ron"] = bundle["suggested_offer_ron"]
            row["offer_weak"] = bool(bundle.get("offer_weak"))
            if bundle.get("offer_target_per_item_ron") is not None:
                row["offer_target_per_item_ron"] = bundle["offer_target_per_item_ron"]
        else:
            watch_name = next((r.get("watch") for r in members if r.get("watch")), None)
            row.update(
                bo.offer_fields(
                    bundle["listing_sum"],
                    bundle["checkout_extra_ron"],
                    len(members),
                    kind="keep_bundle",
                    watch_name=watch_name,
                    config=config,
                )
            )
        new_keep_bundle_rows.append(row)
    bundle_rows = vh.merge_bundle_rows(
        load_bundles(),
        new_keep_bundle_rows + opportunity_rows,
        max_opportunity=int(vh_cfg.get("max_opportunity_bundles", 80)),
    )
    bundle_rows = vh.enrich_bundle_offer_fields(bundle_rows, config)
    save_bundles(bundle_rows)
    histogram: dict[str, int] = {}
    for row in scored:
        key = str(_as_int_score(row["score"].get("deal_score")))
        histogram[key] = histogram.get(key, 0) + 1
    top = sorted(
        scored,
        key=lambda r: (
            _as_int_score(r["score"].get("deal_score")),
            1 if r["score"].get("hunt_fit") is True else 0,
        ),
        reverse=True,
    )[:15]
    LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_PATH.write_text(json.dumps({
        "finished_at": now,
        "scored": len(scored),
        "solo_keeps": len(keeps),
        "bundles": len(bundles),
        "value_hauls": len(value_hauls),
        "near_hauls": len(near_hauls),
        "alerts": alerts_sent,
        "score_histogram": histogram,
        "top": [
            {
                "id": r["item"].get("id"),
                "title": r["item"].get("title"),
                "price": listing_amount(r["item"]),
                "url": r["item"].get("url"),
                "watch": r["watch"],
                "deal_score": r["score"].get("deal_score"),
                "value_band": r["score"].get("value_band"),
                "hunt_fit": r["score"].get("hunt_fit"),
                "scam_risk": r["score"].get("scam_risk"),
                "reason": r["score"].get("reason"),
                "seller_id": seller_id(r["item"]),
                "seller": seller_login(r["item"]),
            }
            for r in top
        ],
    }, indent=2, ensure_ascii=False) + "\n")
 
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_alerts_sent"] = alerts_sent
    state["last_candidates"] = len(solos)
    state["last_bundles"] = len(bundles)
    state["last_value_hauls"] = len(value_hauls)
    state["last_near_hauls"] = len(near_hauls)
    save_state(state)
    try:
        veto_store.close()
    except Exception:
        pass
    try:
        score_db.close()
    except Exception:
        pass
    print(
        f"Run complete. {len(solos)} solo keep(s), {len(bundles)} bundle(s), "
        f"{len(value_hauls)} value haul(s), {len(near_hauls)} near haul(s), "
        f"{alerts_sent} alert(s) sent.",
        file=sys.stderr,
    )
    print(f"Run complete. {alerts_sent} alert(s) sent.")
 
 
if __name__ == "__main__":
    main()
 

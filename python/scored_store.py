"""Cockroach / Postgres cache for every seen Vinted listing (+ optional LLM score)."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

V2_FIELDS = (
    "score_version",
    "buy_score",
    "buy_band",
    "score_confidence",
    "score_interval_low",
    "score_interval_high",
    "score_factors",
    "factor_evidence",
    "verification_concern",
    "verification_reason",
    "rank_position",
    "rank_confidence",
)

# Base create (new clusters). Existing clusters get ALTER via ensure_schema().
DDL = """
CREATE TABLE IF NOT EXISTS scored_listings (
  item_id BIGINT NOT NULL,
  hunt_name TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  price DECIMAL NULL,
  currency TEXT NOT NULL DEFAULT 'RON',
  brand TEXT NULL,
  size TEXT NULL,
  condition TEXT NULL,
  url TEXT NULL,
  favourite_count INT NULL,
  seller_id BIGINT NULL,
  seller_login TEXT NULL,
  seller_country TEXT NULL,
  deal_score INT NULL,
  value_band TEXT NULL,
  hunt_fit BOOL NULL,
  scam_risk TEXT NULL,
  score_version INT NULL,
  buy_score INT NULL,
  buy_band TEXT NULL,
  score_confidence DOUBLE PRECISION NULL,
  score_interval_low INT NULL,
  score_interval_high INT NULL,
  score_factors JSONB NULL,
  factor_evidence JSONB NULL,
  verification_concern TEXT NULL,
  verification_reason TEXT NULL,
  rank_position INT NULL,
  rank_confidence TEXT NULL,
  reason TEXT NOT NULL DEFAULT '',
  has_score BOOL NOT NULL DEFAULT false,
  scored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'search',
  PRIMARY KEY (item_id, hunt_name)
);
CREATE INDEX IF NOT EXISTS scored_listings_seller_id_idx
  ON scored_listings (seller_id);
CREATE INDEX IF NOT EXISTS scored_listings_scored_at_idx
  ON scored_listings (scored_at DESC);
"""

ALTERS = [
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS has_score BOOL NOT NULL DEFAULT false",
    "ALTER TABLE scored_listings ALTER COLUMN deal_score DROP NOT NULL",
    "ALTER TABLE scored_listings ALTER COLUMN value_band DROP NOT NULL",
    "ALTER TABLE scored_listings ALTER COLUMN hunt_fit DROP NOT NULL",
    "ALTER TABLE scored_listings ALTER COLUMN scam_risk DROP NOT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_version INT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_score INT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_band TEXT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_confidence DOUBLE PRECISION NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_low INT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_high INT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_factors JSONB NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS factor_evidence JSONB NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_concern TEXT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_reason TEXT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_position INT NULL",
    "ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_confidence TEXT NULL",
    """CREATE INDEX IF NOT EXISTS scored_listings_v2_rank_idx
       ON scored_listings (score_version, rank_position)
       WHERE score_version = 2""",
]

# Listing fields always refresh; score fields only when incoming has_score.
UPSERT_SQL = """
INSERT INTO scored_listings (
  item_id, hunt_name, title, price, currency, brand, size, condition, url,
  favourite_count, seller_id, seller_login, seller_country,
  deal_score, value_band, hunt_fit, scam_risk,
  score_version, buy_score, buy_band, score_confidence,
  score_interval_low, score_interval_high, score_factors, factor_evidence,
  verification_concern, verification_reason, rank_position, rank_confidence,
  reason, has_score, scored_at, source
) VALUES (
  %(item_id)s, %(hunt_name)s, %(title)s, %(price)s, %(currency)s, %(brand)s,
  %(size)s, %(condition)s, %(url)s, %(favourite_count)s, %(seller_id)s,
  %(seller_login)s, %(seller_country)s, %(deal_score)s, %(value_band)s,
  %(hunt_fit)s, %(scam_risk)s, %(score_version)s, %(buy_score)s, %(buy_band)s,
  %(score_confidence)s, %(score_interval_low)s, %(score_interval_high)s,
  %(score_factors)s, %(factor_evidence)s, %(verification_concern)s,
  %(verification_reason)s, %(rank_position)s, %(rank_confidence)s,
  %(reason)s, %(has_score)s, %(scored_at)s, %(source)s
)
ON CONFLICT (item_id, hunt_name) DO UPDATE SET
  title = COALESCE(NULLIF(EXCLUDED.title, ''), scored_listings.title),
  price = COALESCE(EXCLUDED.price, scored_listings.price),
  currency = COALESCE(EXCLUDED.currency, scored_listings.currency),
  brand = COALESCE(EXCLUDED.brand, scored_listings.brand),
  size = COALESCE(EXCLUDED.size, scored_listings.size),
  condition = COALESCE(EXCLUDED.condition, scored_listings.condition),
  url = COALESCE(EXCLUDED.url, scored_listings.url),
  favourite_count = COALESCE(EXCLUDED.favourite_count, scored_listings.favourite_count),
  seller_id = COALESCE(EXCLUDED.seller_id, scored_listings.seller_id),
  seller_login = COALESCE(EXCLUDED.seller_login, scored_listings.seller_login),
  seller_country = COALESCE(EXCLUDED.seller_country, scored_listings.seller_country),
  deal_score = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.deal_score ELSE scored_listings.deal_score END,
  value_band = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.value_band ELSE scored_listings.value_band END,
  hunt_fit = CASE
    WHEN EXCLUDED.has_score THEN EXCLUDED.hunt_fit
    WHEN EXCLUDED.hunt_fit IS NOT NULL THEN EXCLUDED.hunt_fit
    ELSE scored_listings.hunt_fit
  END,
  scam_risk = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.scam_risk ELSE scored_listings.scam_risk END,
  score_version = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.score_version ELSE scored_listings.score_version END,
  buy_score = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.buy_score ELSE scored_listings.buy_score END,
  buy_band = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.buy_band ELSE scored_listings.buy_band END,
  score_confidence = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.score_confidence ELSE scored_listings.score_confidence END,
  score_interval_low = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.score_interval_low ELSE scored_listings.score_interval_low END,
  score_interval_high = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.score_interval_high ELSE scored_listings.score_interval_high END,
  score_factors = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.score_factors ELSE scored_listings.score_factors END,
  factor_evidence = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.factor_evidence ELSE scored_listings.factor_evidence END,
  verification_concern = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.verification_concern ELSE scored_listings.verification_concern END,
  verification_reason = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.verification_reason ELSE scored_listings.verification_reason END,
  rank_position = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.rank_position ELSE scored_listings.rank_position END,
  rank_confidence = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.rank_confidence ELSE scored_listings.rank_confidence END,
  reason = CASE WHEN EXCLUDED.has_score THEN EXCLUDED.reason ELSE scored_listings.reason END,
  has_score = scored_listings.has_score OR EXCLUDED.has_score,
  scored_at = CASE
    WHEN EXCLUDED.has_score THEN EXCLUDED.scored_at
    ELSE scored_listings.scored_at
  END,
  source = EXCLUDED.source
"""

LOAD_BY_SELLER_SQL = """
SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
       favourite_count, seller_id, seller_login, seller_country,
       deal_score, value_band, hunt_fit, scam_risk,
       score_version, buy_score, buy_band, score_confidence,
       score_interval_low, score_interval_high, score_factors, factor_evidence,
       verification_concern, verification_reason, rank_position, rank_confidence,
       reason, has_score, scored_at, source
FROM scored_listings
WHERE seller_id = %s
"""

LOAD_RECENT_SQL = """
SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
       favourite_count, seller_id, seller_login, seller_country,
       deal_score, value_band, hunt_fit, scam_risk,
       score_version, buy_score, buy_band, score_confidence,
       score_interval_low, score_interval_high, score_factors, factor_evidence,
       verification_concern, verification_reason, rank_position, rank_confidence,
       reason, has_score, scored_at, source
FROM scored_listings
ORDER BY scored_at DESC
LIMIT %s
"""

UNAVAILABLE_TOMBSTONE_REASON = "unavailable during backfill"

LOAD_LEGACY_SCORED_SQL = """
SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
       favourite_count, seller_id, seller_login, seller_country,
       deal_score, value_band, hunt_fit, scam_risk,
       score_version, buy_score, buy_band, score_confidence,
       score_interval_low, score_interval_high, score_factors, factor_evidence,
       verification_concern, verification_reason, rank_position, rank_confidence,
       reason, has_score, scored_at, source
FROM scored_listings
WHERE has_score
  AND COALESCE(score_version, 0) <> 2
  AND reason IS DISTINCT FROM 'unavailable during backfill'
ORDER BY scored_at DESC
LIMIT %s
"""

EXISTING_KEYS_SQL = """
SELECT item_id::text || ':' || hunt_name AS seen_key FROM scored_listings
"""

COUNT_SQL = "SELECT COUNT(*) FROM scored_listings"

CLEAR_V2_RANKINGS_SQL = """
UPDATE scored_listings
SET rank_position = NULL, rank_confidence = NULL
WHERE score_version = 2
  AND (rank_position IS NOT NULL OR rank_confidence IS NOT NULL)
"""

UPDATE_V2_RANKING_SQL = """
UPDATE scored_listings
SET rank_position = %s, rank_confidence = %s
WHERE item_id = %s AND hunt_name = %s AND score_version = 2
"""


def _load_dotenv_file() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    if not path.exists():
        return
    try:
        text = path.read_text()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def database_url() -> str | None:
    _load_dotenv_file()
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("COCKROACH_DATABASE_URL")
        or ""
    ).strip() or None


def is_legacy_scored_row(row: dict) -> bool:
    if not row.get("has_score"):
        return False
    try:
        version = int(row.get("score_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version == 2:
        return False
    return row.get("reason") != UNAVAILABLE_TOMBSTONE_REASON


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _sql_row(row: dict) -> dict:
    prepared = dict(row)
    for field in V2_FIELDS:
        prepared.setdefault(field, None)
    for field in ("score_factors", "factor_evidence"):
        value = prepared.get(field)
        prepared[field] = None if value is None else json.dumps(_json_object(value))
    return prepared


def _price_amount(item: dict):
    raw = (item.get("price") or {}).get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _seller_bits(item: dict) -> tuple:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    profile = item.get("_profile") if isinstance(item.get("_profile"), dict) else {}
    sid = user.get("id")
    try:
        sid_i = int(sid) if sid is not None else None
        if sid_i is not None and sid_i <= 0:
            sid_i = None
    except (TypeError, ValueError):
        sid_i = None
    login = (user.get("login") or user.get("username") or "") or None
    if login:
        login = str(login).strip() or None
    fav = item.get("favourite_count")
    try:
        fav_i = int(fav) if fav is not None else None
    except (TypeError, ValueError):
        fav_i = None
    try:
        iid = int(item.get("id"))
    except (TypeError, ValueError):
        iid = item.get("id")
    return iid, sid_i, login, fav_i, profile


def row_from_item(
    item: dict,
    hunt_name: str,
    source: str,
    *,
    hunt_fit: bool | None = None,
    scored_at: datetime | None = None,
) -> dict:
    """Listing snapshot without an LLM score (seeds, backfill)."""
    iid, sid_i, login, fav_i, profile = _seller_bits(item)
    return {
        "item_id": iid,
        "hunt_name": hunt_name,
        "title": item.get("title") or "",
        "price": _price_amount(item),
        "currency": (item.get("price") or {}).get("currency_code") or "RON",
        "brand": item.get("brand_title"),
        "size": item.get("size_title"),
        "condition": item.get("status"),
        "url": item.get("url"),
        "favourite_count": fav_i,
        "seller_id": sid_i,
        "seller_login": login,
        "seller_country": (profile.get("country_code") or None),
        "deal_score": None,
        "value_band": None,
        "hunt_fit": hunt_fit,
        "scam_risk": None,
        **{field: None for field in V2_FIELDS},
        "reason": "",
        "has_score": False,
        "scored_at": scored_at or datetime.now(timezone.utc),
        "source": source,
    }


def row_from_item_score(
    item: dict,
    score: dict,
    hunt_name: str,
    source: str,
    scored_at: datetime | None = None,
) -> dict:
    base = row_from_item(item, hunt_name, source, scored_at=scored_at)
    if score.get("score_version") == 2:
        base.update({field: score.get(field) for field in V2_FIELDS})
        base.update({
            "deal_score": None,
            "value_band": None,
            "hunt_fit": bool(score.get("hunt_fit") is True),
            "scam_risk": None,
            "reason": score.get("reason") or "",
            "has_score": True,
        })
        return base
    try:
        deal = int(score.get("deal_score") or 0)
    except (TypeError, ValueError):
        deal = 0
    base.update({
        "deal_score": deal,
        "value_band": score.get("value_band") or "skip",
        "hunt_fit": bool(score.get("hunt_fit") is True),
        "scam_risk": score.get("scam_risk") or "medium",
        "reason": score.get("reason") or "",
        "has_score": True,
    })
    return base


def candidate_from_cached(row: dict, watch_obj: dict, fresh_item: dict | None = None) -> dict:
    price = row.get("price")
    currency = row.get("currency") or "RON"
    if fresh_item and isinstance(fresh_item.get("price"), dict):
        amount = fresh_item["price"].get("amount", price)
        currency = fresh_item["price"].get("currency_code") or currency
        title = fresh_item.get("title") or row.get("title")
        url = fresh_item.get("url") or row.get("url")
        brand = fresh_item.get("brand_title") or row.get("brand")
        size = fresh_item.get("size_title") or row.get("size")
        condition = fresh_item.get("status") or row.get("condition")
        fav = fresh_item.get("favourite_count", row.get("favourite_count"))
        user = fresh_item.get("user") or {}
        profile = fresh_item.get("_profile") or {}
    else:
        amount = price
        title = row.get("title")
        url = row.get("url")
        brand = row.get("brand")
        size = row.get("size")
        condition = row.get("condition")
        fav = row.get("favourite_count")
        user = {"id": row.get("seller_id"), "login": row.get("seller_login")}
        profile = {"country_code": row.get("seller_country")} if row.get("seller_country") else {}
    item = {
        "id": row.get("item_id") if not fresh_item else fresh_item.get("id", row.get("item_id")),
        "title": title,
        "price": {"amount": amount, "currency_code": currency},
        "brand_title": brand,
        "size_title": size,
        "status": condition,
        "favourite_count": fav or 0,
        "url": url,
        "user": {
            "id": user.get("id") if user.get("id") is not None else row.get("seller_id"),
            "login": user.get("login") or row.get("seller_login"),
        },
        "_profile": profile if isinstance(profile, dict) else {},
    }
    if row.get("seller_country") and not item["_profile"].get("country_code"):
        item["_profile"]["country_code"] = row["seller_country"]

    has_score = bool(row.get("has_score"))
    if has_score and int(row.get("score_version") or 0) == 2:
        score = {
            "id": item.get("id"),
            **{field: row.get(field) for field in V2_FIELDS},
            "score_factors": _json_object(row.get("score_factors")),
            "factor_evidence": _json_object(row.get("factor_evidence")),
            "hunt_fit": row.get("hunt_fit"),
            "reason": row.get("reason"),
        }
    elif has_score:
        score = {
            "id": item.get("id"),
            "deal_score": row.get("deal_score"),
            "value_band": row.get("value_band"),
            "hunt_fit": row.get("hunt_fit"),
            "scam_risk": row.get("scam_risk"),
            "reason": row.get("reason"),
        }
    else:
        # Unscored seed/backfill: treat as soft hunt-fit so haul prefilter can use it.
        score = {
            "id": item.get("id"),
            "deal_score": 6,
            "value_band": "acceptable",
            "hunt_fit": True if row.get("hunt_fit") is not False else False,
            "scam_risk": "medium",
            "reason": "cached listing (not LLM-scored)",
        }
    return {
        "item": item,
        "score": score,
        "watch": row.get("hunt_name"),
        "watch_obj": watch_obj,
    }


def export_row(row: dict) -> dict:
    scored_at = row.get("scored_at")
    if hasattr(scored_at, "isoformat"):
        scored_at = scored_at.isoformat()
    price = row.get("price")
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
    return {
        "id": row.get("item_id"),
        "watch": row.get("hunt_name"),
        "title": row.get("title"),
        "price": price,
        "currency": row.get("currency") or "RON",
        "brand": row.get("brand"),
        "size": row.get("size"),
        "condition": row.get("condition"),
        "url": row.get("url"),
        "favourite_count": row.get("favourite_count"),
        "seller_id": row.get("seller_id"),
        "seller": row.get("seller_login"),
        "seller_country": row.get("seller_country"),
        "deal_score": row.get("deal_score"),
        "value_band": row.get("value_band"),
        "hunt_fit": row.get("hunt_fit"),
        "scam_risk": row.get("scam_risk"),
        "score_version": row.get("score_version"),
        "buy_score": row.get("buy_score"),
        "buy_band": row.get("buy_band"),
        "score_confidence": row.get("score_confidence"),
        "score_interval_low": row.get("score_interval_low"),
        "score_interval_high": row.get("score_interval_high"),
        "score_factors": _json_object(row.get("score_factors")),
        "factor_evidence": _json_object(row.get("factor_evidence")),
        "verification_concern": row.get("verification_concern"),
        "verification_reason": row.get("verification_reason"),
        "rank_position": row.get("rank_position"),
        "rank_confidence": row.get("rank_confidence"),
        "reason": row.get("reason"),
        "has_score": bool(row.get("has_score")),
        "scored_at": scored_at,
        "index_source": row.get("source"),
        "source": "index",
    }


def _bundle_eligible(row: dict) -> bool:
    if int(row.get("score_version") or 0) == 2:
        return (
            row.get("hunt_fit") is True
            and row.get("buy_band") in {"bundle", "good", "keep", "exceptional"}
            and row.get("verification_concern") != "block"
        )
    return (
        row.get("hunt_fit") is not False
        and row.get("value_band") != "skip"
        and (not row.get("has_score") or int(row.get("deal_score") or 0) >= 6)
    )


def _bundle_is_keep(row: dict) -> bool:
    if int(row.get("score_version") or 0) == 2:
        return (
            int(row.get("buy_score") or 0) >= 85
            and float(row.get("score_confidence") or 0) >= 0.60
            and row.get("verification_concern") != "block"
        )
    return (
        int(row.get("deal_score") or 0) >= 9
        and row.get("value_band") in {"steal", "hunt"}
    )


def index_bundle_opportunities(
    export_rows: list[dict],
    *,
    min_items: int = 2,
    min_deal_score: int = 6,
    config: dict | None = None,
) -> list[dict]:
    """Group indexed hunt-fit rows by seller into dashboard near-bundle shapes."""
    import bundle_offer as bo

    by_seller: dict[tuple[str, str], list] = {}
    for row in export_rows:
        if not _bundle_eligible(row):
            continue
        is_v2 = int(row.get("score_version") or 0) == 2
        if not is_v2 and row.get("has_score"):
            try:
                if int(row.get("deal_score") or 0) < min_deal_score:
                    continue
            except (TypeError, ValueError):
                continue
        sid = row.get("seller_id")
        if sid is None:
            continue
        score_kind = "v2" if is_v2 else "legacy"
        by_seller.setdefault((str(sid), score_kind), []).append(row)

    offer_cfg = bo.bundle_offer_config(config)
    default_extra = float(offer_cfg.get("default_checkout_extra_ron", 25))
    out = []
    for (sid, score_kind), rows in by_seller.items():
        score_field = "buy_score" if score_kind == "v2" else "deal_score"
        best: dict[str, dict] = {}
        for r in rows:
            iid = str(r.get("id"))
            prev = best.get(iid)
            if prev is None or int(r.get(score_field) or 0) > int(prev.get(score_field) or 0):
                best[iid] = r
        members = list(best.values())
        if len(members) < min_items:
            continue
        members.sort(key=lambda r: int(r.get(score_field) or 0), reverse=True)
        listing_sum = 0.0
        for r in members:
            try:
                listing_sum += float(r.get("price") or 0)
            except (TypeError, ValueError):
                pass
        seller = next((r.get("seller") for r in members if r.get("seller")), None)
        country = next((r.get("seller_country") for r in members if r.get("seller_country")), None)
        keeps = [r for r in members if _bundle_is_keep(r)]
        kind = "index_keep_bundle" if keeps and len(members) > len(keeps) else "index_near_bundle"
        watch_name = next((r.get("watch") for r in members if r.get("watch")), None)
        extra = default_extra
        row = {
            "kind": kind,
            "kept_at": max((r.get("scored_at") or "") for r in members),
            "seller": seller,
            "seller_id": int(sid) if str(sid).isdigit() else sid,
            "country": country,
            "checkout_extra_ron": extra,
            "listing_sum": listing_sum,
            "checkout_total": listing_sum + extra,
            "value_band": "opportunity",
            "reason": "Indexed same-seller listings (score cache rediscovery)",
            "items": [
                {
                    "role": "keep" if _bundle_is_keep(r) else "extra",
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "price": r.get("price"),
                    "url": r.get("url"),
                    "watch": r.get("watch"),
                    "deal_score": r.get("deal_score"),
                    "score_version": r.get("score_version"),
                    "buy_score": r.get("buy_score"),
                    "buy_band": r.get("buy_band"),
                    "score_confidence": r.get("score_confidence"),
                    "score_interval_low": r.get("score_interval_low"),
                    "score_interval_high": r.get("score_interval_high"),
                    "rank_position": r.get("rank_position"),
                    "rank_confidence": r.get("rank_confidence"),
                    "seller_id": r.get("seller_id"),
                    "seller": r.get("seller") or seller,
                }
                for r in members
            ],
        }
        row.update(
            bo.offer_fields(
                listing_sum,
                extra,
                len(members),
                kind=kind,
                watch_name=watch_name,
                config=config,
            )
        )
        out.append(row)
    out.sort(key=lambda b: b.get("kept_at") or "", reverse=True)
    return out


class ScoredStore(Protocol):
    def upsert_score(self, row: dict) -> None: ...
    def upsert_many(self, rows: list[dict]) -> None: ...
    def replace_rankings(self, rows: list[dict]) -> None: ...
    def load_by_seller(self, seller_id: int) -> list[dict]: ...
    def load_recent(self, limit: int = 10000) -> list[dict]: ...
    def load_legacy_scored(self, limit: int = 100000) -> list[dict]: ...
    def existing_keys(self) -> set[str]: ...
    def count(self) -> int: ...
    def close(self) -> None: ...


class NullScoredStore:
    def upsert_score(self, row: dict) -> None:
        return None

    def upsert_many(self, rows: list[dict]) -> None:
        return None

    def replace_rankings(self, rows: list[dict]) -> None:
        return None

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return []

    def load_recent(self, limit: int = 10000) -> list[dict]:
        return []

    def load_legacy_scored(self, limit: int = 100000) -> list[dict]:
        return []

    def existing_keys(self) -> set[str]:
        return set()

    def count(self) -> int:
        return 0

    def close(self) -> None:
        return None


class MemoryScoredStore:
    def __init__(self) -> None:
        self._rows: dict[tuple, dict] = {}

    def upsert_score(self, row: dict) -> None:
        key = (row["item_id"], row["hunt_name"])
        prev = self._rows.get(key)
        if not prev:
            self._rows[key] = dict(row)
            return
        merged = dict(prev)
        for field in (
            "title", "price", "currency", "brand", "size", "condition", "url",
            "favourite_count", "seller_id", "seller_login", "seller_country", "source",
        ):
            val = row.get(field)
            if val is not None and val != "":
                merged[field] = val
        if row.get("has_score"):
            for field in (
                "deal_score", "value_band", "hunt_fit", "scam_risk", "reason", "scored_at",
                *V2_FIELDS,
            ):
                merged[field] = row.get(field)
            merged["has_score"] = True
        elif row.get("hunt_fit") is not None:
            merged["hunt_fit"] = row["hunt_fit"]
        self._rows[key] = merged

    def upsert_many(self, rows: list[dict]) -> None:
        for row in rows:
            self.upsert_score(row)

    def replace_rankings(self, rows: list[dict]) -> None:
        for stored in self._rows.values():
            if stored.get("score_version") == 2:
                stored["rank_position"] = None
                stored["rank_confidence"] = None
        for ranking in rows:
            stored = self._rows.get(
                (ranking.get("item_id"), ranking.get("hunt_name"))
            )
            if not stored or stored.get("score_version") != 2:
                continue
            stored["rank_position"] = ranking.get("rank_position")
            stored["rank_confidence"] = ranking.get("rank_confidence")

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return [dict(r) for r in self._rows.values() if r.get("seller_id") == seller_id]

    def load_recent(self, limit: int = 10000) -> list[dict]:
        rows = sorted(
            self._rows.values(),
            key=lambda r: r.get("scored_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [dict(r) for r in rows[:limit]]

    def load_legacy_scored(self, limit: int = 100000) -> list[dict]:
        rows = sorted(
            (row for row in self._rows.values() if is_legacy_scored_row(row)),
            key=lambda r: r.get("scored_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [dict(r) for r in rows[: max(0, int(limit))]]

    def existing_keys(self) -> set[str]:
        return {f"{r['item_id']}:{r['hunt_name']}" for r in self._rows.values()}

    def count(self) -> int:
        return len(self._rows)

    def close(self) -> None:
        return None


class PsycopgScoredStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert_score(self, row: dict) -> None:
        self.upsert_many([row])

    def upsert_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        # Tiny commits + retries: Cockroach serializable aborts under concurrent dashboard reads.
        batch = 10
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            for attempt in range(6):
                try:
                    with self._conn.cursor() as cur:
                        for row in chunk:
                            cur.execute(UPSERT_SQL, _sql_row(row))
                    self._conn.commit()
                    break
                except Exception as e:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    if attempt == 5:
                        raise
                    time.sleep(0.25 * (2 ** attempt))
                    print(f"scored_store upsert retry {attempt + 1}: {e}", file=sys.stderr)

    def replace_rankings(self, rows: list[dict]) -> None:
        for attempt in range(6):
            try:
                with self._conn.cursor() as cur:
                    cur.execute(CLEAR_V2_RANKINGS_SQL)
                    for ranking in rows:
                        cur.execute(
                            UPDATE_V2_RANKING_SQL,
                            (
                                ranking.get("rank_position"),
                                ranking.get("rank_confidence"),
                                ranking.get("item_id"),
                                ranking.get("hunt_name"),
                            ),
                        )
                self._conn.commit()
                return
            except Exception as e:
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                if attempt == 5:
                    raise
                time.sleep(0.25 * (2 ** attempt))
                print(
                    f"scored_store rank replace retry {attempt + 1}: {e}",
                    file=sys.stderr,
                )

    def load_by_seller(self, seller_id: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_BY_SELLER_SQL, (seller_id,))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def load_recent(self, limit: int = 10000) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_RECENT_SQL, (int(limit),))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def load_legacy_scored(self, limit: int = 100000) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_LEGACY_SCORED_SQL, (max(0, int(limit)),))
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def existing_keys(self) -> set[str]:
        with self._conn.cursor() as cur:
            cur.execute(EXISTING_KEYS_SQL)
            return {r[0] for r in cur.fetchall()}

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(COUNT_SQL)
            return int(cur.fetchone()[0])

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
        for stmt in ALTERS:
            try:
                cur.execute(stmt)
            except Exception as e:
                # Cockroach may error on some ALTER forms; continue.
                print(f"scored_store schema note: {e}", file=sys.stderr)
    conn.commit()


def open_store() -> ScoredStore:
    url = database_url()
    if not url:
        print(
            "scored_store: DATABASE_URL unset — scores will NOT land in Cockroach "
            "(desk Index stays stale; only Keeps in git JSON appear).",
            file=sys.stderr,
        )
        return NullScoredStore()
    try:
        import psycopg

        conn = psycopg.connect(url, connect_timeout=10)
        ensure_schema(conn)
        return PsycopgScoredStore(conn)
    except Exception as e:
        print(f"scored_store: DB unavailable, using null store: {e}", file=sys.stderr)
        return NullScoredStore()

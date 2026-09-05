"""Cockroach / Postgres cache for every seen Vinted listing (+ optional LLM score)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

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
]

# Listing fields always refresh; score fields only when incoming has_score.
UPSERT_SQL = """
INSERT INTO scored_listings (
  item_id, hunt_name, title, price, currency, brand, size, condition, url,
  favourite_count, seller_id, seller_login, seller_country,
  deal_score, value_band, hunt_fit, scam_risk, reason, has_score, scored_at, source
) VALUES (
  %(item_id)s, %(hunt_name)s, %(title)s, %(price)s, %(currency)s, %(brand)s,
  %(size)s, %(condition)s, %(url)s, %(favourite_count)s, %(seller_id)s,
  %(seller_login)s, %(seller_country)s, %(deal_score)s, %(value_band)s,
  %(hunt_fit)s, %(scam_risk)s, %(reason)s, %(has_score)s, %(scored_at)s, %(source)s
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
       deal_score, value_band, hunt_fit, scam_risk, reason, has_score, scored_at, source
FROM scored_listings
WHERE seller_id = %s
"""

LOAD_RECENT_SQL = """
SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
       favourite_count, seller_id, seller_login, seller_country,
       deal_score, value_band, hunt_fit, scam_risk, reason, has_score, scored_at, source
FROM scored_listings
ORDER BY scored_at DESC
LIMIT %s
"""

EXISTING_KEYS_SQL = """
SELECT item_id::text || ':' || hunt_name AS seen_key FROM scored_listings
"""

COUNT_SQL = "SELECT COUNT(*) FROM scored_listings"


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
    if has_score:
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
        "reason": row.get("reason"),
        "has_score": bool(row.get("has_score")),
        "scored_at": scored_at,
        "index_source": row.get("source"),
        "source": "index",
    }


def index_bundle_opportunities(
    export_rows: list[dict],
    *,
    min_items: int = 2,
    min_deal_score: int = 6,
) -> list[dict]:
    """Group indexed hunt-fit rows by seller into dashboard near-bundle shapes."""
    by_seller: dict[str, list] = {}
    for row in export_rows:
        if row.get("hunt_fit") is False:
            continue
        band = row.get("value_band")
        if band == "skip":
            continue
        # Unscored seeds count toward same-seller rediscovery.
        if row.get("has_score"):
            try:
                if int(row.get("deal_score") or 0) < min_deal_score:
                    continue
            except (TypeError, ValueError):
                continue
        elif row.get("hunt_fit") is not True and not row.get("has_score"):
            # listing-only without explicit hunt_fit — still allow if seed source
            if "seed" not in str(row.get("index_source") or ""):
                continue
        sid = row.get("seller_id")
        if sid is None:
            continue
        by_seller.setdefault(str(sid), []).append(row)

    out = []
    for sid, rows in by_seller.items():
        best: dict[str, dict] = {}
        for r in rows:
            iid = str(r.get("id"))
            prev = best.get(iid)
            if prev is None or int(r.get("deal_score") or 0) > int(prev.get("deal_score") or 0):
                best[iid] = r
        members = list(best.values())
        if len(members) < min_items:
            continue
        members.sort(key=lambda r: int(r.get("deal_score") or 0), reverse=True)
        listing_sum = 0.0
        for r in members:
            try:
                listing_sum += float(r.get("price") or 0)
            except (TypeError, ValueError):
                pass
        seller = next((r.get("seller") for r in members if r.get("seller")), None)
        country = next((r.get("seller_country") for r in members if r.get("seller_country")), None)
        keeps = [
            r for r in members
            if int(r.get("deal_score") or 0) >= 9 and (r.get("value_band") in ("steal", "hunt"))
        ]
        kind = "index_keep_bundle" if keeps and len(members) > len(keeps) else "index_near_bundle"
        out.append({
            "kind": kind,
            "kept_at": max((r.get("scored_at") or "") for r in members),
            "seller": seller,
            "seller_id": int(sid) if str(sid).isdigit() else sid,
            "country": country,
            "listing_sum": listing_sum,
            "value_band": "opportunity",
            "reason": "Indexed same-seller listings (score cache rediscovery)",
            "items": [
                {
                    "role": "keep" if int(r.get("deal_score") or 0) >= 9
                    and r.get("value_band") in ("steal", "hunt") else "extra",
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "price": r.get("price"),
                    "url": r.get("url"),
                    "watch": r.get("watch"),
                    "deal_score": r.get("deal_score"),
                    "seller_id": r.get("seller_id"),
                    "seller": r.get("seller") or seller,
                }
                for r in members
            ],
        })
    out.sort(key=lambda b: b.get("kept_at") or "", reverse=True)
    return out


class ScoredStore(Protocol):
    def upsert_score(self, row: dict) -> None: ...
    def upsert_many(self, rows: list[dict]) -> None: ...
    def load_by_seller(self, seller_id: int) -> list[dict]: ...
    def load_recent(self, limit: int = 10000) -> list[dict]: ...
    def existing_keys(self) -> set[str]: ...
    def count(self) -> int: ...
    def close(self) -> None: ...


class NullScoredStore:
    def upsert_score(self, row: dict) -> None:
        return None

    def upsert_many(self, rows: list[dict]) -> None:
        return None

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return []

    def load_recent(self, limit: int = 10000) -> list[dict]:
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
            for field in ("deal_score", "value_band", "hunt_fit", "scam_risk", "reason", "scored_at"):
                merged[field] = row.get(field)
            merged["has_score"] = True
        elif row.get("hunt_fit") is not None:
            merged["hunt_fit"] = row["hunt_fit"]
        self._rows[key] = merged

    def upsert_many(self, rows: list[dict]) -> None:
        for row in rows:
            self.upsert_score(row)

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return [dict(r) for r in self._rows.values() if r.get("seller_id") == seller_id]

    def load_recent(self, limit: int = 10000) -> list[dict]:
        rows = sorted(
            self._rows.values(),
            key=lambda r: r.get("scored_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return [dict(r) for r in rows[:limit]]

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
        with self._conn.cursor() as cur:
            for row in rows:
                cur.execute(UPSERT_SQL, row)
        self._conn.commit()

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
        return NullScoredStore()
    try:
        import psycopg

        conn = psycopg.connect(url, connect_timeout=10)
        ensure_schema(conn)
        return PsycopgScoredStore(conn)
    except Exception as e:
        print(f"scored_store: DB unavailable, using null store: {e}", file=sys.stderr)
        return NullScoredStore()

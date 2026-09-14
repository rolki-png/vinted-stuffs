# Scored Listings Cockroach Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every LLM-scored listing in CockroachDB and reuse those scores (with a live availability check) when the same seller becomes interesting again, so bundles can form without rescoring.

**Architecture:** Hybrid storage — thin `seen_keys` stay in git `data/seen_listings.json`; rich rows live in Cockroach `scored_listings`. A small `scripts/scored_store.py` module owns connect/upsert/load; `vinted_bot.py` upserts after each score and revives prior seller rows before `merge_scored` / `assemble_bundles`. Missing or failed DB never aborts a hunt run.

**Tech Stack:** Python 3.12, `psycopg` (Postgres wire → CockroachDB Basic), unittest, existing Vinted CLI availability batch, GitHub Actions secrets.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-05-scored-listings-cockroach-design.md`
- Reuse scores as-is; never LLM-rescore revived rows in v1
- Store every LLM-scored listing (including skips / non-fits)
- Unscored bundle-hunt seeds stay JSON-only (no Cockroach row)
- Do not move `best_deals` / `bundle_pool` / alert fingerprints into Cockroach
- No dashboard UI for the cache in v1
- Never commit `DATABASE_URL` or passwords; use `.env` (gitignored) locally and GitHub Actions secrets in CI
- Prefer env `DATABASE_URL`; accept alias `COCKROACH_DATABASE_URL`
- Hunt run must continue if DB is unset/down

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/sql/001_scored_listings.sql` | Table + index DDL |
| `scripts/scored_store.py` | URL resolution, ensure schema, upsert, load-by-seller, row↔candidate rebuild, Null/Memory stores |
| `scripts/test_scored_store.py` | Unit tests (memory store + rebuild + assemble path) |
| `scripts/vinted_bot.py` | Wire write after score; revive before merge/assemble |
| `scripts/requirements.txt` | Add `psycopg[binary]` |
| `.env.example` | Document `DATABASE_URL=` placeholder |
| `.github/workflows/vinted-bot.yml` | Pass `DATABASE_URL` secret into bot step |
| `CONTEXT.md` | Short term for scored listings cache (optional clarity) |

---

### Task 1: Schema + scored_store (TDD)

**Files:**
- Create: `scripts/sql/001_scored_listings.sql`
- Create: `scripts/scored_store.py`
- Create: `scripts/test_scored_store.py`
- Modify: `scripts/requirements.txt`

**Interfaces:**
- Produces:
  - `database_url() -> str | None`
  - `open_store() -> ScoredStore` (Null if no URL / connect fail)
  - `ScoredStore.upsert_score(row: dict) -> None`
  - `ScoredStore.upsert_many(rows: list[dict]) -> None`
  - `ScoredStore.load_by_seller(seller_id: int) -> list[dict]`
  - `row_from_item_score(item, score, hunt_name, source, scored_at=None) -> dict`
  - `candidate_from_cached(row, watch_obj, fresh_item=None) -> dict` with keys `item`, `score`, `watch`, `watch_obj`
  - `MemoryScoredStore` for tests
- Consumes: none yet from bot

- [ ] **Step 1: Add dependency**

Append to `scripts/requirements.txt`:

```
psycopg[binary]>=3.2
```

- [ ] **Step 2: Write failing tests**

Create `scripts/test_scored_store.py`:

```python
import unittest
from datetime import datetime, timezone

import scored_store as ss


class MemoryStoreTests(unittest.TestCase):
    def test_upsert_and_load_by_seller(self):
        store = ss.MemoryScoredStore()
        row = ss.row_from_item_score(
            item={
                "id": 111,
                "title": "Craft tee",
                "price": {"amount": "40", "currency_code": "GBP"},
                "brand_title": "Craft",
                "size_title": "M",
                "status": "Very good",
                "url": "https://www.vinted.co.uk/items/111",
                "favourite_count": 2,
                "user": {"id": 99, "login": "seller"},
                "_profile": {"country_code": "uk"},
            },
            score={
                "id": 111,
                "deal_score": 7,
                "value_band": "acceptable",
                "hunt_fit": True,
                "scam_risk": "low",
                "reason": "ok extra",
            },
            hunt_name="Craft ADV M-L",
            source="search",
            scored_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        store.upsert_score(row)
        loaded = store.load_by_seller(99)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["item_id"], 111)
        self.assertEqual(loaded[0]["deal_score"], 7)
        self.assertEqual(loaded[0]["seller_id"], 99)

    def test_upsert_overwrites_same_pk(self):
        store = ss.MemoryScoredStore()
        base = ss.row_from_item_score(
            item={
                "id": 1,
                "title": "a",
                "price": {"amount": "10", "currency_code": "GBP"},
                "user": {"id": 5, "login": "x"},
                "_profile": {},
            },
            score={
                "deal_score": 5,
                "value_band": "skip",
                "hunt_fit": False,
                "scam_risk": "medium",
                "reason": "old",
            },
            hunt_name="H",
            source="search",
        )
        store.upsert_score(base)
        base2 = dict(base)
        base2["deal_score"] = 8
        base2["reason"] = "new"
        store.upsert_score(base2)
        loaded = store.load_by_seller(5)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["deal_score"], 8)
        self.assertEqual(loaded[0]["reason"], "new")

    def test_candidate_from_cached_rebuilds_bot_row(self):
        row = {
            "item_id": 42,
            "hunt_name": "Craft ADV M-L",
            "title": "Craft ADV",
            "price": 55.0,
            "currency": "GBP",
            "brand": "Craft",
            "size": "L",
            "condition": "New without tags",
            "url": "https://www.vinted.co.uk/items/42",
            "favourite_count": 1,
            "seller_id": 7,
            "seller_login": "bob",
            "seller_country": "ro",
            "deal_score": 7,
            "value_band": "acceptable",
            "hunt_fit": True,
            "scam_risk": "low",
            "reason": "bundle extra",
            "source": "closet_crawl",
        }
        watch = {"name": "Craft ADV M-L", "country": "uk", "target_type": "men's"}
        cand = ss.candidate_from_cached(row, watch)
        self.assertEqual(cand["watch"], "Craft ADV M-L")
        self.assertIs(cand["watch_obj"], watch)
        self.assertEqual(cand["item"]["id"], 42)
        self.assertEqual(cand["item"]["user"]["id"], 7)
        self.assertEqual(cand["score"]["deal_score"], 7)
        self.assertTrue(cand["score"]["hunt_fit"])

    def test_cached_extra_plus_new_keep_assembles_bundle(self):
        import vinted_bot as bot

        config = {
            "min_deal_score": 9,
            "require_hunt_fit": True,
            "keep_value_bands": ["steal", "hunt"],
            "solo_floor_clothing_ron": 0,
            "bundle_extra_min_score": 7,
            "checkout_extra_ron": {"ro": 25, "default": 25},
        }
        watch = {"name": "Craft ADV M-L", "target_type": "men's gym", "country": "uk"}
        store = ss.MemoryScoredStore()
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 2,
                    "title": "extra",
                    "price": {"amount": "80", "currency_code": "GBP"},
                    "user": {"id": 99, "login": "seller"},
                    "_profile": {"country_code": "uk"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "extra",
                },
                hunt_name=watch["name"],
                source="search",
            )
        )
        cached = store.load_by_seller(99)
        prior = [ss.candidate_from_cached(r, watch) for r in cached]
        keep = {
            "item": {
                "id": 1,
                "title": "keep",
                "price": {"amount": "150", "currency_code": "GBP"},
                "url": "https://www.vinted.co.uk/items/1",
                "user": {"id": 99, "login": "seller"},
                "_profile": {"country_code": "uk"},
            },
            "score": {
                "deal_score": 9,
                "value_band": "steal",
                "hunt_fit": True,
                "scam_risk": "low",
                "reason": "keep",
            },
            "watch": watch["name"],
            "watch_obj": watch,
        }
        bundles, solos = bot.assemble_bundles(bot.merge_scored([keep], prior), config)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(len(solos), 0)
        self.assertEqual(bundles[0]["extras"][0]["item"]["id"], 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests — expect fail (module missing)**

```bash
cd /home/rolki/projects/vinted-stuffs && uv run --with-requirements scripts/requirements.txt python -m unittest scripts.test_scored_store -v
```

If `uv run` path is awkward, from `scripts/`:

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && python -m unittest test_scored_store -v
```

Expected: `ModuleNotFoundError: No module named 'scored_store'` (or import error).

- [ ] **Step 4: Add SQL migration**

Create `scripts/sql/001_scored_listings.sql`:

```sql
CREATE TABLE IF NOT EXISTS scored_listings (
  item_id BIGINT NOT NULL,
  hunt_name TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  price DECIMAL NULL,
  currency TEXT NOT NULL DEFAULT 'GBP',
  brand TEXT NULL,
  size TEXT NULL,
  condition TEXT NULL,
  url TEXT NULL,
  favourite_count INT NULL,
  seller_id BIGINT NULL,
  seller_login TEXT NULL,
  seller_country TEXT NULL,
  deal_score INT NOT NULL DEFAULT 0,
  value_band TEXT NOT NULL DEFAULT 'skip',
  hunt_fit BOOL NOT NULL DEFAULT false,
  scam_risk TEXT NOT NULL DEFAULT 'medium',
  reason TEXT NOT NULL DEFAULT '',
  scored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'search',
  PRIMARY KEY (item_id, hunt_name)
);

CREATE INDEX IF NOT EXISTS scored_listings_seller_id_idx
  ON scored_listings (seller_id);
```

- [ ] **Step 5: Implement `scripts/scored_store.py`**

```python
"""Cockroach / Postgres score cache for LLM-scored Vinted listings."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Protocol

DDL = """
CREATE TABLE IF NOT EXISTS scored_listings (
  item_id BIGINT NOT NULL,
  hunt_name TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  price DECIMAL NULL,
  currency TEXT NOT NULL DEFAULT 'GBP',
  brand TEXT NULL,
  size TEXT NULL,
  condition TEXT NULL,
  url TEXT NULL,
  favourite_count INT NULL,
  seller_id BIGINT NULL,
  seller_login TEXT NULL,
  seller_country TEXT NULL,
  deal_score INT NOT NULL DEFAULT 0,
  value_band TEXT NOT NULL DEFAULT 'skip',
  hunt_fit BOOL NOT NULL DEFAULT false,
  scam_risk TEXT NOT NULL DEFAULT 'medium',
  reason TEXT NOT NULL DEFAULT '',
  scored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'search',
  PRIMARY KEY (item_id, hunt_name)
);
CREATE INDEX IF NOT EXISTS scored_listings_seller_id_idx
  ON scored_listings (seller_id);
"""

UPSERT_SQL = """
INSERT INTO scored_listings (
  item_id, hunt_name, title, price, currency, brand, size, condition, url,
  favourite_count, seller_id, seller_login, seller_country,
  deal_score, value_band, hunt_fit, scam_risk, reason, scored_at, source
) VALUES (
  %(item_id)s, %(hunt_name)s, %(title)s, %(price)s, %(currency)s, %(brand)s,
  %(size)s, %(condition)s, %(url)s, %(favourite_count)s, %(seller_id)s,
  %(seller_login)s, %(seller_country)s, %(deal_score)s, %(value_band)s,
  %(hunt_fit)s, %(scam_risk)s, %(reason)s, %(scored_at)s, %(source)s
)
ON CONFLICT (item_id, hunt_name) DO UPDATE SET
  title = EXCLUDED.title,
  price = EXCLUDED.price,
  currency = EXCLUDED.currency,
  brand = EXCLUDED.brand,
  size = EXCLUDED.size,
  condition = EXCLUDED.condition,
  url = EXCLUDED.url,
  favourite_count = EXCLUDED.favourite_count,
  seller_id = EXCLUDED.seller_id,
  seller_login = EXCLUDED.seller_login,
  seller_country = EXCLUDED.seller_country,
  deal_score = EXCLUDED.deal_score,
  value_band = EXCLUDED.value_band,
  hunt_fit = EXCLUDED.hunt_fit,
  scam_risk = EXCLUDED.scam_risk,
  reason = EXCLUDED.reason,
  scored_at = EXCLUDED.scored_at,
  source = EXCLUDED.source
"""

LOAD_BY_SELLER_SQL = """
SELECT item_id, hunt_name, title, price, currency, brand, size, condition, url,
       favourite_count, seller_id, seller_login, seller_country,
       deal_score, value_band, hunt_fit, scam_risk, reason, scored_at, source
FROM scored_listings
WHERE seller_id = %s
"""


def database_url() -> str | None:
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


def row_from_item_score(
    item: dict,
    score: dict,
    hunt_name: str,
    source: str,
    scored_at: datetime | None = None,
) -> dict:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    profile = item.get("_profile") if isinstance(item.get("_profile"), dict) else {}
    sid = user.get("id")
    try:
        sid_i = int(sid) if sid is not None else None
        if sid_i is not None and sid_i <= 0:
            sid_i = None
    except (TypeError, ValueError):
        sid_i = None
    try:
        iid = int(item.get("id"))
    except (TypeError, ValueError):
        iid = item.get("id")
    login = (user.get("login") or user.get("username") or "") or None
    if login:
        login = str(login).strip() or None
    fav = item.get("favourite_count")
    try:
        fav_i = int(fav) if fav is not None else None
    except (TypeError, ValueError):
        fav_i = None
    try:
        deal = int(score.get("deal_score") or 0)
    except (TypeError, ValueError):
        deal = 0
    return {
        "item_id": iid,
        "hunt_name": hunt_name,
        "title": item.get("title") or "",
        "price": _price_amount(item),
        "currency": (item.get("price") or {}).get("currency_code") or "GBP",
        "brand": item.get("brand_title"),
        "size": item.get("size_title"),
        "condition": item.get("status"),
        "url": item.get("url"),
        "favourite_count": fav_i,
        "seller_id": sid_i,
        "seller_login": login,
        "seller_country": (profile.get("country_code") or None),
        "deal_score": deal,
        "value_band": score.get("value_band") or "skip",
        "hunt_fit": bool(score.get("hunt_fit") is True),
        "scam_risk": score.get("scam_risk") or "medium",
        "reason": score.get("reason") or "",
        "scored_at": scored_at or datetime.now(timezone.utc),
        "source": source,
    }


def candidate_from_cached(row: dict, watch_obj: dict, fresh_item: dict | None = None) -> dict:
    price = row.get("price")
    currency = row.get("currency") or "GBP"
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
    return {
        "item": item,
        "score": {
            "id": item.get("id"),
            "deal_score": row.get("deal_score"),
            "value_band": row.get("value_band"),
            "hunt_fit": row.get("hunt_fit"),
            "scam_risk": row.get("scam_risk"),
            "reason": row.get("reason"),
        },
        "watch": row.get("hunt_name"),
        "watch_obj": watch_obj,
    }


class ScoredStore(Protocol):
    def upsert_score(self, row: dict) -> None: ...
    def upsert_many(self, rows: list[dict]) -> None: ...
    def load_by_seller(self, seller_id: int) -> list[dict]: ...
    def close(self) -> None: ...


class NullScoredStore:
    def upsert_score(self, row: dict) -> None:
        return None

    def upsert_many(self, rows: list[dict]) -> None:
        return None

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return []

    def close(self) -> None:
        return None


class MemoryScoredStore:
    def __init__(self) -> None:
        self._rows: dict[tuple, dict] = {}

    def upsert_score(self, row: dict) -> None:
        key = (row["item_id"], row["hunt_name"])
        self._rows[key] = dict(row)

    def upsert_many(self, rows: list[dict]) -> None:
        for row in rows:
            self.upsert_score(row)

    def load_by_seller(self, seller_id: int) -> list[dict]:
        return [dict(r) for r in self._rows.values() if r.get("seller_id") == seller_id]

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

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def open_store() -> ScoredStore:
    url = database_url()
    if not url:
        return NullScoredStore()
    try:
        import psycopg

        conn = psycopg.connect(url, connect_timeout=10)
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
        return PsycopgScoredStore(conn)
    except Exception as e:
        print(f"scored_store: DB unavailable, using null store: {e}", file=sys.stderr)
        return NullScoredStore()
```

- [ ] **Step 6: Run unit tests — expect pass**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && python -m unittest test_scored_store -v
```

Expected: all four tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/sql/001_scored_listings.sql scripts/scored_store.py scripts/test_scored_store.py scripts/requirements.txt
git commit -m "$(cat <<'EOF'
Add Cockroach scored_listings store and unit tests.

EOF
)"
```

---

### Task 2: Wire upsert into `score_batch`

**Files:**
- Modify: `scripts/vinted_bot.py` (`main` / nested `score_batch`)
- Modify: `scripts/test_scored_store.py` (optional smoke already covered)

**Interfaces:**
- Consumes: `scored_store.open_store`, `row_from_item_score`, `store.upsert_score`
- Produces: every LLM (or test-mode) score written to store when available

- [ ] **Step 1: Open store once in `main`**

Near the top of `main()` after config/state load:

```python
import scored_store as scored_store_mod

score_db = scored_store_mod.open_store()
```

Before process exit (end of `main`, after `save_state`), close:

```python
    try:
        score_db.close()
    except Exception:
        pass
```

- [ ] **Step 2: Upsert inside `score_batch` after a score is attached**

In the loop where `score` is found and `scored.append(...)` happens, also:

```python
                try:
                    score_db.upsert_score(
                        scored_store_mod.row_from_item_score(
                            item, score, watch["name"], source="search",
                        )
                    )
                except Exception as e:
                    print(
                        f"scored_store upsert failed for {item.get('id')}: {e}",
                        file=sys.stderr,
                    )
```

For closet-crawl calls to `score_batch`, pass source — change signature to:

```python
    def score_batch(watch: dict, items: list, source: str = "search") -> None:
```

and use `source=source` in `row_from_item_score`. Closet call site:

```python
                score_batch(watch, batch, source="closet_crawl")
```

Keep `mark_seen` **before** or regardless of upsert success (already before score attach — leave as-is so missing scores still mark seen).

- [ ] **Step 3: Re-run unit tests**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && python -m unittest test_scored_store test_bundle_pool test_keep_rules -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/vinted_bot.py
git commit -m "$(cat <<'EOF'
Upsert every LLM score into Cockroach after scoring.

EOF
)"
```

---

### Task 3: Revive cached seller listings before assemble

**Files:**
- Modify: `scripts/vinted_bot.py`
- Modify: `scripts/test_scored_store.py`

**Interfaces:**
- Consumes: `store.load_by_seller`, `candidate_from_cached`, `check_items_available`, `apply_fresh_items`, `seller_id`, watch map
- Produces: `revive_scored_for_sellers(...)` helper returning list of candidate rows

- [ ] **Step 1: Add helper in `vinted_bot.py` (or keep thin wrapper calling scored_store)**

```python
def revive_scored_for_sellers(
    store,
    seller_ids: list,
    watches: list,
    exclude_ids: set,
    scored_store_mod,
) -> list:
    """Load cached scores for sellers, keep still-listed, skip exclude_ids / unknown hunts."""
    by_name = {w["name"]: w for w in watches}
    revived = []
    specs = []
    pending = []  # (candidate without fresh yet)
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
            spec = {"id": int(row["item_id"]), "country": _country(watch)}
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
    for cand in pending:
        iid = str(cand["item"].get("id"))
        if iid not in live:
            continue
        apply_fresh_items([cand], fresh)
        revived.append(cand)
    return revived
```

- [ ] **Step 2: Call revive before `merge_scored`**

After closet / value-haul scoring and prior_rows availability work, collect interesting seller ids from `scored` + keep-worthy prior, then:

```python
    interesting_sids = []
    seen_sids = set()
    for row in scored + still_prior:
        sid = seller_id(row["item"])
        if sid is None or sid in seen_sids:
            continue
        # Prefer sellers that look useful this run
        if row in scored and row["score"].get("hunt_fit") is not True:
            continue
        seen_sids.add(sid)
        interesting_sids.append(sid)

    revived = revive_scored_for_sellers(
        score_db,
        interesting_sids,
        watches,
        exclude_ids=this_run_ids | {str(r["item"].get("id")) for r in still_prior},
        scored_store_mod=scored_store_mod,
    )
    if revived:
        print(f"Revived {len(revived)} cached scored listing(s) from Cockroach.", file=sys.stderr)
    merged = merge_scored(scored, still_prior + revived)
```

(Replace the existing `merged = merge_scored(scored, still_prior)` line.)

- [ ] **Step 3: Add unit test for revive helper filtering**

Append to `scripts/test_scored_store.py`:

```python
    def test_revive_skips_unknown_hunt_and_excluded_ids(self):
        import vinted_bot as bot

        store = ss.MemoryScoredStore()
        watch = {"name": "Craft ADV M-L", "country": "uk"}
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 10,
                    "title": "a",
                    "price": {"amount": "1", "currency_code": "GBP"},
                    "url": "https://www.vinted.co.uk/items/10",
                    "user": {"id": 1, "login": "s"},
                    "_profile": {"country_code": "uk"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "x",
                },
                hunt_name="Craft ADV M-L",
                source="search",
            )
        )
        store.upsert_score(
            ss.row_from_item_score(
                item={
                    "id": 11,
                    "title": "b",
                    "price": {"amount": "1", "currency_code": "GBP"},
                    "url": "https://www.vinted.co.uk/items/11",
                    "user": {"id": 1, "login": "s"},
                    "_profile": {"country_code": "uk"},
                },
                score={
                    "deal_score": 7,
                    "value_band": "acceptable",
                    "hunt_fit": True,
                    "scam_risk": "low",
                    "reason": "y",
                },
                hunt_name="Deleted Hunt",
                source="search",
            )
        )

        def fake_available(specs):
            return {str(s["id"]) for s in specs}, {}

        with unittest.mock.patch.object(bot, "check_items_available", side_effect=fake_available):
            revived = bot.revive_scored_for_sellers(
                store, [1], [watch], exclude_ids={"10"}, scored_store_mod=ss,
            )
        self.assertEqual(revived, [])
```

Add `import unittest.mock` or use `from unittest.mock import patch` at top of test file.

- [ ] **Step 4: Run tests**

```bash
cd /home/rolki/projects/vinted-stuffs/scripts && python -m unittest test_scored_store test_bundle_pool -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/vinted_bot.py scripts/test_scored_store.py
git commit -m "$(cat <<'EOF'
Revive still-listed Cockroach scores when a seller is interesting.

EOF
)"
```

---

### Task 4: Env docs + Actions secret wiring + CONTEXT

**Files:**
- Modify: `.env.example`
- Modify: `.github/workflows/vinted-bot.yml`
- Modify: `CONTEXT.md`

**Interfaces:**
- Produces: documented `DATABASE_URL`; CI injects secret

- [ ] **Step 1: Extend `.env.example`**

Add:

```
# CockroachDB Basic (score cache). Prefer DATABASE_URL; COCKROACH_DATABASE_URL also works.
# Never commit the real URL. Local: copy to .env (gitignored). CI: GitHub Actions secret DATABASE_URL.
DATABASE_URL=
# COCKROACH_DATABASE_URL=
```

- [ ] **Step 2: Pass secret in workflow**

In `.github/workflows/vinted-bot.yml` under the Run bot `env:` block, add:

```yaml
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

- [ ] **Step 3: Domain note in `CONTEXT.md`**

After **Seen key** entry, add:

```markdown
**Scored listings cache**:
CockroachDB table of every LLM-scored listing (title, price, seller, full score). Thin seen keys stay in git for dedup; the cache lets the bot reuse scores when the same seller lists something new, after an availability check.
_Avoid_: Dumping all scores into seen_listings.json
```

- [ ] **Step 4: CA cert (local once) + Actions download**

Local (already done on the author’s machine if following Cockroach Cloud UI):

```bash
curl --create-dirs -o "$HOME/.postgresql/root.crt" \
  'https://cockroachlabs.cloud/clusters/70432b9f-d784-4414-a25a-25c752c4b17c/cert'
```

`sslmode=verify-full` uses `~/.postgresql/root.crt` by default — no URL change needed.

In `.github/workflows/vinted-bot.yml`, **before** the Run bot step, add:

```yaml
      - name: Download Cockroach CA cert
        run: |
          curl --create-dirs -o "$HOME/.postgresql/root.crt" \
            'https://cockroachlabs.cloud/clusters/70432b9f-d784-4414-a25a-25c752c4b17c/cert'
```

In GitHub repo settings → Secrets, create `DATABASE_URL` with the Cockroach connection string (same value as local `.env`). Do **not** put it in the commit.

- [ ] **Step 5: Optional live smoke (local, not CI)**

With `.env` loaded:

```bash
cd /home/rolki/projects/vinted-stuffs && set -a && source .env && set +a && \
python - <<'PY'
import scored_store as ss
from datetime import datetime, timezone
s = ss.open_store()
assert type(s).__name__ == "PsycopgScoredStore", type(s)
s.upsert_score(ss.row_from_item_score(
    {"id": 1, "title": "smoke", "price": {"amount": "1", "currency_code": "GBP"},
     "user": {"id": 1, "login": "smoke"}, "_profile": {"country_code": "uk"}},
    {"deal_score": 1, "value_band": "skip", "hunt_fit": False, "scam_risk": "low", "reason": "smoke"},
    "smoke-hunt", "search", datetime.now(timezone.utc),
))
print("rows", s.load_by_seller(1))
s.close()
print("ok")
PY
```

Expected: prints `ok` and at least one row. Delete the smoke row from the SQL console afterward if desired.

- [ ] **Step 6: Commit** (no `.env`)

```bash
git add .env.example .github/workflows/vinted-bot.yml CONTEXT.md
git commit -m "$(cat <<'EOF'
Wire DATABASE_URL and Cockroach CA download for score cache.

EOF
)"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Hybrid git keys + Cockroach rich rows | 1–3 |
| Table schema + seller index + upsert PK | 1 |
| Write every LLM score; not unscored seeds | 2 |
| Revive by seller + availability + no LLM | 3 |
| Graceful null/fail DB | 1 (`open_store`), 2–3 try/except |
| `DATABASE_URL` / alias + Actions | 4 |
| Unit tests w/ memory store; behavioral bundle | 1, 3 |
| No dashboard / no backfill / no moving pool | (non-goals — no tasks) |

## Placeholder / consistency review

- Function names aligned: `row_from_item_score`, `candidate_from_cached`, `open_store`, `revive_scored_for_sellers`
- `source` values: `search` | `closet_crawl` only
- No real credentials in this plan file

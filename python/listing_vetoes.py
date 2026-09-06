"""Listing vetoes (Remove / Park / Bought) — Cockroach map + pure desk apply helpers."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Any, Protocol

STATUS_REMOVED = "removed"
STATUS_PARKED = "parked"
STATUS_BOUGHT = "bought"
# Legacy wire/DB value; always normalized to removed.
STATUS_HIDDEN_LEGACY = "hidden"
VALID_STATUSES = frozenset({STATUS_REMOVED, STATUS_PARKED, STATUS_BOUGHT})
VALID_MODES = frozenset({"active", "parked", "bought", "all"})

ENRICHMENT_FIELDS = (
    "hunt_name",
    "hunt_family",
    "brand",
    "size",
    "price_ron",
    "value_band",
    "deal_score",
    "title",
)

DDL = """
CREATE TABLE IF NOT EXISTS listing_vetoes (
  item_id BIGINT NOT NULL PRIMARY KEY,
  status TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hunt_name TEXT NULL,
  hunt_family TEXT NULL,
  brand TEXT NULL,
  size TEXT NULL,
  price_ron DOUBLE PRECISION NULL,
  value_band TEXT NULL,
  deal_score INT NULL,
  title TEXT NULL
);
"""

MIGRATE_HIDDEN_SQL = (
    "UPDATE listing_vetoes SET status = 'removed' WHERE status = 'hidden'"
)

ALTER_COLUMNS_SQL = [
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS hunt_name TEXT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS hunt_family TEXT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS brand TEXT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS size TEXT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS price_ron DOUBLE PRECISION NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS value_band TEXT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS deal_score INT NULL",
    "ALTER TABLE listing_vetoes ADD COLUMN IF NOT EXISTS title TEXT NULL",
]

UPSERT_SQL = """
INSERT INTO listing_vetoes (
  item_id, status, updated_at,
  hunt_name, hunt_family, brand, size, price_ron, value_band, deal_score, title
)
VALUES (
  %(item_id)s, %(status)s, %(updated_at)s,
  %(hunt_name)s, %(hunt_family)s, %(brand)s, %(size)s, %(price_ron)s,
  %(value_band)s, %(deal_score)s, %(title)s
)
ON CONFLICT (item_id) DO UPDATE SET
  status = EXCLUDED.status,
  updated_at = EXCLUDED.updated_at,
  hunt_name = COALESCE(EXCLUDED.hunt_name, listing_vetoes.hunt_name),
  hunt_family = COALESCE(EXCLUDED.hunt_family, listing_vetoes.hunt_family),
  brand = COALESCE(EXCLUDED.brand, listing_vetoes.brand),
  size = COALESCE(EXCLUDED.size, listing_vetoes.size),
  price_ron = COALESCE(EXCLUDED.price_ron, listing_vetoes.price_ron),
  value_band = COALESCE(EXCLUDED.value_band, listing_vetoes.value_band),
  deal_score = COALESCE(EXCLUDED.deal_score, listing_vetoes.deal_score),
  title = COALESCE(EXCLUDED.title, listing_vetoes.title)
"""

DELETE_SQL = "DELETE FROM listing_vetoes WHERE item_id = %s"
LOAD_SQL = """
SELECT item_id, status, hunt_name, hunt_family, brand, size,
       price_ron, value_band, deal_score, title, updated_at
FROM listing_vetoes
"""
LOAD_SUPPRESS_SQL = (
    "SELECT item_id FROM listing_vetoes "
    "WHERE status IN ('removed', 'bought', 'hidden')"
)
LOAD_REMOVED_SQL = (
    "SELECT item_id FROM listing_vetoes WHERE status IN ('removed', 'hidden')"
)


def normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    st = str(status)
    if st == STATUS_HIDDEN_LEGACY:
        return STATUS_REMOVED
    return st


def coerce_write_status(status: str) -> str:
    st = normalize_status(status)
    if st not in VALID_STATUSES:
        raise ValueError(f"invalid veto status: {status}")
    return st


def _item_id(row_or_id) -> int | None:
    if isinstance(row_or_id, dict):
        raw = row_or_id.get("id", row_or_id.get("item_id"))
    else:
        raw = row_or_id
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _status_for(vetoes: dict, item_id) -> str | None:
    iid = _item_id(item_id)
    if iid is None:
        return None
    raw = vetoes.get(iid) or vetoes.get(str(iid))
    if isinstance(raw, dict):
        return normalize_status(raw.get("status"))
    return normalize_status(raw)


def is_removed(vetoes: dict, item_id) -> bool:
    return _status_for(vetoes, item_id) == STATUS_REMOVED


def is_parked(vetoes: dict, item_id) -> bool:
    return _status_for(vetoes, item_id) == STATUS_PARKED


def is_bought(vetoes: dict, item_id) -> bool:
    return _status_for(vetoes, item_id) == STATUS_BOUGHT


# Back-compat alias for older call sites / mental model.
is_hidden = is_removed


def _sort_desk(rows: list) -> list:
    def rank(r: dict) -> int:
        st = r.get("veto_status")
        if st == STATUS_PARKED:
            return 1
        if st == STATUS_BOUGHT:
            return 2
        return 0

    return sorted(rows, key=rank)


def apply_to_finds(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Filter/tag/sort finds by veto map.

    mode:
      active — omit removed and bought; tag parked; parked after active
      parked — only parked rows
      bought — only bought rows
      all    — active + parked + bought (removed always omitted)
    """
    if mode not in VALID_MODES:
        raise ValueError(f"unknown veto mode: {mode}")

    out = []
    for row in rows:
        st = _status_for(vetoes, row)
        if st == STATUS_REMOVED:
            continue
        if mode == "parked" and st != STATUS_PARKED:
            continue
        if mode == "bought" and st != STATUS_BOUGHT:
            continue
        if mode == "active" and st == STATUS_BOUGHT:
            continue
        tagged = dict(row)
        if st:
            tagged["veto_status"] = st
        else:
            tagged.pop("veto_status", None)
        out.append(tagged)

    return _sort_desk(out)


def apply_to_bundles(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Strip removed/bought members; drop bundle if <2 items remain; tag/sort."""
    if mode not in VALID_MODES:
        raise ValueError(f"unknown veto mode: {mode}")

    out = []
    for bundle in rows:
        items = list(bundle.get("items") or [])
        kept_items = []
        for it in items:
            st = _status_for(vetoes, it)
            # Removed always stripped; bought stripped from active/parked
            # (already purchased). For bought/all modes keep bought members tagged.
            if st == STATUS_REMOVED:
                continue
            if st == STATUS_BOUGHT and mode in ("active", "parked"):
                continue
            if mode == "parked" and st not in (STATUS_PARKED, None):
                # keep only bundles that will have parked members after filter
                pass
            tagged = dict(it)
            if st:
                tagged["veto_status"] = st
            kept_items.append(tagged)

        if mode == "bought":
            kept_items = [
                it for it in kept_items if it.get("veto_status") == STATUS_BOUGHT
            ]
            # History is find-centric; drop empty / single-item after filter
            if len(kept_items) < 1:
                continue
        elif len(kept_items) < 2:
            continue

        if mode == "parked" and not any(
            it.get("veto_status") == STATUS_PARKED for it in kept_items
        ):
            continue

        row = dict(bundle)
        row["items"] = kept_items
        listing_sum = 0.0
        for it in kept_items:
            try:
                listing_sum += float(it.get("price") or 0)
            except (TypeError, ValueError):
                pass
        row["listing_sum"] = listing_sum
        extra = row.get("checkout_extra_ron")
        if extra is not None:
            try:
                row["checkout_total"] = listing_sum + float(extra)
            except (TypeError, ValueError):
                pass

        if any(it.get("veto_status") == STATUS_PARKED for it in kept_items):
            row["veto_status"] = STATUS_PARKED
        elif any(it.get("veto_status") == STATUS_BOUGHT for it in kept_items):
            row["veto_status"] = STATUS_BOUGHT
        else:
            row.pop("veto_status", None)
        out.append(row)

    return _sort_desk(out)


def item_is_removed(item_id, removed_ids: set) -> bool:
    """True when item_id is in a suppress set (removed and/or bought ids)."""
    if item_id is None:
        return False
    try:
        return int(item_id) in removed_ids
    except (TypeError, ValueError):
        return False


item_is_hidden = item_is_removed
item_is_suppressed = item_is_removed


def filter_scored_rows(rows: list, removed_ids: set) -> list:
    """Drop scored rows whose listing id is in the suppress set."""
    if not removed_ids:
        return list(rows)
    out = []
    for row in rows:
        item = row.get("item") if isinstance(row, dict) else None
        iid = (item or {}).get("id") if item else row.get("id")
        if item_is_removed(iid, removed_ids):
            continue
        out.append(row)
    return out


def filter_items(items: list, removed_ids: set) -> list:
    """Drop raw Vinted item dicts whose id is suppressed."""
    if not removed_ids:
        return list(items)
    return [it for it in items if not item_is_removed(it.get("id"), removed_ids)]


def coerce_enrichment(enrichment: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {k: None for k in ENRICHMENT_FIELDS}
    if not enrichment:
        return out
    for key in ENRICHMENT_FIELDS:
        if key not in enrichment or enrichment[key] is None:
            continue
        val = enrichment[key]
        if key == "price_ron":
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                out[key] = None
        elif key == "deal_score":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                out[key] = None
        else:
            s = str(val).strip()
            out[key] = s if s else None
    return out


class VetoStore(Protocol):
    def set_status(
        self, item_id: int, status: str, enrichment: dict | None = None
    ) -> None: ...
    def clear(self, item_id: int) -> None: ...
    def load_map(self) -> dict[int, str]: ...
    def load_removed_ids(self) -> set[int]: ...
    def load_suppress_ids(self) -> set[int]: ...
    def load_outcomes(self, family: str | None = None) -> list[dict]: ...
    def close(self) -> None: ...


class MemoryVetoStore:
    def __init__(self) -> None:
        self._rows: dict[int, dict] = {}

    def set_status(
        self, item_id: int, status: str, enrichment: dict | None = None
    ) -> None:
        iid = int(item_id)
        st = coerce_write_status(status)
        prev = self._rows.get(iid) or {}
        enr = coerce_enrichment(enrichment)
        merged = {
            "item_id": iid,
            "status": st,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for key in ENRICHMENT_FIELDS:
            merged[key] = enr[key] if enr[key] is not None else prev.get(key)
        self._rows[iid] = merged

    def clear(self, item_id: int) -> None:
        self._rows.pop(int(item_id), None)

    def load_map(self) -> dict[int, str]:
        return {
            iid: normalize_status(row["status"]) or row["status"]
            for iid, row in self._rows.items()
        }

    def load_removed_ids(self) -> set[int]:
        return {
            iid
            for iid, row in self._rows.items()
            if normalize_status(row["status"]) == STATUS_REMOVED
        }

    def load_suppress_ids(self) -> set[int]:
        return {
            iid
            for iid, row in self._rows.items()
            if normalize_status(row["status"]) in (STATUS_REMOVED, STATUS_BOUGHT)
        }

    def load_outcomes(self, family: str | None = None) -> list[dict]:
        out = []
        for row in self._rows.values():
            st = normalize_status(row.get("status"))
            if st not in (STATUS_REMOVED, STATUS_BOUGHT):
                continue
            if family is not None and (row.get("hunt_family") or "other") != family:
                continue
            out.append(dict(row))
        out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return out

    def load_hidden_ids(self) -> set[int]:
        return self.load_removed_ids()

    def close(self) -> None:
        return None


class NullVetoStore:
    def set_status(
        self, item_id: int, status: str, enrichment: dict | None = None
    ) -> None:
        return None

    def clear(self, item_id: int) -> None:
        return None

    def load_map(self) -> dict[int, str]:
        return {}

    def load_removed_ids(self) -> set[int]:
        return set()

    def load_suppress_ids(self) -> set[int]:
        return set()

    def load_outcomes(self, family: str | None = None) -> list[dict]:
        return []

    def load_hidden_ids(self) -> set[int]:
        return set()

    def close(self) -> None:
        return None


class PsycopgVetoStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    def set_status(
        self, item_id: int, status: str, enrichment: dict | None = None
    ) -> None:
        status = coerce_write_status(status)
        now = datetime.now(timezone.utc)
        enr = coerce_enrichment(enrichment)
        params = {
            "item_id": int(item_id),
            "status": status,
            "updated_at": now,
            **enr,
        }
        with self._conn.cursor() as cur:
            cur.execute(UPSERT_SQL, params)
        self._conn.commit()

    def clear(self, item_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(DELETE_SQL, (int(item_id),))
        self._conn.commit()

    def load_map(self) -> dict[int, str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT item_id, status FROM listing_vetoes")
            return {
                int(r[0]): normalize_status(str(r[1])) or str(r[1])
                for r in cur.fetchall()
            }

    def load_removed_ids(self) -> set[int]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_REMOVED_SQL)
            return {int(r[0]) for r in cur.fetchall()}

    def load_suppress_ids(self) -> set[int]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_SUPPRESS_SQL)
            return {int(r[0]) for r in cur.fetchall()}

    def load_outcomes(self, family: str | None = None) -> list[dict]:
        sql = LOAD_SQL + " WHERE status IN ('removed', 'bought')"
        params: tuple = ()
        if family is not None:
            sql += " AND COALESCE(hunt_family, 'other') = %s"
            params = (family,)
        sql += " ORDER BY updated_at DESC"
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [
                "item_id",
                "status",
                "hunt_name",
                "hunt_family",
                "brand",
                "size",
                "price_ron",
                "value_band",
                "deal_score",
                "title",
                "updated_at",
            ]
            out = []
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                d["status"] = normalize_status(str(d["status"])) or d["status"]
                d["item_id"] = int(d["item_id"])
                if d.get("updated_at") is not None:
                    d["updated_at"] = d["updated_at"].isoformat()
                out.append(d)
            return out

    def load_hidden_ids(self) -> set[int]:
        return self.load_removed_ids()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
        for stmt in ALTER_COLUMNS_SQL:
            try:
                cur.execute(stmt)
            except Exception as e:
                print(f"listing_vetoes alter note: {e}", file=sys.stderr)
        try:
            cur.execute(MIGRATE_HIDDEN_SQL)
        except Exception as e:
            print(f"listing_vetoes migrate note: {e}", file=sys.stderr)
    conn.commit()


def database_url() -> str | None:
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("COCKROACH_DATABASE_URL")
        or ""
    ).strip() or None


def open_store() -> VetoStore:
    url = database_url()
    if not url:
        return NullVetoStore()
    try:
        import psycopg

        conn = psycopg.connect(url, connect_timeout=10)
        ensure_schema(conn)
        return PsycopgVetoStore(conn)
    except Exception as e:
        print(f"listing_vetoes: DB unavailable, using null store: {e}", file=sys.stderr)
        return NullVetoStore()

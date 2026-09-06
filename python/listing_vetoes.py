"""Listing vetoes (Remove / Park) — Cockroach-backed map + pure desk apply helpers."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Protocol

STATUS_REMOVED = "removed"
STATUS_PARKED = "parked"
# Legacy wire/DB value; always normalized to removed.
STATUS_HIDDEN_LEGACY = "hidden"
VALID_STATUSES = frozenset({STATUS_REMOVED, STATUS_PARKED})

DDL = """
CREATE TABLE IF NOT EXISTS listing_vetoes (
  item_id BIGINT NOT NULL PRIMARY KEY,
  status TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

MIGRATE_HIDDEN_SQL = (
    "UPDATE listing_vetoes SET status = 'removed' WHERE status = 'hidden'"
)

UPSERT_SQL = """
INSERT INTO listing_vetoes (item_id, status, updated_at)
VALUES (%(item_id)s, %(status)s, %(updated_at)s)
ON CONFLICT (item_id) DO UPDATE SET
  status = EXCLUDED.status,
  updated_at = EXCLUDED.updated_at
"""

DELETE_SQL = "DELETE FROM listing_vetoes WHERE item_id = %s"
LOAD_SQL = "SELECT item_id, status FROM listing_vetoes"
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
    return normalize_status(vetoes.get(iid) or vetoes.get(str(iid)))


def is_removed(vetoes: dict, item_id) -> bool:
    return _status_for(vetoes, item_id) == STATUS_REMOVED


def is_parked(vetoes: dict, item_id) -> bool:
    return _status_for(vetoes, item_id) == STATUS_PARKED


# Back-compat alias for older call sites / mental model.
is_hidden = is_removed


def apply_to_finds(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Filter/tag/sort finds by veto map.

    mode:
      active — omit removed; tag parked; parked after active (default)
      parked — only parked rows
      all    — active + parked (removed always omitted)
    """
    if mode not in ("active", "parked", "all"):
        raise ValueError(f"unknown veto mode: {mode}")

    out = []
    for row in rows:
        st = _status_for(vetoes, row)
        if st == STATUS_REMOVED:
            continue
        if mode == "parked" and st != STATUS_PARKED:
            continue
        tagged = dict(row)
        if st:
            tagged["veto_status"] = st
        else:
            tagged.pop("veto_status", None)
        out.append(tagged)

    return sorted(out, key=lambda r: 1 if r.get("veto_status") == STATUS_PARKED else 0)


def apply_to_bundles(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Strip removed members; drop bundle if <2 items remain; tag/sort parked."""
    if mode not in ("active", "parked", "all"):
        raise ValueError(f"unknown veto mode: {mode}")

    out = []
    for bundle in rows:
        items = list(bundle.get("items") or [])
        kept_items = []
        for it in items:
            st = _status_for(vetoes, it)
            if st == STATUS_REMOVED:
                continue
            tagged = dict(it)
            if st:
                tagged["veto_status"] = st
            kept_items.append(tagged)

        if len(kept_items) < 2:
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
        else:
            row.pop("veto_status", None)
        out.append(row)

    return sorted(out, key=lambda r: 1 if r.get("veto_status") == STATUS_PARKED else 0)


def item_is_removed(item_id, removed_ids: set) -> bool:
    """True when item_id is in the bot suppress set (removed vetoes only)."""
    if item_id is None:
        return False
    try:
        return int(item_id) in removed_ids
    except (TypeError, ValueError):
        return False


item_is_hidden = item_is_removed


def filter_scored_rows(rows: list, removed_ids: set) -> list:
    """Drop scored rows whose listing id is removed."""
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
    """Drop raw Vinted item dicts whose id is removed."""
    if not removed_ids:
        return list(items)
    return [it for it in items if not item_is_removed(it.get("id"), removed_ids)]


class VetoStore(Protocol):
    def set_status(self, item_id: int, status: str) -> None: ...
    def clear(self, item_id: int) -> None: ...
    def load_map(self) -> dict[int, str]: ...
    def load_removed_ids(self) -> set[int]: ...
    def close(self) -> None: ...


class MemoryVetoStore:
    def __init__(self) -> None:
        self._map: dict[int, str] = {}

    def set_status(self, item_id: int, status: str) -> None:
        self._map[int(item_id)] = coerce_write_status(status)

    def clear(self, item_id: int) -> None:
        self._map.pop(int(item_id), None)

    def load_map(self) -> dict[int, str]:
        return {iid: normalize_status(st) or st for iid, st in self._map.items()}

    def load_removed_ids(self) -> set[int]:
        return {
            iid
            for iid, st in self._map.items()
            if normalize_status(st) == STATUS_REMOVED
        }

    def load_hidden_ids(self) -> set[int]:
        return self.load_removed_ids()

    def close(self) -> None:
        return None


class NullVetoStore:
    def set_status(self, item_id: int, status: str) -> None:
        return None

    def clear(self, item_id: int) -> None:
        return None

    def load_map(self) -> dict[int, str]:
        return {}

    def load_removed_ids(self) -> set[int]:
        return set()

    def load_hidden_ids(self) -> set[int]:
        return set()

    def close(self) -> None:
        return None


class PsycopgVetoStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    def set_status(self, item_id: int, status: str) -> None:
        status = coerce_write_status(status)
        now = datetime.now(timezone.utc)
        with self._conn.cursor() as cur:
            cur.execute(
                UPSERT_SQL,
                {"item_id": int(item_id), "status": status, "updated_at": now},
            )
        self._conn.commit()

    def clear(self, item_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(DELETE_SQL, (int(item_id),))
        self._conn.commit()

    def load_map(self) -> dict[int, str]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_SQL)
            return {
                int(r[0]): normalize_status(str(r[1])) or str(r[1])
                for r in cur.fetchall()
            }

    def load_removed_ids(self) -> set[int]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_REMOVED_SQL)
            return {int(r[0]) for r in cur.fetchall()}

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

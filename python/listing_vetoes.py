"""Listing vetoes (Hide / Park) — Cockroach-backed map + pure desk apply helpers."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Protocol

STATUS_HIDDEN = "hidden"
STATUS_PARKED = "parked"
VALID_STATUSES = frozenset({STATUS_HIDDEN, STATUS_PARKED})

DDL = """
CREATE TABLE IF NOT EXISTS listing_vetoes (
  item_id BIGINT NOT NULL PRIMARY KEY,
  status TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

UPSERT_SQL = """
INSERT INTO listing_vetoes (item_id, status, updated_at)
VALUES (%(item_id)s, %(status)s, %(updated_at)s)
ON CONFLICT (item_id) DO UPDATE SET
  status = EXCLUDED.status,
  updated_at = EXCLUDED.updated_at
"""

DELETE_SQL = "DELETE FROM listing_vetoes WHERE item_id = %s"
LOAD_SQL = "SELECT item_id, status FROM listing_vetoes"
LOAD_HIDDEN_SQL = "SELECT item_id FROM listing_vetoes WHERE status = 'hidden'"


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


def is_hidden(vetoes: dict, item_id) -> bool:
    iid = _item_id(item_id)
    if iid is None:
        return False
    return vetoes.get(iid) == STATUS_HIDDEN or vetoes.get(str(iid)) == STATUS_HIDDEN


def is_parked(vetoes: dict, item_id) -> bool:
    iid = _item_id(item_id)
    if iid is None:
        return False
    return vetoes.get(iid) == STATUS_PARKED or vetoes.get(str(iid)) == STATUS_PARKED


def _status_for(vetoes: dict, item_id) -> str | None:
    iid = _item_id(item_id)
    if iid is None:
        return None
    return vetoes.get(iid) or vetoes.get(str(iid))


def apply_to_finds(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Filter/tag/sort finds by veto map.

    mode:
      active  — omit hidden; tag parked; parked after active (default)
      parked  — only parked rows
      hidden  — only hidden rows
      all     — all rows with veto_status when set; parked after non-parked
    """
    out = []
    for row in rows:
        st = _status_for(vetoes, row)
        if mode == "active":
            if st == STATUS_HIDDEN:
                continue
        elif mode == "parked":
            if st != STATUS_PARKED:
                continue
        elif mode == "hidden":
            if st != STATUS_HIDDEN:
                continue
        elif mode == "all":
            pass
        else:
            raise ValueError(f"unknown veto mode: {mode}")
        tagged = dict(row)
        if st:
            tagged["veto_status"] = st
        else:
            tagged.pop("veto_status", None)
        out.append(tagged)

    def sort_key(r):
        st = r.get("veto_status")
        if st == STATUS_PARKED:
            return 1
        if st == STATUS_HIDDEN:
            return 2
        return 0

    # Stable: active, then parked, then hidden
    return sorted(out, key=sort_key)


def apply_to_bundles(rows: list, vetoes: dict, *, mode: str = "active") -> list:
    """Strip hidden members; drop bundle if <2 items remain; tag/sort parked."""
    if mode not in ("active", "parked", "hidden", "all"):
        raise ValueError(f"unknown veto mode: {mode}")

    out = []
    for bundle in rows:
        items = list(bundle.get("items") or [])
        kept_items = []
        for it in items:
            st = _status_for(vetoes, it)
            if mode == "active" and st == STATUS_HIDDEN:
                continue
            if mode == "parked" and st == STATUS_HIDDEN:
                continue
            if mode == "hidden" and st != STATUS_HIDDEN:
                continue
            tagged = dict(it)
            if st:
                tagged["veto_status"] = st
            kept_items.append(tagged)

        if mode == "hidden":
            if not kept_items:
                continue
        elif len(kept_items) < 2:
            continue
        elif mode == "parked" and not any(
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

        any_parked = any(it.get("veto_status") == STATUS_PARKED for it in kept_items)
        any_hidden = any(it.get("veto_status") == STATUS_HIDDEN for it in kept_items)
        if mode == "hidden" or (mode == "all" and any_hidden and not any_parked):
            row["veto_status"] = STATUS_HIDDEN
        elif any_parked:
            row["veto_status"] = STATUS_PARKED
        else:
            row.pop("veto_status", None)
        out.append(row)

    def sort_key(r):
        st = r.get("veto_status")
        if st == STATUS_PARKED:
            return 1
        if st == STATUS_HIDDEN:
            return 2
        return 0

    return sorted(out, key=sort_key)


def item_is_hidden(item_id, hidden_ids: set) -> bool:
    """True when item_id is in the bot suppress set (hidden vetoes only)."""
    if item_id is None:
        return False
    try:
        return int(item_id) in hidden_ids
    except (TypeError, ValueError):
        return False


def filter_scored_rows(rows: list, hidden_ids: set) -> list:
    """Drop scored rows whose listing id is hidden."""
    if not hidden_ids:
        return list(rows)
    out = []
    for row in rows:
        item = row.get("item") if isinstance(row, dict) else None
        iid = (item or {}).get("id") if item else row.get("id")
        if item_is_hidden(iid, hidden_ids):
            continue
        out.append(row)
    return out


def filter_items(items: list, hidden_ids: set) -> list:
    """Drop raw Vinted item dicts whose id is hidden."""
    if not hidden_ids:
        return list(items)
    return [it for it in items if not item_is_hidden(it.get("id"), hidden_ids)]


class VetoStore(Protocol):
    def set_status(self, item_id: int, status: str) -> None: ...
    def clear(self, item_id: int) -> None: ...
    def load_map(self) -> dict[int, str]: ...
    def load_hidden_ids(self) -> set[int]: ...
    def close(self) -> None: ...


class MemoryVetoStore:
    def __init__(self) -> None:
        self._map: dict[int, str] = {}

    def set_status(self, item_id: int, status: str) -> None:
        status = str(status)
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid veto status: {status}")
        self._map[int(item_id)] = status

    def clear(self, item_id: int) -> None:
        self._map.pop(int(item_id), None)

    def load_map(self) -> dict[int, str]:
        return dict(self._map)

    def load_hidden_ids(self) -> set[int]:
        return {iid for iid, st in self._map.items() if st == STATUS_HIDDEN}

    def close(self) -> None:
        return None


class NullVetoStore:
    def set_status(self, item_id: int, status: str) -> None:
        return None

    def clear(self, item_id: int) -> None:
        return None

    def load_map(self) -> dict[int, str]:
        return {}

    def load_hidden_ids(self) -> set[int]:
        return set()

    def close(self) -> None:
        return None


class PsycopgVetoStore:
    def __init__(self, conn) -> None:
        self._conn = conn

    def set_status(self, item_id: int, status: str) -> None:
        status = str(status)
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid veto status: {status}")
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
            return {int(r[0]): str(r[1]) for r in cur.fetchall()}

    def load_hidden_ids(self) -> set[int]:
        with self._conn.cursor() as cur:
            cur.execute(LOAD_HIDDEN_SQL)
            return {int(r[0]) for r in cur.fetchall()}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(DDL)
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

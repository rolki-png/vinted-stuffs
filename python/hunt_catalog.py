"""Brand-id hunts match Vinted catalog by brand, not title keywords."""

from __future__ import annotations

import json
from pathlib import Path


def branded_hunts(watches: list) -> list:
    return [
        w
        for w in watches or []
        if isinstance(w, dict) and w.get("brand_ids") and str(w.get("query") or "").strip()
    ]


def catalog_search_text(watch: dict) -> str:
    """Vinted search_text. Empty when brand_ids already select the catalog."""
    if watch.get("brand_ids"):
        return ""
    return str(watch.get("query") or "")


def watches_by_name(watches: list) -> dict:
    return {w["name"]: w for w in watches or [] if isinstance(w, dict) and w.get("name")}


BRAND_QUERY_STOPWORDS = frozenset({
    "leggings",
    "maternity",
    "dress",
    "shorts",
    "gym",
    "running",
    "technical",
    "polo",
    "size",
    "training",
})


def catalog_brand_needles(query: str) -> list[str]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    tokens = [t for t in q.replace("/", " ").replace("-", " ").split() if t]
    needles = []
    for token in tokens:
        if token in BRAND_QUERY_STOPWORDS or token.isdigit():
            continue
        if len(token) < 4 and not any(ch.isdigit() or ch == "&" for ch in token):
            continue
        if token not in needles:
            needles.append(token)
    if q not in needles and " " not in q:
        needles.insert(0, q)
    return needles


def brand_text_matches_query(brand: str, query: str) -> bool:
    brand_l = str(brand or "").strip().lower()
    if not brand_l:
        return False
    needles = catalog_brand_needles(query)
    return any(n in brand_l for n in needles)


def item_matches_hunt_catalog(item: dict, watch: dict, *, missing_brand_ok: bool = False) -> bool:
    """Brand-id hunts keep only that brand; keyword hunts keep everything returned."""
    ids = watch.get("brand_ids") or []
    if not ids:
        return True
    wanted = set()
    for raw in ids:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    bid = item.get("brand_id")
    if bid is not None:
        try:
            if int(bid) in wanted:
                return True
        except (TypeError, ValueError):
            pass
    brand = str(item.get("brand_title") or item.get("brand") or "").strip()
    if not brand:
        return missing_brand_ok
    return brand_text_matches_query(brand, watch.get("query") or "")


def scored_row_matches_hunt_catalog(row: dict, watch: dict, *, missing_brand_ok: bool = False) -> bool:
    return item_matches_hunt_catalog(
        {
            "brand_id": row.get("brand_id"),
            "brand_title": row.get("brand") or row.get("brand_title"),
        },
        watch,
        missing_brand_ok=missing_brand_ok,
    )


def row_watch_name(row: dict) -> str:
    return str(row.get("watch") or row.get("hunt_name") or "")


def filter_scored_export_rows(rows: list, watches: list) -> list:
    by_name = watches_by_name(watches)
    out = []
    for row in rows or []:
        watch = by_name.get(row_watch_name(row))
        if not watch or scored_row_matches_hunt_catalog(row, watch):
            out.append(row)
    return out


def filter_pool_rows(rows: list, watches: list) -> list:
    by_name = watches_by_name(watches)
    out = []
    for row in rows or []:
        watch = by_name.get(row.get("watch"))
        item = row.get("item") if isinstance(row.get("item"), dict) else row
        if not watch or item_matches_hunt_catalog(item, watch, missing_brand_ok=False):
            out.append(row)
    return out


def branded_hunt_names(watches: list) -> set[str]:
    return {w["name"] for w in branded_hunts(watches)}


def filter_seen_keys(keys: list, watches: list, keep_pairs: set[str]) -> list:
    """Drop per-hunt seen keys for brand hunts that are not a kept catalog pair."""
    names = branded_hunt_names(watches)
    if not names:
        return list(keys or [])
    out = []
    for key in keys or []:
        text = str(key)
        if ":" not in text:
            out.append(key)
            continue
        item_id, hunt = text.split(":", 1)
        if hunt not in names:
            out.append(key)
            continue
        if f"{item_id}:{hunt}" in keep_pairs:
            out.append(key)
    return out


def keep_pairs_from_rows(rows: list) -> set[str]:
    pairs = set()
    for row in rows or []:
        iid = row.get("id") if row.get("id") is not None else row.get("item_id")
        hunt = row_watch_name(row)
        if iid is None or not hunt:
            continue
        pairs.add(f"{iid}:{hunt}")
    return pairs


def ilike_contains(query: str) -> str:
    return f"%{str(query).strip()}%"


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def rewrite_desk_json(root: Path, watches: list) -> dict:
    """Drop off-catalog brand-hunt junk from git JSON the desk still reads."""
    indexed_path = root / "data" / "indexed_scores.json"
    pool_path = root / "data" / "bundle_pool.json"
    deals_path = root / "data" / "best_deals.json"
    bundles_path = root / "data" / "best_bundles.json"
    state_path = root / "data" / "seen_listings.json"
    last_path = root / "data" / "last_run.json"

    indexed = _read_json(indexed_path, [])
    kept_indexed = filter_scored_export_rows(indexed, watches)
    pool = _read_json(pool_path, [])
    kept_pool = filter_pool_rows(pool, watches)
    deals = _read_json(deals_path, [])
    kept_deals = filter_scored_export_rows(deals, watches)
    last_run = _read_json(last_path, {})
    last_top = last_run.get("top") if isinstance(last_run, dict) else None
    kept_top = filter_scored_export_rows(last_top or [], watches)

    keep_pairs = keep_pairs_from_rows(kept_indexed)
    keep_pairs |= keep_pairs_from_rows(
        [{"id": (r.get("item") or {}).get("id"), "watch": r.get("watch")} for r in kept_pool]
    )
    keep_pairs |= keep_pairs_from_rows(kept_deals)

    stats = {
        "indexed": len(indexed) - len(kept_indexed) if isinstance(indexed, list) else 0,
        "pool": len(pool) - len(kept_pool) if isinstance(pool, list) else 0,
        "deals": len(deals) - len(kept_deals) if isinstance(deals, list) else 0,
        "seen_keys": 0,
        "last_run_top": 0,
    }

    if isinstance(indexed, list) and stats["indexed"]:
        _write_json(indexed_path, kept_indexed)
    if isinstance(pool, list) and stats["pool"]:
        _write_json(pool_path, kept_pool)
    if isinstance(deals, list) and stats["deals"]:
        _write_json(deals_path, kept_deals)

    if isinstance(last_run, dict) and isinstance(last_top, list):
        stats["last_run_top"] = len(last_top) - len(kept_top)
        if stats["last_run_top"]:
            last_run["top"] = kept_top
            _write_json(last_path, last_run)

    if bundles_path.exists():
        bundles = _read_json(bundles_path, [])
        if isinstance(bundles, list):
            kept_bundles = []
            for bundle in bundles:
                watch = watches_by_name(watches).get(bundle.get("watch") or "")
                if not watch or not watch.get("brand_ids"):
                    kept_bundles.append(bundle)
                    continue
                keeps = filter_scored_export_rows(bundle.get("keeps") or [], [watch])
                extras = filter_scored_export_rows(bundle.get("extras") or [], [watch])
                if keeps or extras:
                    next_row = dict(bundle)
                    next_row["keeps"] = keeps
                    next_row["extras"] = extras
                    kept_bundles.append(next_row)
            dropped_b = len(bundles) - len(kept_bundles)
            stats["bundles"] = dropped_b
            if dropped_b:
                _write_json(bundles_path, kept_bundles)

    state = _read_json(state_path, {})
    if isinstance(state, dict):
        keys = state.get("seen_keys") or []
        next_keys = filter_seen_keys(keys, watches, keep_pairs)
        stats["seen_keys"] = len(keys) - len(next_keys)
        if stats["seen_keys"]:
            state["seen_keys"] = next_keys
            _write_json(state_path, state)
    return stats

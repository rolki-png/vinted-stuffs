#!/usr/bin/env python3
"""
Backfill Cockroach scored_listings: refetch seen_keys from Vinted, LLM-score, upsert.

Usage (from repo root, with .env containing DATABASE_URL + AI_GATEWAY_API_KEY or GEMINI_API_KEY):

  uv run --project python python python/backfill_scored_listings.py --limit 100

  # Rescore a bounded rotating batch of active-hunt legacy dashboard rows:
  uv run --project python python python/backfill_scored_listings.py \\
    --legacy-active-v2 --limit 10000 --export

Env:
  DATABASE_URL, AI_GATEWAY_API_KEY (preferred) or GEMINI_API_KEY
  VINTED_BIN optional
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scored_store as ss  # noqa: E402
import vinted_bot as bot  # noqa: E402

LEGACY_PROGRESS_KEY = "legacy_active_v2"
PARTIAL_EXIT = 3


@dataclass
class AvailabilityResult:
    items: dict[str, dict]
    checked_pairs: set[tuple[str, str]]
    available_pairs: set[tuple[str, str]]


def _load_dotenv() -> None:
    for name in (".env", ".env.local"):
        path = REPO_ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val


def parse_seen_keys(state: dict) -> list[tuple[str, str]]:
    out = []
    for key in state.get("seen_keys") or []:
        key = str(key)
        if ":" not in key:
            continue
        item_id, hunt = key.split(":", 1)
        if item_id.isdigit() and hunt:
            out.append((item_id, hunt))
    return out


def already_scored_keys(store) -> set[str]:
    """Keys that already have an LLM score in CRDB."""
    scored = set()
    # Prefer scanning recent rows; for full set use existing_keys + has_score filter.
    try:
        with store._conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "SELECT item_id::text || ':' || hunt_name FROM scored_listings WHERE has_score = true"
            )
            scored = {r[0] for r in cur.fetchall()}
    except Exception:
        for row in store.load_recent(50000):
            if row.get("has_score"):
                scored.add(f"{row['item_id']}:{row['hunt_name']}")
    return scored


def legacy_active_pairs(store, watch_by_name: dict) -> list[tuple[str, str]]:
    """Return every scored, non-v2 row belonging to a currently configured hunt."""
    pairs = []
    for row in store.load_recent(50000):
        hunt = row.get("hunt_name")
        if hunt not in watch_by_name or not row.get("has_score"):
            continue
        try:
            version = int(row.get("score_version") or 0)
        except (TypeError, ValueError):
            version = 0
        if version == 2 or row.get("reason") == "unavailable during backfill":
            continue
        pairs.append((str(row["item_id"]), str(hunt)))
    return sorted(set(pairs))


def _state_pair(value) -> tuple[str, str] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    item_id, hunt = value
    if item_id is None or not hunt:
        return None
    return str(item_id), str(hunt)


def _unavailable_pairs(progress: dict) -> set[tuple[str, str]]:
    pairs = set()
    for value in progress.get("unavailable_pairs") or []:
        pair = _state_pair(value)
        if pair is not None:
            pairs.add(pair)
    return pairs


def _legacy_progress(state: dict) -> dict:
    raw = state.get(LEGACY_PROGRESS_KEY)
    raw = raw if isinstance(raw, dict) else {}
    cursor = _state_pair(raw.get("cursor"))
    unavailable = _unavailable_pairs(raw)
    return {
        "cursor": list(cursor) if cursor else None,
        "unavailable_pairs": [list(pair) for pair in sorted(unavailable)],
    }


def bounded_legacy_batch(
    pairs: list[tuple[str, str]],
    progress: dict,
    *,
    limit: int,
) -> list[tuple[str, str]]:
    """Select a stable rotating batch without letting unavailable rows consume it."""
    unavailable = _unavailable_pairs(progress)
    eligible = sorted(set(pairs) - unavailable)
    if not eligible or limit <= 0:
        return []
    cursor = _state_pair(progress.get("cursor"))
    start = bisect_right(eligible, cursor) if cursor else 0
    rotated = eligible[start:] + eligible[:start]
    return rotated[:limit]


def legacy_completion(
    pairs: list[tuple[str, str]],
    progress: dict,
) -> dict[str, int | str]:
    remaining_pairs = set(pairs)
    unavailable = _unavailable_pairs(progress) & remaining_pairs
    remaining = len(remaining_pairs - unavailable)
    return {
        "legacy": len(remaining_pairs),
        "unavailable": len(unavailable),
        "remaining": remaining,
        "status": "complete" if remaining == 0 else "partial",
        "exit_code": 0 if remaining == 0 else PARTIAL_EXIT,
    }


def fetch_items(
    pairs: list[tuple[str, str]],
    watch_by_name: dict,
) -> AvailabilityResult:
    """Fetch live payloads and distinguish checked-unavailable from fetch failures."""
    by_country: dict[str, list[tuple[tuple[str, str], dict]]] = defaultdict(list)
    for item_id, hunt in pairs:
        watch = watch_by_name.get(hunt) or {"country": "ro"}
        country = bot._country(watch)
        pair = (item_id, hunt)
        by_country[country].append(
            (pair, {"id": int(item_id), "country": country})
        )

    fresh: dict[str, dict] = {}
    checked_pairs: set[tuple[str, str]] = set()
    available_pairs: set[tuple[str, str]] = set()

    def record(data, entries) -> int:
        checked_pairs.update(pair for pair, _spec in entries)
        returned_live_ids = set()
        for row in (data or {}).get("items") or []:
            iid = row.get("id")
            if iid is None or not row.get("available"):
                continue
            item_id = str(iid)
            returned_live_ids.add(item_id)
            payload = row.get("item")
            if isinstance(payload, dict):
                fresh[item_id] = (
                    bot._normalize_item(payload)
                    if payload.get("seller") or payload.get("user")
                    else payload
                )
        for pair, spec in entries:
            if str(spec["id"]) in returned_live_ids:
                available_pairs.add(pair)
        return len(returned_live_ids)

    for country, entries in by_country.items():
        chunk_size = 15
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i:i + chunk_size]
            attempted = chunk
            try:
                data = bot._vinted_json(
                    ["batch"],
                    timeout=180,
                    stdin_payload={"items": [spec for _pair, spec in chunk]},
                )
            except Exception as e:
                print(f"fetch failed ({country} n={len(chunk)}): {e}", file=sys.stderr)
                time.sleep(5)
                # Retry once with half chunk
                attempted = chunk[: max(1, len(chunk) // 2)]
                try:
                    data = bot._vinted_json(
                        ["batch"],
                        timeout=180,
                        stdin_payload={
                            "items": [spec for _pair, spec in attempted]
                        },
                    )
                except Exception as e2:
                    print(f"fetch retry failed: {e2}", file=sys.stderr)
                    continue
            live_count = record(data, attempted)
            print(
                f"  fetched {country}: +{live_count} live "
                f"chunk {i // chunk_size + 1}",
                file=sys.stderr,
            )
            time.sleep(1.2)
    return AvailabilityResult(
        items=fresh,
        checked_pairs=checked_pairs,
        available_pairs=available_pairs,
    )


def unavailable_tombstone(item_id: str, hunt_name: str) -> dict:
    """Mark gone/unfetchable listings so they leave the pending queue."""
    return {
        "item_id": int(item_id),
        "hunt_name": hunt_name,
        "title": "",
        "price": None,
        "currency": "RON",
        "brand": None,
        "size": None,
        "condition": None,
        "url": None,
        "favourite_count": None,
        "seller_id": None,
        "seller_login": None,
        "seller_country": None,
        "deal_score": 0,
        "value_band": "skip",
        "hunt_fit": False,
        "scam_risk": "medium",
        "reason": "unavailable during backfill",
        "has_score": True,
        "scored_at": datetime.now(timezone.utc),
        "source": "backfill_gone",
    }


def run_legacy_active_v2(
    *,
    store,
    watch_by_name: dict,
    config: dict,
    state: dict,
    gateway: str,
    gemini_client,
    limit: int,
    dry_run: bool = False,
) -> dict[str, int | str]:
    """Availability-check and rescore one rotating bounded batch of legacy rows."""
    pairs = legacy_active_pairs(store, watch_by_name)
    progress = _legacy_progress(state)
    current_pairs = set(pairs)
    progress["unavailable_pairs"] = [
        list(pair)
        for pair in sorted(_unavailable_pairs(progress) & current_pairs)
    ]
    selected = bounded_legacy_batch(pairs, progress, limit=limit)

    checked: set[tuple[str, str]] = set()
    available: set[tuple[str, str]] = set()
    live: set[tuple[str, str]] = set()
    newly_unavailable: set[tuple[str, str]] = set()
    scored_n = 0

    if selected:
        print(
            f"Legacy v2 rollout: candidates={len(pairs)} selected={len(selected)} "
            f"limit={limit}",
            file=sys.stderr,
        )
        availability = fetch_items(selected, watch_by_name)
        selected_set = set(selected)
        checked = availability.checked_pairs & selected_set
        available = availability.available_pairs & checked
        live = {
            pair for pair in available if pair[0] in availability.items
        }
        newly_unavailable = checked - available

        if not dry_run:
            known_unavailable = _unavailable_pairs(progress)
            known_unavailable.update(newly_unavailable)
            progress["unavailable_pairs"] = [
                list(pair) for pair in sorted(known_unavailable)
            ]
            progress["cursor"] = list(selected[-1])

        by_hunt: dict[str, list[str]] = defaultdict(list)
        for item_id, hunt in selected:
            if (item_id, hunt) in live:
                by_hunt[hunt].append(item_id)

        for hunt_name, item_ids in by_hunt.items():
            watch = watch_by_name[hunt_name]
            items = [availability.items[item_id] for item_id in item_ids]
            if dry_run:
                print(
                    f"[dry-run] {hunt_name}: would rescore {len(items)} legacy rows",
                    file=sys.stderr,
                )
                continue
            bot.attach_seller_profiles(items, bot._country(watch))
            chunk_size = 10
            for offset in range(0, len(items), chunk_size):
                chunk = items[offset:offset + chunk_size]
                scores = bot.score_listings(
                    watch,
                    chunk,
                    gateway,
                    gemini_client,
                    config,
                )
                by_id = {
                    str(score["id"]): score
                    for score in scores
                    if score.get("id") is not None
                    and score.get("score_version") == 2
                }
                rows = [
                    ss.row_from_item_score(
                        item,
                        by_id[str(item["id"])],
                        hunt_name,
                        "backfill_v2",
                    )
                    for item in chunk
                    if str(item.get("id")) in by_id
                ]
                store.upsert_many(rows)
                scored_n += len(rows)
                print(
                    f"rescored {hunt_name}: chunk {offset // chunk_size + 1} "
                    f"→ {len(rows)}/{len(chunk)} v2 scores",
                    file=sys.stderr,
                )
                time.sleep(0.5)

    remaining_pairs = legacy_active_pairs(store, watch_by_name)
    completion_progress = progress if not dry_run else _legacy_progress(state)
    completion = legacy_completion(remaining_pairs, completion_progress)
    unknown = len(set(selected) - checked) + len(available - live)
    summary = {
        "candidates": len(pairs),
        "selected": len(selected),
        "checked": len(checked),
        "live": len(live),
        "newly_unavailable": len(newly_unavailable),
        "unknown": unknown,
        "rescored": scored_n,
        **completion,
    }
    if not dry_run:
        progress["last_run"] = dict(summary)
        state[LEGACY_PROGRESS_KEY] = progress
    print(
        "LEGACY_ACTIVE_V2_SUMMARY " + json.dumps(summary, sort_keys=True),
        file=sys.stderr,
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Max keys to process this run")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N pending keys")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only; no LLM / no upsert")
    parser.add_argument("--fetch-only", action="store_true", help="Upsert listing rows without LLM")
    parser.add_argument("--export", action="store_true", help="Rewrite data/indexed_scores.json at end")
    parser.add_argument(
        "--legacy-active-v2",
        action="store_true",
        help="Availability-check and rescore active-hunt legacy dashboard rows",
    )
    return parser


def export_store(store) -> None:
    recent = store.load_recent(10000)
    export = [ss.export_row(row) for row in recent]
    bot.save_indexed_scores(export)
    opportunities = ss.index_bundle_opportunities(export)
    print(
        f"exported indexed_scores={len(export)} index_opps={len(opportunities)}",
        file=sys.stderr,
    )


def main() -> None:
    _load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be greater than zero")
    if args.legacy_active_v2 and args.fetch_only:
        parser.error("--fetch-only cannot be combined with --legacy-active-v2")

    gateway = os.environ.get("AI_GATEWAY_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not args.dry_run and not args.fetch_only and not gateway and not gemini_key:
        print(
            "Need AI_GATEWAY_API_KEY or GEMINI_API_KEY in env/.env for LLM scoring.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = bot.load_config()
    watch_by_name = {w["name"]: w for w in config["watches"]}
    state = bot.load_state()

    store = ss.open_store()
    if type(store).__name__ == "NullScoredStore":
        print("DATABASE_URL missing or DB unreachable.", file=sys.stderr)
        sys.exit(1)

    gemini_client = None
    if gemini_key and bot.genai is not None:
        gemini_client = bot.genai.Client(api_key=gemini_key)

    if args.legacy_active_v2:
        summary = run_legacy_active_v2(
            store=store,
            watch_by_name=watch_by_name,
            config=config,
            state=state,
            gateway=gateway,
            gemini_client=gemini_client,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            bot.save_state(state)
        if args.export or summary["rescored"]:
            export_store(store)
        store.close()
        if summary["exit_code"]:
            sys.exit(summary["exit_code"])
        return

    pairs = parse_seen_keys(state)
    # Only hunts still in config (user may have removed watches).
    pairs = [(i, h) for i, h in pairs if h in watch_by_name]
    print(f"seen_keys for active hunts: {len(pairs)}", file=sys.stderr)

    scored_already = already_scored_keys(store)
    pending = [(i, h) for i, h in pairs if f"{i}:{h}" not in scored_already]
    print(
        f"already scored in CRDB: {len(scored_already)}; pending: {len(pending)}",
        file=sys.stderr,
    )
    pending = pending[args.offset: args.offset + args.limit]
    print(f"this run: {len(pending)} (offset={args.offset} limit={args.limit})", file=sys.stderr)
    if not pending:
        print("Nothing to do.", file=sys.stderr)
        store.close()
        return

    # Group by hunt for scoring prompts
    by_hunt: dict[str, list[str]] = defaultdict(list)
    for item_id, hunt in pending:
        by_hunt[hunt].append(item_id)

    print("Fetching item details…", file=sys.stderr)
    availability = fetch_items(pending, watch_by_name)
    fresh = availability.items
    print(f"Live payloads: {len(fresh)} / {len(pending)}", file=sys.stderr)

    gone = [
        unavailable_tombstone(item_id, hunt)
        for item_id, hunt in sorted(
            availability.checked_pairs - availability.available_pairs
        )
    ]
    if gone and not args.dry_run:
        store.upsert_many(gone)
        print(f"Marked {len(gone)} unavailable as skip tombstones.", file=sys.stderr)

    upserted = len(gone) if not args.dry_run else 0
    scored_n = 0
    for hunt_name, item_ids in by_hunt.items():
        watch = watch_by_name.get(hunt_name)
        if not watch:
            print(f"Skip unknown hunt '{hunt_name}' ({len(item_ids)} ids)", file=sys.stderr)
            continue
        items = [fresh[iid] for iid in item_ids if iid in fresh]
        if not items:
            continue

        if args.dry_run:
            print(f"[dry-run] {hunt_name}: would process {len(items)}", file=sys.stderr)
            continue

        if args.fetch_only:
            rows = [
                ss.row_from_item(it, hunt_name, "backfill", hunt_fit=True)
                for it in items
            ]
            store.upsert_many(rows)
            upserted += len(rows)
            print(f"fetch-only upsert {hunt_name}: {len(rows)}", file=sys.stderr)
            continue

        bot.attach_seller_profiles(items, bot._country(watch))
        chunk_size = 10
        for offset in range(0, len(items), chunk_size):
            chunk = items[offset:offset + chunk_size]
            scores = bot.score_listings(
                watch,
                chunk,
                gateway,
                gemini_client,
                config,
            )
            by_id = {str(s["id"]): s for s in scores if s.get("id") is not None}
            rows = []
            for item in chunk:
                score = by_id.get(str(item.get("id")))
                if not score:
                    # LLM miss — store listing without has_score so a later run can retry.
                    rows.append(ss.row_from_item(item, hunt_name, "backfill", hunt_fit=None))
                    continue
                rows.append(
                    ss.row_from_item_score(item, score, hunt_name, "backfill")
                )
                scored_n += 1
            store.upsert_many(rows)
            upserted += len(rows)
            print(
                f"scored {hunt_name}: chunk {offset // chunk_size + 1} "
                f"→ {len(by_id)}/{len(chunk)} scores",
                file=sys.stderr,
            )
            time.sleep(0.5)

    print(
        f"Done. upserted={upserted} newly_scored={scored_n} "
        f"gone={len(gone)} crdb_count={store.count()}",
        file=sys.stderr,
    )

    if args.export or scored_n or upserted:
        export_store(store)

    store.close()


if __name__ == "__main__":
    main()

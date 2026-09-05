#!/usr/bin/env python3
"""
Backfill Cockroach scored_listings: refetch seen_keys from Vinted, LLM-score, upsert.

Usage (from repo root, with .env containing DATABASE_URL + AI_GATEWAY_API_KEY or GEMINI_API_KEY):

  uv run --with-requirements scripts/requirements.txt \\
    python scripts/backfill_scored_listings.py --limit 100

  # Continue later (skips keys that already have_score in CRDB):
  python scripts/backfill_scored_listings.py --limit 500

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
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scored_store as ss  # noqa: E402
import vinted_bot as bot  # noqa: E402


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


def fetch_items(pairs: list[tuple[str, str]], watch_by_name: dict) -> dict[str, dict]:
    """Fetch live item payloads keyed by item_id string. Country from hunt config."""
    by_country: dict[str, list[dict]] = defaultdict(list)
    for item_id, hunt in pairs:
        watch = watch_by_name.get(hunt) or {"country": "ro"}
        country = bot._country(watch)
        by_country[country].append({"id": int(item_id), "country": country})

    fresh: dict[str, dict] = {}
    for country, specs in by_country.items():
        chunk_size = 15
        for i in range(0, len(specs), chunk_size):
            chunk = specs[i:i + chunk_size]
            try:
                data = bot._vinted_json(
                    ["batch"],
                    timeout=180,
                    stdin_payload={"items": chunk},
                )
            except Exception as e:
                print(f"fetch failed ({country} n={len(chunk)}): {e}", file=sys.stderr)
                time.sleep(5)
                # Retry once with half chunk
                half = chunk[: max(1, len(chunk) // 2)]
                try:
                    data = bot._vinted_json(
                        ["batch"],
                        timeout=180,
                        stdin_payload={"items": half},
                    )
                except Exception as e2:
                    print(f"fetch retry failed: {e2}", file=sys.stderr)
                    continue
            live = set()
            for row in (data or {}).get("items") or []:
                iid = row.get("id")
                if iid is None or not row.get("available"):
                    continue
                live.add(str(iid))
                payload = row.get("item")
                if isinstance(payload, dict):
                    item = (
                        bot._normalize_item(payload)
                        if payload.get("seller") or payload.get("user")
                        else payload
                    )
                    fresh[str(iid)] = item
            print(
                f"  fetched {country}: +{len(live)} live "
                f"chunk {i // chunk_size + 1}",
                file=sys.stderr,
            )
            time.sleep(1.2)
    return fresh


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


def main() -> None:
    _load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=100, help="Max keys to process this run")
    ap.add_argument("--offset", type=int, default=0, help="Skip first N pending keys")
    ap.add_argument("--dry-run", action="store_true", help="Fetch only; no LLM / no upsert")
    ap.add_argument("--fetch-only", action="store_true", help="Upsert listing rows without LLM")
    ap.add_argument("--export", action="store_true", help="Rewrite data/indexed_scores.json at end")
    args = ap.parse_args()

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
    pairs = parse_seen_keys(state)
    # Only hunts still in config (user may have removed watches).
    pairs = [(i, h) for i, h in pairs if h in watch_by_name]
    print(f"seen_keys for active hunts: {len(pairs)}", file=sys.stderr)

    store = ss.open_store()
    if type(store).__name__ == "NullScoredStore":
        print("DATABASE_URL missing or DB unreachable.", file=sys.stderr)
        sys.exit(1)

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
    fresh = fetch_items(pending, watch_by_name)
    print(f"Live payloads: {len(fresh)} / {len(pending)}", file=sys.stderr)

    gone = []
    for item_id, hunt in pending:
        if item_id not in fresh:
            gone.append(unavailable_tombstone(item_id, hunt))
    if gone and not args.dry_run:
        store.upsert_many(gone)
        print(f"Marked {len(gone)} unavailable as skip tombstones.", file=sys.stderr)

    gemini_client = None
    if gemini_key and bot.genai is not None:
        gemini_client = bot.genai.Client(api_key=gemini_key)

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
            scores = bot.score_listings(watch, chunk, gateway, gemini_client)
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
        recent = store.load_recent(10000)
        export = [ss.export_row(r) for r in recent]
        bot.save_indexed_scores(export)
        opps = ss.index_bundle_opportunities(export)
        print(f"exported indexed_scores={len(export)} index_opps={len(opps)}", file=sys.stderr)

    store.close()


if __name__ == "__main__":
    main()

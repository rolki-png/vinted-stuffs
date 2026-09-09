#!/usr/bin/env python3
"""Closet-crawl sellers who already have one haul-eligible listing.

Index hauls need ≥2 same-seller hunt-fit pieces at buy_score ≥ 60. After a
Mamalicious backfill we often have many singleton seeds — this script fetches
each seed seller's closet and scores new listings against matching hunts so a
second piece can form an index_near_bundle / index_keep_bundle.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import listing_vetoes as lv  # noqa: E402
import scored_store as ss  # noqa: E402
import vinted_bot as bot  # noqa: E402

DEFAULT_LIMIT = 36


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


def _eligible_haul_member(row: dict) -> bool:
    try:
        version = int(row.get("score_version") or 0)
        buy = int(row.get("buy_score"))
    except (TypeError, ValueError):
        return False
    return (
        version == 2
        and row.get("hunt_fit") is True
        and buy >= 60
        and row.get("verification_concern") != "block"
        and row.get("seller_id") is not None
    )


def select_haul_seeds(
    rows: list[dict],
    *,
    hunt_needle: str = "",
    min_score: int = 60,
) -> list[dict]:
    """Sellers with exactly one haul-eligible listing for the hunt needle."""
    text = str(hunt_needle or "").strip().casefold()
    by_seller: dict[str, list[dict]] = {}
    for row in rows or []:
        if not _eligible_haul_member(row):
            continue
        try:
            buy = int(row.get("buy_score"))
        except (TypeError, ValueError):
            continue
        if buy < min_score:
            continue
        hunt = str(row.get("hunt_name") or row.get("watch") or "")
        if text and text not in hunt.casefold():
            continue
        sid = str(row.get("seller_id"))
        by_seller.setdefault(sid, []).append(row)

    seeds = []
    for sid, group in by_seller.items():
        best: dict[str | int, dict] = {}
        for row in group:
            iid = row.get("item_id", row.get("id"))
            if iid is None:
                continue
            prev = best.get(iid)
            if prev is None or int(row.get("buy_score") or 0) > int(
                prev.get("buy_score") or 0
            ):
                best[iid] = row
        if len(best) != 1:
            continue
        row = next(iter(best.values()))
        country = (
            str(row.get("seller_country") or "").strip().lower()
            or "ro"
        )
        seeds.append(
            {
                "seller_id": int(sid) if str(sid).isdigit() else sid,
                "seller": row.get("seller_login") or row.get("seller"),
                "country": country,
                "watch": row.get("hunt_name") or row.get("watch"),
                "buy_score": int(row.get("buy_score") or 0),
                "item_id": row.get("item_id", row.get("id")),
            }
        )
    seeds.sort(key=lambda s: (-int(s.get("buy_score") or 0), str(s.get("seller") or "")))
    return seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hunt", default="Mamalicious", help="Hunt name substring")
    parser.add_argument(
        "--closet-limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Max closet listings to fetch per seller",
    )
    parser.add_argument(
        "--max-sellers",
        type=int,
        default=20,
        help="Cap how many seed sellers to crawl this run",
    )
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    _load_dotenv()
    args = build_parser().parse_args()
    gateway = os.environ.get("AI_GATEWAY_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not args.dry_run and not gateway and not gemini_key:
        print("Need AI_GATEWAY_API_KEY or GEMINI_API_KEY", file=sys.stderr)
        sys.exit(1)

    config = bot.load_config()
    watches = config["watches"]
    watch_by_name = {w["name"]: w for w in watches}
    branded = [
        w
        for w in watches
        if str(args.hunt or "").casefold() in str(w.get("name") or "").casefold()
    ]
    if not branded:
        print(f"No watches match hunt={args.hunt!r}", file=sys.stderr)
        sys.exit(1)

    store = ss.open_store()
    if type(store).__name__ == "NullScoredStore":
        print("DATABASE_URL missing or DB unreachable.", file=sys.stderr)
        sys.exit(1)

    gemini_client = None
    if gemini_key and bot.genai is not None:
        gemini_client = bot.genai.Client(api_key=gemini_key)

    veto_store = lv.open_store()
    try:
        taste_outcomes = veto_store.load_outcomes()
    except Exception as e:
        print(f"taste outcomes skipped: {e}", file=sys.stderr)
        taste_outcomes = []
    veto_store.close()

    recent = store.load_recent(50000)
    seeds = select_haul_seeds(recent, hunt_needle=args.hunt)[: args.max_sellers]
    print(f"haul seeds for {args.hunt!r}: {len(seeds)}", file=sys.stderr)
    for seed in seeds:
        print(
            f"  seed {seed.get('seller')} score={seed.get('buy_score')} "
            f"country={seed.get('country')} item={seed.get('item_id')}",
            file=sys.stderr,
        )
    if not seeds:
        print("Nothing to crawl.", file=sys.stderr)
        store.close()
        return

    already = already_scored_keys(store)
    by_country: dict[str, list] = {}
    for seed in seeds:
        by_country.setdefault(seed["country"], []).append(seed["seller_id"])

    closets: dict[str, list] = {}
    for country, ids in by_country.items():
        print(
            f"Closet crawl {country}: {len(ids)} seller(s) limit={args.closet_limit}",
            file=sys.stderr,
        )
        if args.dry_run:
            continue
        closets.update(bot.get_seller_closets(ids, country, args.closet_limit))

    scored_n = 0
    upserted = 0
    for seed in seeds:
        sid = str(seed["seller_id"])
        closet = closets.get(sid) or []
        if args.dry_run:
            print(f"[dry-run] would crawl {seed.get('seller')} closet", file=sys.stderr)
            continue
        print(
            f"seller {seed.get('seller')}: closet={len(closet)}",
            file=sys.stderr,
        )
        by_watch: dict[str, list] = {}
        for raw in closet:
            iid = raw.get("id")
            if iid is None:
                continue
            matches = bot.matching_watches(raw, branded)
            if not matches:
                continue
            watch = matches[0]
            key = f"{iid}:{watch['name']}"
            if key in already:
                continue
            by_watch.setdefault(watch["name"], []).append(raw)
        for hunt_name, items in by_watch.items():
            watch = watch_by_name.get(hunt_name)
            if not watch or not items:
                continue
            bot.attach_seller_profiles(items, bot._country(watch))
            taste_block = None
            try:
                from backfill_scored_listings import taste_block_for

                taste_block = taste_block_for(watch, config, taste_outcomes)
            except Exception:
                taste_block = None
            chunk_size = 10
            for offset in range(0, len(items), chunk_size):
                chunk = items[offset : offset + chunk_size]
                scores = bot.score_listings(
                    watch,
                    chunk,
                    gateway,
                    gemini_client,
                    config,
                    taste_block=taste_block,
                )
                by_id = {str(s["id"]): s for s in scores if s.get("id") is not None}
                rows = []
                for item in chunk:
                    score = by_id.get(str(item.get("id")))
                    key = f"{item.get('id')}:{hunt_name}"
                    if not score:
                        rows.append(
                            ss.row_from_item(
                                item, hunt_name, "closet_crawl", hunt_fit=None
                            )
                        )
                        continue
                    rows.append(
                        ss.row_from_item_score(
                            item, score, hunt_name, "closet_crawl"
                        )
                    )
                    scored_n += 1
                    already.add(key)
                store.upsert_many(rows)
                upserted += len(rows)
                print(
                    f"  scored {hunt_name}: {len(by_id)}/{len(chunk)}",
                    file=sys.stderr,
                )
                time.sleep(0.4)

    print(
        f"Done. upserted={upserted} newly_scored={scored_n} seeds={len(seeds)} "
        f"crdb_count={store.count()}",
        file=sys.stderr,
    )
    if args.export and not args.dry_run:
        from backfill_scored_listings import export_store

        export_store(store)
    store.close()


def already_scored_keys(store) -> set[str]:
    out: set[str] = set()
    try:
        with store._conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(
                """
                SELECT item_id::text || ':' || hunt_name FROM scored_listings
                WHERE has_score = true AND score_version = 2
                """
            )
            out = {r[0] for r in cur.fetchall()}
    except Exception:
        for row in store.load_recent(50000):
            if int(row.get("score_version") or 0) == 2 and row.get("has_score"):
                out.add(f"{row.get('item_id')}:{row.get('hunt_name')}")
    return out


if __name__ == "__main__":
    main()

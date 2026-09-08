#!/usr/bin/env python3
"""Merge legacy_active_v2 progress when hunt-state commits rebase-conflict."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _pair_key(item) -> tuple[str, str] | str:
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return (str(item[0]), str(item[1]))
    return str(item)


def merge_pair_lists(*groups) -> list:
    seen: set = set()
    out: list = []
    for group in groups:
        for item in group or []:
            key = _pair_key(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def merge_legacy_progress(main: dict, incoming: dict) -> dict:
    result = dict(main)
    current = dict(main.get("legacy_active_v2") or {})
    incoming_progress = dict(incoming.get("legacy_active_v2") or {})
    merged = dict(current)
    for key, value in incoming_progress.items():
        if key in {
            "unavailable_pairs",
            "stuck_pairs",
            "live_unscored_counts",
            "last_run",
            "cursor",
        }:
            continue
        merged[key] = value
    merged["unavailable_pairs"] = merge_pair_lists(
        current.get("unavailable_pairs"),
        incoming_progress.get("unavailable_pairs"),
    )
    merged["stuck_pairs"] = merge_pair_lists(
        current.get("stuck_pairs"),
        incoming_progress.get("stuck_pairs"),
    )
    counts = {
        str(key): int(value or 0)
        for key, value in (current.get("live_unscored_counts") or {}).items()
    }
    for key, value in (incoming_progress.get("live_unscored_counts") or {}).items():
        counts[str(key)] = max(counts.get(str(key), 0), int(value or 0))
    merged["live_unscored_counts"] = counts
    if incoming_progress.get("last_run"):
        merged["last_run"] = incoming_progress["last_run"]
    if incoming_progress.get("cursor") is not None:
        merged["cursor"] = incoming_progress["cursor"]
    result["legacy_active_v2"] = merged
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print(
            "usage: merge_legacy_state.py MAIN.json INCOMING.json OUTPUT.json",
            file=sys.stderr,
        )
        return 2
    main_path, incoming_path, output_path = map(Path, args)
    merged = merge_legacy_progress(
        json.loads(main_path.read_text()),
        json.loads(incoming_path.read_text()),
    )
    output_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

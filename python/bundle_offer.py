"""Bundle offer guidance: pure suggest + config (no I/O)."""

from __future__ import annotations

import math

DEFAULTS = {
    "gym_target_delivered_per_item_ron": 30,
    "maternity_target_delivered_per_item_ron": 50,
    "min_haircut": 0.10,
    "max_haircut_alerted": 0.25,
    "max_haircut_near": 0.35,
    "default_checkout_extra_ron": 25,
}

NEAR_KINDS = frozenset({"near_haul", "index_near_bundle"})
ALERTED_KINDS = frozenset({"value_haul", "keep_bundle", "index_keep_bundle"})


def bundle_offer_config(config: dict | None = None) -> dict:
    merged = dict(DEFAULTS)
    if config:
        merged.update(config.get("bundle_offer") or {})
    return merged


def suggest_bundle_offer(
    listing_sum: float,
    checkout_extra: float,
    n_useful: int,
    *,
    target_per_item: float,
    max_haircut: float,
    min_haircut: float = 0.10,
) -> dict | None:
    """Back-solve goods total for target delivered/item, then clamp haircut band.

    Returns suggested_offer_ron, offer_weak, offer_target_per_item_ron — or None
    when guidance does not apply.
    """
    try:
        listing = float(listing_sum)
        extra = float(checkout_extra)
        n = int(n_useful)
        target = float(target_per_item)
        max_h = float(max_haircut)
        min_h = float(min_haircut)
    except (TypeError, ValueError):
        return None
    if n < 2 or listing <= 0 or target <= 0:
        return None
    if not (0 < min_h < 1) or not (0 < max_h < 1) or max_h < min_h:
        return None

    raw = math.floor(target * n - extra)
    lo = listing * (1.0 - max_h)
    hi = listing * (1.0 - min_h)
    weak = raw < lo
    clamped = min(max(float(raw), lo), hi)
    offer = int(math.floor(clamped))
    if offer < 1:
        offer = 1
    return {
        "suggested_offer_ron": offer,
        "offer_weak": bool(weak),
        "offer_target_per_item_ron": target,
    }


def max_haircut_for_kind(kind: str, cfg: dict) -> float:
    if kind in NEAR_KINDS:
        return float(cfg.get("max_haircut_near", DEFAULTS["max_haircut_near"]))
    return float(cfg.get("max_haircut_alerted", DEFAULTS["max_haircut_alerted"]))


def target_per_item_for_watch(watch: dict | None, watch_name: str | None, cfg: dict) -> float:
    from value_haul import is_maternity_watch

    w = dict(watch or {})
    if watch_name and not w.get("name"):
        w["name"] = watch_name
    if is_maternity_watch(w):
        return float(
            cfg.get(
                "maternity_target_delivered_per_item_ron",
                DEFAULTS["maternity_target_delivered_per_item_ron"],
            )
        )
    return float(
        cfg.get(
            "gym_target_delivered_per_item_ron",
            DEFAULTS["gym_target_delivered_per_item_ron"],
        )
    )


def offer_fields(
    listing_sum: float,
    checkout_extra: float,
    n_useful: int,
    *,
    kind: str,
    watch: dict | None = None,
    watch_name: str | None = None,
    config: dict | None = None,
) -> dict:
    """Fields to merge onto a bundle record (empty dict if no suggestion)."""
    cfg = bundle_offer_config(config)
    suggestion = suggest_bundle_offer(
        listing_sum,
        checkout_extra,
        n_useful,
        target_per_item=target_per_item_for_watch(watch, watch_name, cfg),
        max_haircut=max_haircut_for_kind(kind, cfg),
        min_haircut=float(cfg.get("min_haircut", DEFAULTS["min_haircut"])),
    )
    return dict(suggestion) if suggestion else {}

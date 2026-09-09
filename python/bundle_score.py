from __future__ import annotations

import math
from typing import Any

import buy_score

BUNDLE_SCORE_VERSION = 1
DEFAULTS = {
    "extras_weight": 0.15,
    "quality_gap_penalty": 0.05,
    "fee_relief_scale": 6.0,
    "extras_term_min": -8.0,
    "extras_term_max": 12.0,
}
UNRANKED_KINDS = frozenset({"near_haul"})


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def score_config(config: dict | None = None) -> dict:
    raw = (config or {}).get("bundle_scoring") or {}
    out = dict(DEFAULTS)
    out.update({key: raw[key] for key in DEFAULTS if key in raw})
    try:
        version = int(raw.get("score_version", BUNDLE_SCORE_VERSION))
    except (TypeError, ValueError, OverflowError):
        version = BUNDLE_SCORE_VERSION
    out["score_version"] = version
    return out


def confidence_label(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    value = float(confidence)
    if value < 0.60:
        return "low"
    if value < 0.80:
        return "medium"
    return "high"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int_score(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    as_int = int(round(number))
    return as_int if 0 <= as_int <= 100 else None


def _is_v2_member(member: dict) -> bool:
    return buy_score.is_v2_score(
        {
            "score_version": member.get("score_version"),
            "buy_score": member.get("buy_score"),
        }
    )


def _eligible_members(members: list[dict]) -> list[dict]:
    out = []
    for member in members:
        if not isinstance(member, dict):
            continue
        if not _is_v2_member(member):
            continue
        if member.get("verification_concern") == "block":
            continue
        buy = _int_score(member.get("buy_score"))
        if buy is None:
            continue
        conf = _number(member.get("score_confidence"))
        if conf is None or not 0 <= conf <= 1:
            continue
        row = dict(member)
        row["buy_score"] = buy
        row["score_confidence"] = conf
        out.append(row)
    return out


def _is_keep_member(member: dict, config: dict | None = None) -> bool:
    if str(member.get("role") or "").lower() == "keep":
        return True
    cfg = buy_score.score_config(config)
    buy = _int_score(member.get("buy_score"))
    conf = _number(member.get("score_confidence"))
    if buy is None or conf is None:
        return False
    return (
        buy >= int(cfg["keep_min_score"])
        and conf >= float(cfg["min_keep_confidence"])
        and member.get("verification_concern") != "block"
        and member.get("hunt_fit") is not False
    )


def _null_result(version: int) -> dict:
    return {
        "bundle_score": None,
        "bundle_score_version": version,
        "bundle_confidence": None,
        "bundle_anchor_item_id": None,
        "bundle_rank_position": None,
    }


def _split_anchor_extras(eligible: list[dict], anchor: dict) -> list[dict]:
    extras = []
    seen_anchor = False
    anchor_id = anchor.get("id")
    for member in eligible:
        same = (
            member["buy_score"] == anchor["buy_score"]
            and str(member.get("id")) == str(anchor_id)
            and member["score_confidence"] == anchor["score_confidence"]
        )
        if not seen_anchor and same:
            seen_anchor = True
            continue
        extras.append(member)
    return extras


def calculate_bundle_score(
    members: list[dict],
    *,
    kind: str | None = None,
    config: dict | None = None,
) -> dict:
    cfg = score_config(config)
    version = int(cfg["score_version"])
    kind_key = kind or "keep_bundle"
    if kind_key in UNRANKED_KINDS:
        return _null_result(version)

    eligible = _eligible_members(members or [])
    if not eligible:
        return _null_result(version)

    if kind_key in {"keep_bundle", "index_keep_bundle"}:
        keep_pool = [m for m in eligible if _is_keep_member(m, config)]
        anchor_pool = keep_pool or eligible
    else:
        anchor_pool = eligible

    anchor = max(
        anchor_pool,
        key=lambda m: (m["buy_score"], m["score_confidence"], str(m.get("id") or "")),
    )
    extras = _split_anchor_extras(eligible, anchor)
    n = len(eligible)
    fee_relief = clamp(
        cfg["fee_relief_scale"] * (n - 1) / n,
        0.0,
        float(cfg["fee_relief_scale"]),
    )
    if not extras:
        extras_term = 0.0
    else:
        extra_mean = sum(m["buy_score"] for m in extras) / len(extras)
        quality_gap = anchor["buy_score"] - extra_mean
        extras_term = clamp(
            float(cfg["extras_weight"]) * (extra_mean - 50.0)
            - float(cfg["quality_gap_penalty"]) * max(quality_gap, 0.0)
            + fee_relief,
            float(cfg["extras_term_min"]),
            float(cfg["extras_term_max"]),
        )

    raw = clamp(anchor["buy_score"] + extras_term, 0.0, 100.0)
    confidences = [m["score_confidence"] for m in eligible]
    bundle_confidence = min(
        anchor["score_confidence"],
        sum(confidences) / len(confidences),
    )

    return {
        "bundle_score": int(round(raw)),
        "bundle_score_version": version,
        "bundle_confidence": round(bundle_confidence, 4),
        "bundle_anchor_item_id": anchor.get("id"),
        "bundle_rank_position": None,
    }


def apply_to_row(row: dict, config: dict | None = None) -> dict:
    """Return a shallow copy of row with bundle score fields set."""
    out = dict(row or {})
    kind = out.get("kind") or "keep_bundle"
    out.update(
        calculate_bundle_score(out.get("items") or [], kind=kind, config=config)
    )
    return out


def _fingerprint(row: dict) -> str:
    sid = row.get("seller_id")
    ids = sorted(
        str(it.get("id"))
        for it in (row.get("items") or [])
        if isinstance(it, dict) and it.get("id") is not None
    )
    return f"{sid}:" + ",".join(ids)


def assign_bundle_ranks(rows: list[dict]) -> list[dict]:
    """Assign bundle_rank_position among scored rows; unscored stay null."""
    decorated = [dict(row or {}) for row in rows]
    scored: list[tuple[int, int, str, str]] = []
    for index, row in enumerate(decorated):
        score = _int_score(row.get("bundle_score"))
        if score is None:
            row["bundle_rank_position"] = None
            continue
        scored.append(
            (index, score, str(row.get("kept_at") or ""), _fingerprint(row))
        )
    scored.sort(key=lambda t: t[3])
    scored.sort(key=lambda t: t[2], reverse=True)
    scored.sort(key=lambda t: t[1], reverse=True)
    for position, (index, *_rest) in enumerate(scored, start=1):
        decorated[index]["bundle_rank_position"] = position
    return decorated

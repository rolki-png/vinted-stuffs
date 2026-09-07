from __future__ import annotations

import math
from typing import Any

SCORE_VERSION = 2
FACTOR_WEIGHTS = {
    "usefulness": 0.30,
    "quality": 0.20,
    "condition": 0.15,
    "versatility": 0.10,
    "value": 0.25,
}
DEFAULTS = {
    "keep_min_score": 85,
    "bundle_min_score": 60,
    "min_keep_confidence": 0.60,
    "duplication_penalty": 15.0,
    "absolute_saving_full_scale_ron": 200.0,
    "personal_adjustment_cap": 10.0,
}
VALID_VERIFICATION = {"none", "inspect", "block"}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def score_config(config: dict | None) -> dict:
    raw = (config or {}).get("buy_scoring") or {}
    out = dict(DEFAULTS)
    out.update({key: raw[key] for key in DEFAULTS if key in raw})
    out["factor_weights"] = dict(FACTOR_WEIGHTS)
    supplied = raw.get("factor_weights")
    if isinstance(supplied, dict):
        out["factor_weights"].update(
            {key: float(supplied[key]) for key in FACTOR_WEIGHTS if key in supplied}
        )
    total = sum(out["factor_weights"].values())
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError("buy_scoring.factor_weights must sum to 1")
    return out


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _factor(raw: dict, key: str, *, probability: bool = False) -> tuple[float, float, str]:
    field = raw.get(key) if isinstance(raw.get(key), dict) else {}
    neutral = 0.5 if probability else 50.0
    high = 1.0 if probability else 100.0
    value = clamp(_number(field.get("value"), neutral), 0.0, high)
    confidence = clamp(_number(field.get("confidence"), 0.0), 0.0, 1.0)
    adjusted = neutral + confidence * (value - neutral)
    return adjusted, confidence, str(field.get("evidence") or "unknown")[:240]


def buy_band(score: int) -> str:
    if score >= 95:
        return "exceptional"
    if score >= 85:
        return "keep"
    if score >= 75:
        return "good"
    if score >= 60:
        return "bundle"
    return "skip"


def is_v2_score(score: dict) -> bool:
    return int(score.get("score_version") or 0) == SCORE_VERSION and score.get("buy_score") is not None


def calculate_buy_score(
    extraction: dict,
    delivered_cost_ron: float,
    config: dict | None = None,
) -> dict:
    cfg = score_config(config)
    raw = extraction.get("factors") if isinstance(extraction.get("factors"), dict) else {}
    delivered = max(0.0, _number(delivered_cost_ron, 0.0))
    replacement_field = (
        raw.get("equivalent_replacement_cost")
        if isinstance(raw.get("equivalent_replacement_cost"), dict)
        else {}
    )
    replacement = _number(replacement_field.get("value"), 0.0)
    replacement_confidence = clamp(
        _number(replacement_field.get("confidence"), 0.0), 0.0, 1.0
    )
    invalid_value = replacement <= 0
    if invalid_value:
        value_raw = 0.0
        replacement_confidence = 0.0
    else:
        saving = replacement - delivered
        relative = clamp(50.0 + 50.0 * saving / replacement, 0.0, 100.0)
        absolute = clamp(
            50.0
            + 50.0 * saving / float(cfg["absolute_saving_full_scale_ron"]),
            0.0,
            100.0,
        )
        value_raw = 0.60 * relative + 0.40 * absolute
    values: dict[str, float] = {}
    confidences: dict[str, float] = {}
    evidence: dict[str, str] = {}
    for key in ("usefulness", "quality", "condition", "versatility"):
        values[key], confidences[key], evidence[key] = _factor(raw, key)
    values["value"] = 50.0 + replacement_confidence * (value_raw - 50.0)
    confidences["value"] = replacement_confidence
    evidence["value"] = str(replacement_field.get("evidence") or "unknown")[:240]
    fit, fit_confidence, fit_evidence = _factor(raw, "fit_probability", probability=True)
    duplicate, duplicate_confidence, duplicate_evidence = _factor(
        raw, "duplication_probability", probability=True
    )
    requested = extraction.get("personal_adjustments")
    requested = requested if isinstance(requested, dict) else {}
    applied: dict[str, float] = {}
    cap = float(cfg["personal_adjustment_cap"])
    for key in ("usefulness", "quality", "condition", "versatility", "value"):
        adjustment = clamp(_number(requested.get(key), 0.0), -cap, cap)
        values[key] = clamp(values[key] + adjustment, 0.0, 100.0)
        applied[key] = adjustment
    fit_adjustment = clamp(_number(requested.get("fit_probability"), 0.0), -cap, cap)
    duplicate_adjustment = clamp(
        _number(requested.get("duplication_probability"), 0.0), -cap, cap
    )
    fit = clamp(fit + fit_adjustment / 100.0, 0.0, 1.0)
    duplicate = clamp(duplicate + duplicate_adjustment / 100.0, 0.0, 1.0)
    applied["fit_probability"] = fit_adjustment
    applied["duplication_probability"] = duplicate_adjustment
    base = sum(cfg["factor_weights"][key] * values[key] for key in FACTOR_WEIGHTS)
    raw_utility = fit * base - float(cfg["duplication_penalty"]) * duplicate
    score = 0 if invalid_value else round(clamp(raw_utility, 0.0, 100.0))
    sigma_fit = 0.25 * (1.0 - fit_confidence)
    sigma_duplicate = 0.25 * (1.0 - duplicate_confidence)
    variance = (base * sigma_fit) ** 2
    variance += sum(
        (fit * cfg["factor_weights"][key] * 25.0 * (1.0 - confidences[key])) ** 2
        for key in FACTOR_WEIGHTS
    )
    variance += (float(cfg["duplication_penalty"]) * sigma_duplicate) ** 2
    half_width = 1.645 * math.sqrt(variance)
    score_confidence = min(
        fit_confidence,
        sum(cfg["factor_weights"][key] * confidences[key] for key in FACTOR_WEIGHTS),
    )
    verification = str(extraction.get("verification_concern") or "none").lower()
    verification = verification if verification in VALID_VERIFICATION else "block"
    if invalid_value:
        verification = "block"
    return {
        "id": extraction.get("id"),
        "score_version": SCORE_VERSION,
        "buy_score": score,
        "buy_band": buy_band(score),
        "score_confidence": round(score_confidence, 4),
        "score_interval_low": round(clamp(raw_utility - half_width, 0.0, 100.0)),
        "score_interval_high": round(clamp(raw_utility + half_width, 0.0, 100.0)),
        "score_factors": {
            **values,
            "fit_probability": round(fit, 4),
            "duplication_probability": round(duplicate, 4),
            "delivered_cost_ron": round(delivered, 2),
            "equivalent_replacement_cost_ron": round(replacement, 2),
            "personal_adjustments": applied,
        },
        "factor_evidence": {
            **evidence,
            "fit_probability": fit_evidence,
            "duplication_probability": duplicate_evidence,
        },
        "verification_concern": verification,
        "verification_reason": str(extraction.get("verification_reason") or "")[:240],
        "hunt_fit": extraction.get("hunt_fit") is True,
        "reason": str(extraction.get("reason") or "")[:240],
    }

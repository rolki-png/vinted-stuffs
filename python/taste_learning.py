"""Family-scoped taste learning from explicit, factor-scoped feedback."""
from __future__ import annotations

from typing import Any

# First match wins (case-insensitive substring on hunt name).
_FAMILY_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "maternity",
        (
            "maternity",
            "mama",
            "mamalicious",
            "seraphine",
            "noppies",
            "hatch",
            "storq",
            "legoe",
            "bae the label",
            "tiffany rose",
            "boob",
            "ripe",
            "envie",
            "jojo",
            "beyond nine",
            "isabella oliver",
            "pietro brunelli",
            "next maternity",
            "asos maternity",
            "h&m mama",
            "leggings",
        ),
    ),
    (
        "sneakers",
        ("new balance", "asics", "diadora"),
    ),
    (
        "gym",
        (
            "gym",
            "running",
            "gorewear",
            "2xu",
            "craft",
            "saysky",
            "falke",
            "odlo",
            "lululemon",
            "ten thousand",
            "rhone",
            "vuori",
            "tracksmith",
            "h&m sport",
        ),
    ),
    (
        "knitwear",
        (
            "merino",
            "cashmere",
            "johnstons",
            "cruciani",
            "gran sasso",
            "fedeli",
            "sunspel",
            "zimmerli",
            "hanro",
            "merz",
            "cdlp",
            "devold",
            "smartwool",
            "ortovox",
            "woolpower",
            "polo",
        ),
    ),
]

_DEFAULT_TASTE = {
    "enabled": True,
    "prompt_examples_per_polarity": 5,
}

REASON_SCOPES = {
    "wrong_size": "fit_probability adjustment only",
    "bad_fit_style": "fit_probability adjustment only",
    "low_quality_condition": "quality/condition adjustment only",
    "poor_value": "value adjustment only",
    "rarely_useful": "usefulness adjustment only",
    "already_own_similar": "duplication_probability adjustment only",
}


def taste_config(config: dict | None) -> dict:
    raw = (config or {}).get("taste_learning") or {}
    out = dict(_DEFAULT_TASTE)
    if isinstance(raw, dict):
        for key in _DEFAULT_TASTE:
            if key in raw:
                out[key] = raw[key]
    out["enabled"] = bool(out["enabled"])
    out["prompt_examples_per_polarity"] = int(out["prompt_examples_per_polarity"])
    return out


def resolve_family(hunt_name: str, watch: dict | None = None) -> str:
    if watch and watch.get("family"):
        return str(watch["family"]).strip().lower() or "other"
    name = (hunt_name or "").lower()
    for family, needles in _FAMILY_RULES:
        for needle in needles:
            if needle in name:
                return family
    return "other"


def _format_outcome_line(row: dict) -> str:
    title = str(row.get("title") or "")[:80]
    brand = row.get("brand") or "?"
    size = row.get("size") or "?"
    price = row.get("price_ron")
    price_s = f"{price}" if price is not None else "?"
    if row.get("buy_score") is not None:
        band = row.get("buy_band") or "?"
        score = row.get("buy_score")
    else:
        band = row.get("value_band") or "?"
        score = row.get("deal_score")
    score_s = f"{score}" if score is not None else "?"
    return (
        f"- {title} | brand={brand} size={size} "
        f"price={price_s} band={band} score={score_s}"
    )


def build_taste_prompt_block(
    outcomes: list[dict], *, per_polarity: int = 5
) -> str:
    bought = [r for r in outcomes if r.get("status") == "bought"]
    removed_by_reason: dict[str, list[dict]] = {}
    for row in outcomes:
        if row.get("status") != "removed":
            continue
        reason = row.get("reason_code")
        if reason in REASON_SCOPES:
            removed_by_reason.setdefault(reason, []).append(row)

    # Prefer most recent first if updated_at present
    def _sort_key(r: dict) -> Any:
        return r.get("updated_at") or ""

    limit = max(0, int(per_polarity))
    bought = sorted(bought, key=_sort_key, reverse=True)[:limit]
    negative_limit = max(3, limit)
    reason_groups = [
        (
            reason,
            sorted(rows, key=_sort_key, reverse=True)[:negative_limit],
        )
        for reason, rows in removed_by_reason.items()
        if len(rows) >= 3
    ]
    if not bought and not reason_groups:
        return ""

    parts = [
        "Buyer taste from desk outcomes in this hunt family "
        "(use Bought as positive context; apply reasoned Remove feedback only "
        "to its named factor; ignore Park):"
    ]
    if bought:
        parts.append("Bought (strong positive):")
        parts.extend(_format_outcome_line(r) for r in bought)
    for reason, rows in reason_groups:
        parts.append(f"Removed reason={reason} ({REASON_SCOPES[reason]}):")
        parts.extend(_format_outcome_line(r) for r in rows)
    return "\n".join(parts)

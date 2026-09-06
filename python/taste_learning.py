"""Family-scoped taste learning: prompt few-shots + conservative hard suppress."""
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
    "hard_suppress_min_removes": 3,
    "hard_suppress_require_zero_bought": True,
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
    out["hard_suppress_min_removes"] = int(out["hard_suppress_min_removes"])
    out["hard_suppress_require_zero_bought"] = bool(
        out["hard_suppress_require_zero_bought"]
    )
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


def normalize_brand(brand: str | None) -> str:
    if brand is None:
        return ""
    return " ".join(str(brand).strip().lower().split())


def normalize_size(size: str | None) -> str:
    if size is None:
        return ""
    return " ".join(str(size).strip().lower().split())


def pattern_key(
    family: str, brand: str | None, size: str | None
) -> str | None:
    b = normalize_brand(brand)
    if not b:
        return None
    fam = (family or "other").strip().lower() or "other"
    return f"{fam}|{b}|{normalize_size(size)}"


def _format_outcome_line(row: dict) -> str:
    title = str(row.get("title") or "")[:80]
    brand = row.get("brand") or "?"
    size = row.get("size") or "?"
    price = row.get("price_ron")
    price_s = f"{price}" if price is not None else "?"
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
    removed = [r for r in outcomes if r.get("status") == "removed"]
    # Prefer most recent first if updated_at present
    def _sort_key(r: dict) -> Any:
        return r.get("updated_at") or ""

    bought = sorted(bought, key=_sort_key, reverse=True)[: max(0, int(per_polarity))]
    removed = sorted(removed, key=_sort_key, reverse=True)[: max(0, int(per_polarity))]
    if not bought and not removed:
        return ""

    parts = [
        "Buyer taste from desk outcomes in this hunt family "
        "(prefer Bought patterns; avoid Removed patterns; ignore Park):"
    ]
    if bought:
        parts.append("Bought (strong positive):")
        parts.extend(_format_outcome_line(r) for r in bought)
    if removed:
        parts.append("Removed (strong negative):")
        parts.extend(_format_outcome_line(r) for r in removed)
    return "\n".join(parts)


def hard_suppress(
    candidate: dict,
    outcomes: list[dict],
    *,
    min_removes: int = 3,
    require_zero_bought: bool = True,
) -> bool:
    key = pattern_key(
        candidate.get("hunt_family") or candidate.get("family") or "other",
        candidate.get("brand"),
        candidate.get("size"),
    )
    if key is None:
        return False

    removes = 0
    boughts = 0
    for row in outcomes:
        st = row.get("status")
        if st not in ("removed", "bought"):
            continue
        row_key = pattern_key(
            row.get("hunt_family") or row.get("family") or "other",
            row.get("brand"),
            row.get("size"),
        )
        if row_key != key:
            continue
        if st == "removed":
            removes += 1
        elif st == "bought":
            boughts += 1

    if require_zero_bought and boughts > 0:
        return False
    return removes >= int(min_removes)

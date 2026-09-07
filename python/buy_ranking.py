from __future__ import annotations

import math
from collections import defaultdict

import buy_score


def candidate_key(candidate: dict) -> str:
    item = candidate.get("item") if isinstance(candidate, dict) else {}
    item = item if isinstance(item, dict) else {}
    return f"{item.get('id')}:{candidate.get('watch') or ''}"


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _qualified(candidate: dict, config: dict | None = None) -> bool:
    score = candidate.get("score") if isinstance(candidate, dict) else {}
    score = score if isinstance(score, dict) else {}
    value = _number(score.get("buy_score"))
    confidence = _number(score.get("score_confidence"))
    cfg = buy_score.score_config(config)
    try:
        is_v2 = int(score.get("score_version") or 0) == buy_score.SCORE_VERSION
    except (TypeError, ValueError, OverflowError):
        is_v2 = False
    item = candidate.get("item") if isinstance(candidate, dict) else {}
    item = item if isinstance(item, dict) else {}
    watch = candidate.get("watch_obj") if isinstance(candidate, dict) else {}
    watch = watch if isinstance(watch, dict) else {}
    return (
        item.get("id") is not None
        and is_v2
        and value is not None
        and 0 <= value <= 100
        and value >= float(cfg["keep_min_score"])
        and confidence is not None
        and 0 <= confidence <= 1
        and confidence >= float(cfg["min_keep_confidence"])
        and score.get("hunt_fit") is True
        and score.get("verification_concern") != "block"
        and not watch.get("bundle_hunt")
    )


def _overlap(left: dict, right: dict) -> bool:
    left_score = left.get("score") or {}
    right_score = right.get("score") or {}
    left_low = _number(left_score.get("score_interval_low"))
    left_high = _number(left_score.get("score_interval_high"))
    right_low = _number(right_score.get("score_interval_low"))
    right_high = _number(right_score.get("score_interval_high"))
    if None in (left_low, left_high, right_low, right_high):
        return False
    if left_low > left_high or right_low > right_high:
        return False
    return left_low <= right_high and right_low <= left_high


def _bounded_count(value, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _pairwise_limit(config: dict | None) -> int:
    cfg = (config or {}).get("buy_scoring") or {}
    return _bounded_count(cfg.get("pairwise_max_candidates", 20), 20)


def _qualified_in_score_order(
    candidates: list[dict],
    config: dict | None,
) -> list[dict]:
    return sorted(
        (row for row in candidates if _qualified(row, config)),
        key=lambda row: (
            -float(row["score"]["buy_score"]),
            candidate_key(row),
        ),
    )


def comparison_pairs(
    candidates: list[dict],
    config: dict | None,
) -> list[tuple[str, str]]:
    cfg = (config or {}).get("buy_scoring") or {}
    neighbors = _bounded_count(cfg.get("pairwise_neighbors", 2), 2)
    rows = _qualified_in_score_order(candidates, config)[: _pairwise_limit(config)]
    pairs: list[tuple[str, str]] = []
    for index, left in enumerate(rows):
        for right in rows[index + 1 : index + 1 + neighbors]:
            if _overlap(left, right):
                pairs.append((candidate_key(left), candidate_key(right)))
    return pairs


def bradley_terry_rank(
    candidate_ids: list[str],
    outcomes: list[dict],
) -> list[str]:
    ids = list(dict.fromkeys(candidate_ids))
    strengths = {key: 1.0 for key in ids}
    wins: defaultdict[str, float] = defaultdict(float)
    games: defaultdict[str, defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for outcome in outcomes:
        left, right = outcome.get("left"), outcome.get("right")
        winner = outcome.get("winner")
        if (
            left not in strengths
            or right not in strengths
            or left == right
            or winner not in {"left", "right", "tie"}
        ):
            continue
        games[left][right] += 1
        games[right][left] += 1
        if winner == "left":
            wins[left] += 1.0
        elif winner == "right":
            wins[right] += 1.0
        else:
            wins[left] += 0.5
            wins[right] += 0.5
    for _ in range(100):
        updated = {}
        for key in ids:
            denominator = sum(
                count / max(strengths[key] + strengths[other], 1e-9)
                for other, count in games[key].items()
            )
            updated[key] = (
                wins[key] / denominator if denominator and wins[key] else 1e-6
            )
        scale = sum(updated.values()) / max(len(updated), 1)
        strengths = {
            key: value / max(scale, 1e-9) for key, value in updated.items()
        }
    return sorted(ids, key=lambda key: (-strengths[key], key))


def _valid_outcomes(candidate_ids: list[str], outcomes: list[dict]) -> list[dict]:
    known = set(candidate_ids)
    valid = []
    seen = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        pair = (outcome.get("left"), outcome.get("right"))
        if (
            pair in seen
            or pair[0] not in known
            or pair[1] not in known
            or pair[0] == pair[1]
            or outcome.get("winner") not in {"left", "right", "tie"}
        ):
            continue
        seen.add(pair)
        valid.append(outcome)
    return valid


def _connected(candidate_ids: list[str], outcomes: list[dict]) -> bool:
    if len(candidate_ids) < 2:
        return True
    graph = {key: set() for key in candidate_ids}
    for outcome in outcomes:
        left, right = outcome.get("left"), outcome.get("right")
        if left in graph and right in graph and left != right:
            graph[left].add(right)
            graph[right].add(left)
    seen = set()
    pending = [candidate_ids[0]]
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        pending.extend(graph[key] - seen)
    return seen == set(candidate_ids)


def comparison_graph_connected(
    candidates: list[dict],
    outcomes: list[dict],
    config: dict | None = None,
) -> bool:
    shortlist = _qualified_in_score_order(candidates, config)[
        : _pairwise_limit(config)
    ]
    candidate_ids = [candidate_key(row) for row in shortlist]
    valid_outcomes = _valid_outcomes(candidate_ids, outcomes)
    return bool(valid_outcomes) and _connected(candidate_ids, valid_outcomes)


def apply_rankings(
    candidates: list[dict],
    outcomes: list[dict],
    config: dict | None = None,
) -> list[dict]:
    for row in candidates:
        score = row.get("score") if isinstance(row, dict) else None
        if isinstance(score, dict):
            score.pop("rank_position", None)
            score.pop("rank_confidence", None)
    qualified = _qualified_in_score_order(candidates, config)
    limit = _pairwise_limit(config)
    shortlist = qualified[:limit]
    remainder = qualified[limit:]
    shortlist_ids = [candidate_key(row) for row in shortlist]
    valid_outcomes = _valid_outcomes(shortlist_ids, outcomes)
    usable = (
        bool(valid_outcomes)
        and _connected(shortlist_ids, valid_outcomes)
    )
    shortlist_order = (
        bradley_terry_rank(shortlist_ids, valid_outcomes)
        if usable
        else shortlist_ids
    )
    order = shortlist_order + [candidate_key(row) for row in remainder]
    position = {key: index + 1 for index, key in enumerate(order)}
    shortlist_keys = set(shortlist_ids)
    mean_confidence = 0.0
    if usable:
        confidences = [
            _number(outcome.get("confidence")) or 0.0
            for outcome in valid_outcomes
        ]
        mean_confidence = sum(confidences) / len(confidences)
    shortlist_confidence = (
        "high"
        if mean_confidence >= 0.80
        else "medium"
        if mean_confidence >= 0.60
        else "low"
    )
    for row in qualified:
        row["score"]["rank_position"] = position[candidate_key(row)]
        row["score"]["rank_confidence"] = (
            shortlist_confidence
            if candidate_key(row) in shortlist_keys
            else "low"
        )
    return candidates

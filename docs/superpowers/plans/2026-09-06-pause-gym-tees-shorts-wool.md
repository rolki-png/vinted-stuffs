# Pause gym tees / shorts focus / drop wool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-reject men’s gym T-shirts, widen shorts discovery, remove Cruciani and maternity knitwear preference.

**Architecture:** Config retargets searches/notes to shorts; `value_haul.looks_like_mens_gym_tee` + haul prefilter drop tees early; scoring prompt adds an explicit gym-tee skip line for men’s gym watches.

**Tech Stack:** `python/config.json`, `python/value_haul.py`, `python/vinted_bot.py`, unittest

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-06-pause-gym-tees-shorts-wool-design.md`
- Keep Zimmerli / Hanro / Merz / CDLP; sneakers unchanged
- Tee reject applies only to men’s gym / training / value-haul gym paths
- Country `ro`; men’s M/L `size_ids: [1739, 1740]`

---

### Task 1: Tee detector + haul prefilter (TDD)

**Files:** `python/value_haul.py`, `python/tests/test_value_haul.py`

- [ ] Failing tests: koszulka/tee rejected; shorts accepted; maternity unchanged
- [ ] Implement `looks_like_mens_gym_tee`; wire into `looks_like_haul_fit`
- [ ] Run `cd python && python3 -m unittest tests.test_value_haul -v`

### Task 2: Solo scoring gym-tee skip line

**Files:** `python/vinted_bot.py`

- [ ] When watch target is men’s gym/training/sport, append prompt rule: men’s gym T-shirts always skip; shorts are the target
- [ ] Optional cheap filter before score batch if already present pattern — prefer prompt + haul gate; add pre-score drop if easy

### Task 3: Config retarget

**Files:** `python/config.json`

- [ ] Add 4 broad shorts watches; replace `Gym bundle seeds M-L` with shorts-leaning seeds (notes: tees not useful)
- [ ] Retarget premium gym watches to shorts / skip tees
- [ ] Delete Cruciani; strip knitwear from maternity notes

### Task 4: Verify + ship

- [ ] Mark spec status approved; run desk + python tests
- [ ] Commit, push `fork` main, deploy Vercel if dashboard bits changed (bot is Actions via git)

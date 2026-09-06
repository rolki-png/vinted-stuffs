# 01: Suggest offer on value/near hauls (dashboard)

**What to build:** When a value haul or near haul is persisted, it includes a suggested bundle offer (goods total) and a weak/stretch flag derived from delivered cost per useful item (gym 30 / maternity 50) with haircut clamps. The Bundles tab shows that number (and weak labelling). Unit tests lock the pure suggest behaviour, including the maternity ~227→~187 shape.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] Pure suggest function returns whole-RON offer, weak flag, and respects min 10% / max 25% (alerted) or 35% (near) haircuts
- [x] Config (or passed knobs) expose gym 30 and maternity 50 delivered-per-item targets
- [x] New `value_haul` and `near_haul` records store `suggested_offer_ron` and `offer_weak` (omit when fewer than 2 useful items or listing sum ≤ 0)
- [x] Bundles dashboard shows the suggestion for those kinds; missing fields on old rows do not break the UI
- [x] Table-driven unit tests cover gym hit, maternity shape, near stretch, weak unreachable, and min-haircut-even-when-full-price-beats-target

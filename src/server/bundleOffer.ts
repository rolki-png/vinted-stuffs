// @ts-nocheck
/** Bundle offer guidance — mirrors scripts/bundle_offer.py (persist on index rows). */

const DEFAULTS = {
  gym_target_delivered_per_item_ron: 30,
  maternity_target_delivered_per_item_ron: 50,
  min_haircut: 0.1,
  max_haircut_alerted: 0.25,
  max_haircut_near: 0.35,
  default_checkout_extra_ron: 25,
};

const NEAR_KINDS = new Set(["near_haul", "index_near_bundle"]);

function isMaternityWatchName(name) {
  const n = String(name || "").toLowerCase();
  return n.includes("maternity") || n.includes("mama");
}

function suggestBundleOffer(
  listingSum,
  checkoutExtra,
  nUseful,
  { targetPerItem, maxHaircut, minHaircut = 0.1 } = {}
) {
  const listing = Number(listingSum);
  const extra = Number(checkoutExtra);
  const n = Number(nUseful);
  const target = Number(targetPerItem);
  const maxH = Number(maxHaircut);
  const minH = Number(minHaircut);
  if (!Number.isFinite(listing) || !Number.isFinite(extra) || !Number.isFinite(n)) return null;
  if (!Number.isFinite(target) || !Number.isFinite(maxH) || !Number.isFinite(minH)) return null;
  if (n < 2 || listing <= 0 || target <= 0) return null;
  if (!(minH > 0 && minH < 1) || !(maxH > 0 && maxH < 1) || maxH < minH) return null;

  const raw = Math.floor(target * n - extra);
  const lo = listing * (1 - maxH);
  const hi = listing * (1 - minH);
  const weak = raw < lo;
  const clamped = Math.min(Math.max(raw, lo), hi);
  let offer = Math.floor(clamped);
  if (offer < 1) offer = 1;
  return {
    suggested_offer_ron: offer,
    offer_weak: Boolean(weak),
    offer_target_per_item_ron: target,
  };
}

function offerFields(listingSum, checkoutExtra, nUseful, { kind, watchName } = {}) {
  const maxHaircut = NEAR_KINDS.has(kind)
    ? DEFAULTS.max_haircut_near
    : DEFAULTS.max_haircut_alerted;
  const targetPerItem = isMaternityWatchName(watchName)
    ? DEFAULTS.maternity_target_delivered_per_item_ron
    : DEFAULTS.gym_target_delivered_per_item_ron;
  return (
    suggestBundleOffer(listingSum, checkoutExtra, nUseful, {
      targetPerItem,
      maxHaircut,
      minHaircut: DEFAULTS.min_haircut,
    }) || {}
  );
}

export {
DEFAULTS,
  suggestBundleOffer,
  offerFields,
}

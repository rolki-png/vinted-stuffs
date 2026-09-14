// @ts-nocheck
/**
 * Runtime Vinted market defaults. Committed code is UK; other catalogs via env.
 */

const DEFAULT_COUNTRY = "uk"
const DEFAULT_CURRENCY = "GBP"
const DEFAULT_SITE_HOST = "www.vinted.co.uk"

function _clean(value) {
  return String(value || "").trim()
}

function forceCountry() {
  const value = _clean(process.env.VINTED_FORCE_COUNTRY).toLowerCase()
  return value || null
}

function defaultCountry() {
  const forced = forceCountry()
  if (forced) return forced
  const value = _clean(process.env.VINTED_COUNTRY).toLowerCase()
  return value || DEFAULT_COUNTRY
}

function defaultCurrency() {
  const value = _clean(process.env.VINTED_CURRENCY).toUpperCase()
  return value || DEFAULT_CURRENCY
}

function siteHost() {
  let value = _clean(process.env.VINTED_SITE_HOST)
    .replace(/^https?:\/\//i, "")
    .replace(/\/.*$/, "")
  return value || DEFAULT_SITE_HOST
}

function memberUrl(sellerId) {
  return `https://${siteHost()}/member/${sellerId}`
}

function marketFromEnv() {
  return {
    country: defaultCountry(),
    currency: defaultCurrency(),
    siteHost: siteHost(),
  }
}

export {
  DEFAULT_COUNTRY,
  DEFAULT_CURRENCY,
  DEFAULT_SITE_HOST,
  forceCountry,
  defaultCountry,
  defaultCurrency,
  siteHost,
  memberUrl,
  marketFromEnv,
}

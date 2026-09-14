"""Runtime Vinted market defaults. Committed code is UK; other catalogs via env."""
from __future__ import annotations

import os

# Public-tree defaults (UK Vinted).
DEFAULT_COUNTRY = "uk"
DEFAULT_CURRENCY = "GBP"
DEFAULT_SITE_HOST = "www.vinted.co.uk"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def force_country() -> str | None:
    value = _clean(os.environ.get("VINTED_FORCE_COUNTRY")).lower()
    return value or None


def default_country() -> str:
    forced = force_country()
    if forced:
        return forced
    value = _clean(os.environ.get("VINTED_COUNTRY")).lower()
    return value or DEFAULT_COUNTRY


def default_currency() -> str:
    value = _clean(os.environ.get("VINTED_CURRENCY")).upper()
    return value or DEFAULT_CURRENCY


def site_host() -> str:
    value = _clean(os.environ.get("VINTED_SITE_HOST")).lstrip("/").removeprefix("https://").removeprefix("http://")
    value = value.split("/")[0]
    return value or DEFAULT_SITE_HOST


def member_url(seller_id) -> str:
    return f"https://{site_host()}/member/{seller_id}"


def watch_country(watch: dict | None) -> str:
    forced = force_country()
    if forced:
        return forced
    watch = watch or {}
    return str(watch.get("country") or watch.get("market") or default_country()).strip().lower()

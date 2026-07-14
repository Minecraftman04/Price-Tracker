#!/usr/bin/env python3
"""Use Bambu Lab's Shopify JSON data before the generic HTML fallbacks."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

import check_price

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
PRODUCTS_BY_URL = {str(item["product_url"]).rstrip("/"): item for item in CONFIG.get("products", [])}
ORIGINAL_FETCH = check_price.fetch_html
CATALOG: list[dict[str, Any]] | None = None


def normalise(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def price_decimal(value: Any) -> Decimal | None:
    return check_price.decimal_price(value)


def cents_to_decimal(value: Any) -> Decimal | None:
    """Convert Shopify's Storefront ``.js`` integer prices from pence to pounds."""
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return (amount / Decimal("100")).quantize(Decimal("0.01"))


def request_json(url: str, timeout: int) -> dict[str, Any] | None:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Price-Tracker/2.3 (+https://github.com/Minecraftman04/Price-Tracker)",
            "Accept": "application/json,text/javascript,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
        },
        timeout=min(max(timeout, 15), 30),
        allow_redirects=True,
    )
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "").lower()
    if (
        "json" not in content_type
        and "javascript" not in content_type
        and not response.text.lstrip().startswith(("{", "["))
    ):
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def normalise_product_payload(
    payload: dict[str, Any] | None,
    *,
    prices_in_cents: bool = False,
) -> dict[str, Any] | None:
    """Return one Shopify product in the shape used by the checker.

    Shopify's public ``/products/<handle>.js`` endpoint returns the product at
    the top level and expresses prices in pence. The older ``.json`` endpoint
    wraps it in ``{"product": ...}`` and normally expresses prices in pounds.
    """
    if not isinstance(payload, dict):
        return None

    candidate = payload.get("product")
    product = candidate if isinstance(candidate, dict) else payload
    variants = product.get("variants")
    if not isinstance(variants, list) or not variants:
        return None

    normalised = dict(product)
    normalised_variants: list[dict[str, Any]] = []
    for item in variants:
        if not isinstance(item, dict):
            continue
        variant = dict(item)
        if prices_in_cents:
            for key in ("price", "compare_at_price"):
                converted = cents_to_decimal(variant.get(key))
                if converted is not None:
                    variant[key] = f"{converted:.2f}"
        normalised_variants.append(variant)

    if not normalised_variants:
        return None
    normalised["variants"] = normalised_variants
    return normalised


def load_catalog(timeout: int) -> list[dict[str, Any]]:
    global CATALOG
    if CATALOG is not None:
        return CATALOG

    products: list[dict[str, Any]] = []
    for page in range(1, 6):
        payload = request_json(
            f"https://uk.store.bambulab.com/products.json?limit=250&page={page}",
            timeout,
        )
        batch = payload.get("products", []) if payload else []
        if not isinstance(batch, list) or not batch:
            break
        products.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 250:
            break
    CATALOG = products
    print(f"Bambu Shopify catalogue contains {len(products)} products")
    return products


def product_score(candidate: dict[str, Any], wanted: dict[str, Any]) -> float:
    candidate_name = normalise(candidate.get("title", ""))
    wanted_name = normalise(wanted.get("product_name", ""))
    if not candidate_name or not wanted_name:
        return 0.0
    score = SequenceMatcher(None, candidate_name, wanted_name).ratio() * 100
    candidate_tokens = set(candidate_name.split())
    wanted_tokens = set(wanted_name.split())
    if wanted_tokens:
        score += 100 * len(candidate_tokens & wanted_tokens) / len(wanted_tokens)
    if candidate_name == wanted_name:
        score += 200
    return score


def resolve_product(url: str, wanted: dict[str, Any], timeout: int) -> dict[str, Any] | None:
    clean_url = url.rstrip("/")

    # Shopify documents the .js endpoint for storefront product data. It is
    # generally available even when the rendered Bambu page is bot-protected.
    for suffix, prices_in_cents in ((".js", True), (".json", False)):
        payload = request_json(f"{clean_url}{suffix}", timeout)
        product = normalise_product_payload(payload, prices_in_cents=prices_in_cents)
        if product:
            return product

    catalog = load_catalog(timeout)
    if not catalog:
        return None
    ranked = sorted(catalog, key=lambda item: product_score(item, wanted), reverse=True)
    if not ranked or product_score(ranked[0], wanted) < 100:
        return None
    return normalise_product_payload(ranked[0]) or ranked[0]


def variant_score(variant: dict[str, Any], wanted: dict[str, Any]) -> float:
    title = normalise(
        " ".join(
            str(variant.get(key, ""))
            for key in ("title", "option1", "option2", "option3", "sku")
            if variant.get(key) is not None
        )
    )
    target = normalise(f"{wanted.get('variant', '')} {wanted.get('sku', '')}")
    score = SequenceMatcher(None, title, target).ratio() * 100 if target else 0
    title_tokens = set(title.split())
    target_tokens = set(target.split())
    if target_tokens:
        score += 120 * len(title_tokens & target_tokens) / len(target_tokens)
    configured_sku = normalise(wanted.get("sku", ""))
    variant_sku = normalise(variant.get("sku", ""))
    if configured_sku and configured_sku == variant_sku:
        score += 300

    reference = price_decimal(wanted.get("initial_price"))
    price = price_decimal(variant.get("price"))
    if reference is not None and price is not None:
        score += max(0.0, 50.0 - float(abs(price - reference)))
    return score


def choose_variant(product: dict[str, Any], wanted: dict[str, Any]) -> dict[str, Any] | None:
    variants = product.get("variants", [])
    if not isinstance(variants, list):
        return None
    valid = [item for item in variants if isinstance(item, dict) and price_decimal(item.get("price")) is not None]
    if not valid:
        return None
    return max(valid, key=lambda item: variant_score(item, wanted))


def synthetic_product_html(product: dict[str, Any], variant: dict[str, Any], wanted: dict[str, Any]) -> str:
    price = price_decimal(variant.get("price"))
    if price is None:
        raise ValueError("Shopify variant has no valid price")
    available = bool(variant.get("available", product.get("available", True)))
    availability = "https://schema.org/InStock" if available else "https://schema.org/OutOfStock"
    variant_text = " / ".join(
        str(value)
        for value in (
            variant.get("title"),
            variant.get("option1"),
            variant.get("option2"),
            variant.get("option3"),
            variant.get("sku"),
        )
        if value and str(value).lower() != "default title"
    )
    structured = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.get("title") or wanted.get("product_name"),
        "sku": variant.get("sku") or wanted.get("sku"),
        "offers": {
            "@type": "Offer",
            "priceCurrency": "GBP",
            "price": f"{price:.2f}",
            "availability": availability,
        },
    }
    stock_text = "In stock" if available else "Out of stock"
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(structured, ensure_ascii=False)
        + "</script></head><body><main>"
        + f"<h1>{product.get('title') or wanted.get('product_name')}</h1>"
        + f"<p>{variant_text or wanted.get('variant', '')}</p>"
        + f"<span>£{price:.2f}</span><span>{stock_text}</span>"
        + "</main></body></html>"
    )


def fetch_with_shopify(url: str, timeout: int, search_url: str = "") -> tuple[str, str]:
    clean_url = url.rstrip("/")
    wanted = PRODUCTS_BY_URL.get(clean_url)
    if wanted and wanted.get("retailer") == "Bambu Lab UK":
        try:
            product = resolve_product(clean_url, wanted, timeout)
            if product:
                variant = choose_variant(product, wanted)
                if variant:
                    handle = str(product.get("handle", "")).strip()
                    resolved_url = (
                        f"https://uk.store.bambulab.com/products/{handle}"
                        if handle
                        else clean_url
                    )
                    print(
                        f"Resolved Bambu product: {wanted['product_name']} -> "
                        f"{resolved_url} | {variant.get('title')} | £{variant.get('price')} "
                        f"| available={variant.get('available')}"
                    )
                    return synthetic_product_html(product, variant, wanted), "Bambu Shopify storefront JSON"
        except Exception as exc:  # noqa: BLE001
            print(f"Bambu Shopify JSON fallback failed for {wanted['product_name']}: {exc}", file=sys.stderr)

        # Bambu can block both Shopify JSON endpoints while its rendered product
        # page remains readable through the existing fallback. Preserve live
        # stock information from that page even when its price is client-rendered.
        fallback_html, fallback_source = ORIGINAL_FETCH(url, timeout, search_url)
        live_stock = check_price.extract_stock(
            fallback_html,
            variant=str(wanted.get("variant", "")),
            product_name=str(wanted.get("product_name", "")),
        )
        if live_stock is not None:
            try:
                live_price = check_price.extract_price(
                    fallback_html,
                    reference_price=price_decimal(wanted.get("initial_price")),
                    variant=str(wanted.get("variant", "")),
                    product_name=str(wanted.get("product_name", "")),
                )
            except Exception:  # noqa: BLE001
                live_price = price_decimal(wanted.get("initial_price"))

            if live_price is not None:
                fallback_product = {
                    "title": wanted.get("product_name"),
                    "handle": clean_url.rsplit("/", 1)[-1],
                    "available": live_stock,
                    "variants": [],
                }
                fallback_variant = {
                    "title": wanted.get("variant") or "Default",
                    "sku": wanted.get("sku"),
                    "price": f"{live_price:.2f}",
                    "available": live_stock,
                }
                print(
                    f"Resolved Bambu live stock from rendered page: {wanted['product_name']} "
                    f"| £{live_price:.2f} | available={live_stock}"
                )
                return (
                    synthetic_product_html(fallback_product, fallback_variant, wanted),
                    f"{fallback_source} stock + configured reference price",
                )

        return fallback_html, fallback_source

    return ORIGINAL_FETCH(url, timeout, search_url)


check_price.fetch_html = fetch_with_shopify

if __name__ == "__main__":
    raise SystemExit(check_price.main())

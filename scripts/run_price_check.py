#!/usr/bin/env python3
"""Use Bambu Lab's Shopify JSON data before the generic HTML fallbacks."""

from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
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


def request_json(url: str, timeout: int) -> dict[str, Any] | None:
    response = requests.get(
        url,
        headers={
            "User-Agent": "Price-Tracker/2.2 (+https://github.com/Minecraftman04/Price-Tracker)",
            "Accept": "application/json",
            "Accept-Language": "en-GB,en;q=0.9",
            "Cache-Control": "no-cache",
        },
        timeout=min(max(timeout, 15), 30),
        allow_redirects=False,
    )
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type and not response.text.lstrip().startswith(("{", "[")):
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


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
    payload = request_json(f"{url.rstrip('/')}.json", timeout)
    product = payload.get("product") if payload else None
    if isinstance(product, dict):
        return product

    catalog = load_catalog(timeout)
    if not catalog:
        return None
    ranked = sorted(catalog, key=lambda item: product_score(item, wanted), reverse=True)
    if not ranked or product_score(ranked[0], wanted) < 100:
        return None
    return ranked[0]


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
    available = bool(variant.get("available", True))
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
                        f"{resolved_url} | {variant.get('title')} | £{variant.get('price')}"
                    )
                    return synthetic_product_html(product, variant, wanted), "Bambu Shopify product JSON"
        except Exception as exc:  # noqa: BLE001
            print(f"Bambu Shopify JSON fallback failed for {wanted['product_name']}: {exc}", file=sys.stderr)

    return ORIGINAL_FETCH(url, timeout, search_url)


check_price.fetch_html = fetch_with_shopify

if __name__ == "__main__":
    raise SystemExit(check_price.main())

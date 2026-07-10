#!/usr/bin/env python3
"""Track multiple product prices while preserving the last known value on fetch failures."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
HISTORY_PATH = ROOT / "data" / "price-history.json"
LATEST_PATH = ROOT / "data" / "latest.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def decimal_price(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace("£", "").replace(",", "")
    match = re.search(r"\d+(?:\.\d{1,2})?", text)
    if not match:
        return None
    try:
        price = Decimal(match.group(0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return price if Decimal("1.00") <= price <= Decimal("10000.00") else None


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def _add_candidate(candidates: list[tuple[int, Decimal]], priority: int, value: Any) -> None:
    price = decimal_price(value)
    if price is not None:
        candidates.append((priority, price))


def collect_price_candidates(html: str, variant: str = "", product_name: str = "") -> list[tuple[int, Decimal]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, Decimal]] = []

    for script in soup.find_all("script"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        script_type = str(script.get("type", "")).lower()
        if script_type == "application/ld+json":
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if payload is not None:
                for node in walk_json(payload):
                    currency = str(node.get("priceCurrency", node.get("currency", ""))).upper()
                    if currency and currency != "GBP":
                        continue
                    node_type = str(node.get("@type", "")).lower()
                    for key in ("price", "lowPrice", "highPrice", "amount"):
                        if key in node:
                            _add_candidate(candidates, 100 if node_type in {"offer", "aggregateoffer"} else 92, node[key])

        if "price" in raw.lower() and len(raw) < 5_000_000:
            for match in re.finditer(
                r'(?i)["\'](?:price|salePrice|currentPrice|amount)["\']\s*:\s*["\']?(\d+(?:\.\d{1,2})?)',
                raw,
            ):
                _add_candidate(candidates, 72, match.group(1))

    for selector in (
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        'meta[itemprop="price"]',
    ):
        for tag in soup.select(selector):
            _add_candidate(candidates, 96, tag.get("content"))

    for tag in soup.select('[itemprop="offers"] [itemprop="price"], [itemprop="price"]'):
        _add_candidate(candidates, 90, tag.get("content") or tag.get("value") or tag.get_text(" ", strip=True))

    for tag in soup.select('[data-price], [data-product-price], [data-current-price]'):
        for attribute in ("data-current-price", "data-product-price", "data-price"):
            if tag.get(attribute) is not None:
                _add_candidate(candidates, 86, tag.get(attribute))
                break

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    lower_text = text.lower()
    for match_text, after_priority, around_priority in (
        (variant, 116, 112),
        (product_name, 114, 110),
    ):
        if not match_text:
            continue
        index = lower_text.find(match_text.lower())
        if index >= 0:
            after_window = text[index: index + len(match_text) + 700]
            for raw_price in re.findall(r"£\s*\d[\d,]*(?:\.\d{1,2})?", after_window):
                _add_candidate(candidates, after_priority, raw_price)
            around_window = text[max(0, index - 160): index + len(match_text) + 900]
            for raw_price in re.findall(r"£\s*\d[\d,]*(?:\.\d{1,2})?", around_window):
                _add_candidate(candidates, around_priority, raw_price)

    for match in re.finditer(
        r"((?:£\s*\d[\d,]*\.\d{2}\s*){1,4})(?:\(incl\.?\s*VAT\)|incl\.?\s*VAT)",
        text,
        flags=re.IGNORECASE,
    ):
        prices = re.findall(r"£\s*\d[\d,]*\.\d{2}", match.group(1))
        if prices:
            _add_candidate(candidates, 108, prices[-1])

    for raw_price in re.findall(r"£\s*\d[\d,]*(?:\.\d{1,2})?", text):
        _add_candidate(candidates, 30, raw_price)

    return candidates


def extract_price(
    html: str,
    reference_price: Decimal | None = None,
    variant: str = "",
    product_name: str = "",
) -> Decimal:
    candidates = collect_price_candidates(html, variant, product_name)
    if not candidates:
        raise ValueError("Could not find a plausible GBP product price in the page")

    highest_priority = max(priority for priority, _ in candidates)
    best = [price for priority, price in candidates if priority == highest_priority]
    if reference_price is not None:
        return min(best, key=lambda price: abs(price - reference_price))
    return best[0]


def extract_stock(html: str, variant: str = "", product_name: str = "") -> bool | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in walk_json(payload):
            availability = str(node.get("availability", "")).lower()
            if "instock" in availability:
                return True
            if any(token in availability for token in ("outofstock", "soldout", "discontinued")):
                return False

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()
    scope = text
    for match_text in (variant, product_name):
        if not match_text:
            continue
        index = text.find(match_text.lower())
        if index >= 0:
            scope = text[max(0, index - 300): index + len(match_text) + 900]
            break
    if any(phrase in scope for phrase in ("out of stock", "currently unavailable", "sold out")):
        return False
    if any(phrase in scope for phrase in ("in stock", "add to cart", "add to basket")):
        return True
    return None


def request_html(url: str, timeout: int) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    html = response.text
    lowered = html.lower()
    if len(html) < 1000 or any(marker in lowered for marker in ("just a moment...", "cf-chl-", "access denied")):
        raise RuntimeError("retailer returned a challenge or incomplete product page")
    return html


def reader_html(url: str, timeout: int) -> str:
    response = requests.get(
        f"https://r.jina.ai/{url}",
        headers={"User-Agent": "Price-Tracker/2.1", "X-No-Cache": "true"},
        timeout=max(timeout, 60),
    )
    response.raise_for_status()
    text = response.text
    if len(text) < 500 or "Page not found" in text[:500]:
        raise RuntimeError("rendered response was unexpectedly short or missing")
    return text


def fetch_html(url: str, timeout: int, search_url: str = "") -> tuple[str, str]:
    local_html = os.environ.get("PRICE_TRACKER_HTML_FILE")
    if local_html:
        return Path(local_html).read_text(encoding="utf-8"), "Local test page"

    candidates = [(url, "Live product page")]
    if search_url and search_url != url:
        candidates.append((search_url, "Retailer search fallback"))

    errors: list[str] = []
    for candidate_url, source in candidates:
        try:
            return request_html(candidate_url, timeout), source
        except Exception as exc:  # noqa: BLE001
            errors.append(f"direct {candidate_url}: {exc}")
        for attempt in range(1, 3):
            try:
                return reader_html(candidate_url, timeout), f"{source} via rendered fallback"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"rendered {candidate_url} attempt {attempt}: {exc}")
                if attempt < 2:
                    time.sleep(3)

    raise RuntimeError("; ".join(errors[-4:]))


def set_output(name: str, value: Any) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    rendered = json.dumps(value, separators=(",", ":"), ensure_ascii=False) if isinstance(value, (dict, list)) else (
        str(value).lower() if isinstance(value, bool) else str(value)
    )
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={rendered}\n")
    else:
        print(f"OUTPUT {name}={rendered}")


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None


def hours_since(timestamp: str, now: datetime) -> float:
    previous = parse_timestamp(timestamp)
    return float("inf") if previous is None else (now - previous).total_seconds() / 3600


def latest_product_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(product.get("id")): product
        for product in payload.get("products", [])
        if isinstance(product, dict) and product.get("id")
    }


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    histories: dict[str, list[dict[str, Any]]] = load_json(HISTORY_PATH, {})
    previous_latest = load_json(LATEST_PATH, {})
    previous_products = latest_product_map(previous_latest)

    now = datetime.now(timezone.utc)
    timestamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    currency = config.get("currency", "GBP")
    heartbeat_hours = float(config.get("heartbeat_hours", 24))
    history_limit = int(config.get("max_history_entries_per_product", 2000))
    timeout = int(config.get("request_timeout_seconds", 35))

    products_output: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    any_history_changed = False
    failures = 0

    for product in config.get("products", []):
        product_id = str(product["id"])
        history = list(histories.get(product_id, []))
        previous_record = history[-1] if history else None
        previous_product = previous_products.get(product_id, {})

        reference = decimal_price(
            previous_product.get("price", previous_record.get("price") if previous_record else product.get("initial_price"))
        ) or Decimal(str(product["initial_price"]))
        initial_stock = product.get("initial_in_stock")
        price = reference
        stock = previous_product.get(
            "in_stock",
            previous_record.get("in_stock") if previous_record else initial_stock,
        )
        check_error: str | None = None
        price_source = "Live product page"

        try:
            search_url = str(product.get("search_url", ""))
            if not search_url and product.get("retailer") == "Bambu Lab UK":
                search_url = f"https://uk.store.bambulab.com/search?q={quote_plus(str(product['product_name']))}"
            html, price_source = fetch_html(str(product["product_url"]), timeout, search_url)
            price = extract_price(
                html,
                reference_price=reference,
                variant=str(product.get("variant", "")),
                product_name=str(product.get("product_name", "")),
            )
            fetched_stock = extract_stock(
                html,
                variant=str(product.get("variant", "")),
                product_name=str(product.get("product_name", "")),
            )
            if fetched_stock is not None:
                stock = fetched_stock
        except Exception as exc:  # noqa: BLE001
            failures += 1
            check_error = str(exc)[:280]
            price_source = "Last known price"
            print(f"Warning: {product['product_name']} could not be refreshed: {check_error}", file=sys.stderr)

        previous_price = Decimal(str(previous_record["price"])) if previous_record else None
        previous_stock = previous_record.get("in_stock") if previous_record else None
        price_changed = previous_price is None or price != previous_price
        stock_changed = previous_record is not None and stock != previous_stock
        heartbeat_due = previous_record is None or hours_since(previous_record.get("timestamp", ""), now) >= heartbeat_hours
        error_changed = previous_product.get("check_error") != check_error
        history_changed = price_changed or stock_changed or heartbeat_due
        any_history_changed = any_history_changed or history_changed or error_changed

        reason_parts: list[str] = []
        if previous_record is None:
            reason_parts.append("initial")
        elif price_changed:
            reason_parts.append("price-change")
        if stock_changed:
            reason_parts.append("stock-change")
        if heartbeat_due and not reason_parts:
            reason_parts.append("heartbeat")

        if history_changed:
            history.append(
                {
                    "timestamp": timestamp,
                    "price": float(price),
                    "currency": currency,
                    "in_stock": stock,
                    "reason": ",".join(reason_parts),
                }
            )
            history = history[-history_limit:]
            histories[product_id] = history

        all_prices = [Decimal(str(item["price"])) for item in history] or [price]
        change = price - previous_price if previous_price is not None else None
        change_percent = (
            (change / previous_price * Decimal("100")).quantize(Decimal("0.01"))
            if change is not None and previous_price
            else None
        )
        target = decimal_price(product.get("target_price"))
        dropped = previous_price is not None and price < previous_price
        target_reached = bool(target is not None and price <= target and (previous_price is None or previous_price > target))

        if (dropped and product.get("notify_on_any_drop", True)) or target_reached:
            alerts.append(
                {
                    "product_id": product_id,
                    "product_name": product["product_name"],
                    "product_url": product["product_url"],
                    "current_price": f"{price:.2f}",
                    "previous_price": f"{previous_price:.2f}" if previous_price is not None else "",
                    "drop_amount": f"{(previous_price - price):.2f}" if previous_price is not None else "0.00",
                    "drop_percent": f"{abs(change_percent or Decimal('0')):.2f}",
                    "in_stock": stock,
                    "target_reached": target_reached,
                }
            )

        products_output.append(
            {
                "id": product_id,
                "product_name": product["product_name"],
                "variant": product.get("variant"),
                "product_url": product["product_url"],
                "retailer": product.get("retailer"),
                "sku": product.get("sku"),
                "category": product.get("category"),
                "image_url": product.get("image_url"),
                "currency": currency,
                "currency_symbol": config.get("currency_symbol", "£"),
                "price": float(price),
                "previous_price": float(previous_price) if previous_price is not None else None,
                "change": float(change) if change is not None else None,
                "change_percent": float(change_percent) if change_percent is not None else None,
                "lowest_price": float(min(all_prices)),
                "highest_price": float(max(all_prices)),
                "in_stock": stock,
                "checked_at": timestamp,
                "first_seen_at": history[0]["timestamp"] if history else timestamp,
                "history_count": len(history),
                "target_price": float(target) if target is not None else None,
                "notify_on_any_drop": bool(product.get("notify_on_any_drop", True)),
                "basket_price": product.get("basket_price"),
                "basket_original_price": product.get("basket_original_price"),
                "basket_status": product.get("basket_status", "none"),
                "price_source": price_source,
                "check_error": check_error,
            }
        )

    latest = {
        "generated_at": timestamp,
        "currency": currency,
        "currency_symbol": config.get("currency_symbol", "£"),
        "basket": config.get("basket", {}),
        "product_count": len(products_output),
        "failed_checks": failures,
        "products": products_output,
        "source": "Automated GitHub Actions multi-product check",
    }
    write_json(LATEST_PATH, latest)
    if any_history_changed:
        write_json(HISTORY_PATH, histories)

    set_output("data_changed", any_history_changed)
    set_output("alerts_json", alerts)
    set_output("checked_at", timestamp)
    set_output("product_count", len(products_output))
    set_output("failed_checks", failures)
    set_output("price", f"{sum(Decimal(str(p.get('basket_price') or 0)) for p in products_output if p.get('basket_status') == 'selected'):.2f}")

    print(f"Checked {len(products_output)} products; failures={failures}; data_changed={any_history_changed}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Price check failed: {exc}", file=sys.stderr)
        raise

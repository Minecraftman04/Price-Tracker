#!/usr/bin/env python3
"""Fetch an OcUK product page, extract its current price, and update JSON data."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
HISTORY_PATH = ROOT / "data" / "price-history.json"
LATEST_PATH = ROOT / "data" / "latest.json"


@dataclass(frozen=True)
class ProductSnapshot:
    price: Decimal
    in_stock: bool | None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
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
    if Decimal("5.00") <= price <= Decimal("5000.00"):
        return price
    return None


def walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_json_ld_candidates(soup: BeautifulSoup) -> list[tuple[int, Decimal]]:
    candidates: list[tuple[int, Decimal]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in walk_json(payload):
            node_type = str(node.get("@type", "")).lower()
            currency = str(node.get("priceCurrency", "")).upper()
            if currency and currency != "GBP":
                continue
            if node_type in {"offer", "aggregateoffer"}:
                for key, priority in (("price", 100), ("lowPrice", 95), ("highPrice", 70)):
                    price = decimal_price(node.get(key))
                    if price is not None:
                        candidates.append((priority, price))
    return candidates


def extract_price(html: str) -> Decimal:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, Decimal]] = extract_json_ld_candidates(soup)

    meta_selectors = (
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        'meta[itemprop="price"]',
    )
    for selector in meta_selectors:
        for tag in soup.select(selector):
            price = decimal_price(tag.get("content"))
            if price is not None:
                candidates.append((90, price))

    for tag in soup.select('[itemprop="offers"] [itemprop="price"], [itemprop="price"]'):
        price = decimal_price(tag.get("content") or tag.get("value") or tag.get_text(" ", strip=True))
        if price is not None:
            candidates.append((88, price))

    for tag in soup.select('[data-price], [data-product-price], [data-current-price]'):
        for attribute in ("data-current-price", "data-product-price", "data-price"):
            price = decimal_price(tag.get(attribute))
            if price is not None:
                candidates.append((82, price))
                break

    text = soup.get_text(" ", strip=True)

    # OcUK displays sale pricing as "£old £current (incl. VAT)". The final price
    # before the VAT label is the actual basket price.
    vat_patterns = (
        r"((?:£\s*\d[\d,]*\.\d{2}\s*){1,3})\(incl\.?\s*VAT\)",
        r"((?:£\s*\d[\d,]*\.\d{2}\s*){1,3})incl\.?\s*VAT",
    )
    for pattern in vat_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            prices = re.findall(r"£\s*\d[\d,]*\.\d{2}", match.group(1))
            if prices:
                price = decimal_price(prices[-1])
                if price is not None:
                    candidates.append((80, price))

    if not candidates:
        raise ValueError("Could not find a plausible GBP product price in the page")

    highest_priority = max(priority for priority, _ in candidates)
    best = [price for priority, price in candidates if priority == highest_priority]
    return best[0]


def extract_stock(html: str) -> bool | None:
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
    if any(phrase in text for phrase in ("out of stock", "currently unavailable", "sold out")):
        return False
    if "in stock" in text:
        return True
    return None


def fetch_html(url: str, timeout: int) -> str:
    local_html = os.environ.get("PRICE_TRACKER_HTML_FILE")
    if local_html:
        return Path(local_html).read_text(encoding="utf-8")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    html = response.text
    lowered = html.lower()
    if len(html) < 5000 or any(marker in lowered for marker in ("just a moment...", "cf-chl-", "access denied")):
        raise RuntimeError("Retailer returned a challenge or incomplete page instead of the product page")
    return html


def set_output(name: str, value: Any) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    rendered = str(value).lower() if isinstance(value, bool) else str(value)
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={rendered}\n")
    else:
        print(f"OUTPUT {name}={rendered}")


def hours_since(timestamp: str, now: datetime) -> float:
    try:
        previous = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return float("inf")
    return (now - previous).total_seconds() / 3600


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    history: list[dict[str, Any]] = load_json(HISTORY_PATH, [])
    previous = history[-1] if history else None

    html = fetch_html(config["product_url"], int(config.get("request_timeout_seconds", 35)))
    snapshot = ProductSnapshot(price=extract_price(html), in_stock=extract_stock(html))

    now = datetime.now(timezone.utc)
    timestamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    previous_price = Decimal(str(previous["price"])) if previous else None
    previous_stock = previous.get("in_stock") if previous else None

    dropped = previous_price is not None and snapshot.price < previous_price
    price_changed = previous_price is None or snapshot.price != previous_price
    stock_changed = previous is not None and snapshot.in_stock != previous_stock
    heartbeat_due = previous is None or hours_since(previous.get("timestamp", ""), now) >= float(config.get("heartbeat_hours", 24))
    data_changed = price_changed or stock_changed or heartbeat_due

    target = decimal_price(config.get("target_price"))
    target_reached = bool(
        target is not None
        and snapshot.price <= target
        and (previous_price is None or previous_price > target)
    )

    if data_changed:
        reason_parts: list[str] = []
        if previous is None:
            reason_parts.append("initial")
        if price_changed and previous is not None:
            reason_parts.append("price-change")
        if stock_changed:
            reason_parts.append("stock-change")
        if heartbeat_due and not reason_parts:
            reason_parts.append("heartbeat")

        history.append(
            {
                "timestamp": timestamp,
                "price": float(snapshot.price),
                "currency": config.get("currency", "GBP"),
                "in_stock": snapshot.in_stock,
                "reason": ",".join(reason_parts),
            }
        )
        history = history[-int(config.get("max_history_entries", 2000)) :]

        all_prices = [Decimal(str(item["price"])) for item in history]
        change = snapshot.price - previous_price if previous_price is not None else None
        change_percent = (
            (change / previous_price * Decimal("100")) if change is not None and previous_price else None
        )

        latest = {
            "product_name": config["product_name"],
            "product_url": config["product_url"],
            "retailer": config.get("retailer"),
            "sku": config.get("sku"),
            "currency": config.get("currency", "GBP"),
            "currency_symbol": config.get("currency_symbol", "£"),
            "price": float(snapshot.price),
            "previous_price": float(previous_price) if previous_price is not None else None,
            "change": float(change) if change is not None else None,
            "change_percent": float(change_percent.quantize(Decimal("0.01"))) if change_percent is not None else None,
            "lowest_price": float(min(all_prices)),
            "highest_price": float(max(all_prices)),
            "in_stock": snapshot.in_stock,
            "checked_at": timestamp,
            "first_seen_at": history[0]["timestamp"],
            "history_count": len(history),
            "target_price": float(target) if target is not None else None,
            "notify_on_any_drop": bool(config.get("notify_on_any_drop", True)),
            "source": "Automated GitHub Actions check",
        }
        write_json(HISTORY_PATH, history)
        write_json(LATEST_PATH, latest)

    drop_amount = previous_price - snapshot.price if dropped and previous_price is not None else Decimal("0")
    drop_percent = (
        (drop_amount / previous_price * Decimal("100")).quantize(Decimal("0.01"))
        if dropped and previous_price
        else Decimal("0")
    )

    set_output("data_changed", data_changed)
    set_output("dropped", dropped and bool(config.get("notify_on_any_drop", True)))
    set_output("target_reached", target_reached)
    set_output("price", f"{snapshot.price:.2f}")
    set_output("previous_price", f"{previous_price:.2f}" if previous_price is not None else "")
    set_output("drop_amount", f"{drop_amount:.2f}")
    set_output("drop_percent", f"{drop_percent:.2f}")
    set_output("in_stock", snapshot.in_stock if snapshot.in_stock is not None else "unknown")
    set_output("checked_at", timestamp)

    print(
        f"Checked {config['product_name']}: £{snapshot.price:.2f}, "
        f"stock={snapshot.in_stock}, changed={data_changed}, dropped={dropped}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Price check failed: {exc}", file=sys.stderr)
        raise

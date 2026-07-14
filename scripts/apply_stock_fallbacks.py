#!/usr/bin/env python3
"""Apply explicit product fallbacks only when a live check failed.

The tracker normally trusts live retailer data. Per-product stock and price
fallbacks are used only while that product has a non-empty ``check_error``. As
soon as the live check succeeds again, the normal live result takes precedence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
LATEST_PATH = ROOT / "data" / "latest.json"
HISTORY_PATH = ROOT / "data" / "price-history.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def decimal_price(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("£", "").replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def parse_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def configured_fallback_price(wanted: dict[str, Any], timestamp: str) -> Decimal | None:
    active_price = decimal_price(wanted.get("fallback_price"))
    if active_price is None:
        return None

    expires = parse_timestamp(wanted.get("fallback_price_until"))
    checked_at = parse_timestamp(timestamp)
    if expires is not None and checked_at is not None and checked_at > expires:
        return decimal_price(wanted.get("fallback_price_after"))
    return active_price


def apply_stock_fallbacks(
    config: dict[str, Any],
    latest: dict[str, Any],
    histories: dict[str, list[dict[str, Any]]],
) -> bool:
    configured = {
        str(product.get("id")): product
        for product in config.get("products", [])
        if isinstance(product, dict) and product.get("id")
    }
    timestamp = str(latest.get("generated_at", ""))
    currency = str(latest.get("currency", config.get("currency", "GBP")))
    changed = False

    for product in latest.get("products", []):
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("id", ""))
        wanted = configured.get(product_id, {})

        # Never replace a successful live result. These fallbacks exist only for
        # retailer responses that are currently blocked or incomplete.
        if not product.get("check_error"):
            continue

        stock_fallback = wanted.get("fallback_in_stock")
        price_fallback = configured_fallback_price(wanted, timestamp)
        if not isinstance(stock_fallback, bool) and price_fallback is None:
            continue

        old_price = decimal_price(product.get("price"))
        desired_price = price_fallback if price_fallback is not None else old_price
        old_stock = product.get("in_stock")
        desired_stock = stock_fallback if isinstance(stock_fallback, bool) else old_stock
        if desired_price is None:
            continue

        price_changed = old_price != desired_price
        stock_changed = old_stock != desired_stock

        history = histories.setdefault(product_id, [])
        current_entry = history[-1] if history and history[-1].get("timestamp") == timestamp else None
        previous_entry = (
            history[-2]
            if current_entry is not None and len(history) >= 2
            else history[-1]
            if current_entry is None and history
            else None
        )
        previous_price = decimal_price(previous_entry.get("price")) if previous_entry else old_price

        reason_parts: list[str] = []
        if price_changed:
            reason_parts.append("price-fallback")
        if stock_changed:
            reason_parts.append("stock-fallback")

        if reason_parts:
            entry = {
                "timestamp": timestamp,
                "price": float(desired_price),
                "currency": currency,
                "in_stock": desired_stock,
                "reason": ",".join(reason_parts),
            }
            if current_entry is not None:
                current_entry.update(entry)
            else:
                history.append(entry)
            changed = True

        all_prices = [decimal_price(item.get("price")) for item in history]
        all_prices = [value for value in all_prices if value is not None] or [desired_price]
        price_delta = desired_price - previous_price if previous_price is not None else None
        change_percent = (
            (price_delta / previous_price * Decimal("100")).quantize(Decimal("0.01"))
            if price_delta is not None and previous_price
            else None
        )

        product["price"] = float(desired_price)
        product["previous_price"] = float(previous_price) if previous_price is not None else None
        product["change"] = float(price_delta) if price_delta is not None else None
        product["change_percent"] = float(change_percent) if change_percent is not None else None
        product["lowest_price"] = float(min(all_prices))
        product["highest_price"] = float(max(all_prices))
        product["in_stock"] = desired_stock
        product["history_count"] = len(history)

        if price_fallback is not None:
            product["price_source"] = "Confirmed Bambu storefront price fallback"
            product["fallback_note"] = wanted.get("fallback_price_note")
        if isinstance(stock_fallback, bool):
            product["fallback_stock_note"] = wanted.get("fallback_stock_note")

        if price_changed or stock_changed:
            print(
                f"Applied configured fallback for {product.get('product_name', product_id)}: "
                f"price=£{desired_price:.2f}, in_stock={desired_stock}"
            )

    return changed


def set_data_changed_output(changed: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(f"OUTPUT data_changed={str(changed).lower()}")
        return
    if changed:
        # GitHub Actions uses the final value written for a duplicate output key.
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write("data_changed=true\n")


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    latest = load_json(LATEST_PATH, {})
    histories = load_json(HISTORY_PATH, {})
    changed = apply_stock_fallbacks(config, latest, histories)

    # Always preserve fallback metadata in the deployed working tree. Only actual
    # price/stock/history changes set data_changed and create a repository commit.
    write_json(LATEST_PATH, latest)
    write_json(HISTORY_PATH, histories)
    set_data_changed_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

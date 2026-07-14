#!/usr/bin/env python3
"""Apply explicit stock fallbacks only when a live product check failed.

The tracker normally trusts live retailer data. A per-product ``fallback_in_stock``
value is used only while that product has a non-empty ``check_error``. As soon
as the live check succeeds again, the normal live result takes precedence.
"""

from __future__ import annotations

import json
import os
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
        fallback = wanted.get("fallback_in_stock")

        # Never replace a successful live result. This fallback exists only for
        # retailer responses that are currently blocked or incomplete.
        if not isinstance(fallback, bool) or not product.get("check_error"):
            continue
        if product.get("in_stock") == fallback:
            continue

        product["in_stock"] = fallback
        history = histories.setdefault(product_id, [])
        entry = {
            "timestamp": timestamp,
            "price": product.get("price"),
            "currency": currency,
            "in_stock": fallback,
            "reason": "stock-fallback",
        }
        if not history or history[-1].get("timestamp") != timestamp or history[-1].get("in_stock") != fallback:
            history.append(entry)
        product["history_count"] = len(history)
        changed = True
        print(
            f"Applied configured stock fallback for {product.get('product_name', product_id)}: "
            f"in_stock={fallback}"
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
    if changed:
        write_json(LATEST_PATH, latest)
        write_json(HISTORY_PATH, histories)
    set_data_changed_output(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

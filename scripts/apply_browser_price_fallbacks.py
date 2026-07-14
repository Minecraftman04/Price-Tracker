#!/usr/bin/env python3
"""Refresh blocked Bambu Lab checks with the rendered storefront page.

Bambu's static HTML and Shopify JSON endpoints sometimes omit the client-rendered
sale price. GitHub's Ubuntu runner already includes Chrome, so this fallback loads
only failed Bambu checks in a real headless browser and extracts the visible current
price and stock state. Successful normal checks always remain the first choice.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

import check_price

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
LATEST_PATH = ROOT / "data" / "latest.json"
HISTORY_PATH = ROOT / "data" / "price-history.json"

MONEY_PATTERN = re.compile(
    r"(?:£\s*([0-9][\d,]*(?:\.\d{1,2})?)|([0-9][\d,]*(?:\.\d{1,2})?)\s*GBP)",
    flags=re.IGNORECASE,
)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("£", "").replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def currency_values(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for match in MONEY_PATTERN.finditer(text):
        value = decimal_value(match.group(1) or match.group(2))
        if value is not None:
            values.append(value)
    return values


def plausible_price(value: Decimal, reference: Decimal | None) -> bool:
    if not Decimal("1.00") <= value <= Decimal("10000.00"):
        return False
    if reference is None:
        return True
    return reference * Decimal("0.35") <= value <= reference * Decimal("1.75")


def extract_rendered_current_price(
    html: str,
    *,
    product_name: str,
    reference_price: Decimal | None,
) -> Decimal:
    """Prefer the visible sale/current price over a struck-through old price."""
    soup = BeautifulSoup(html, "html.parser")

    # Price-specific elements are the strongest signal. Exclude common names used
    # for old/compare-at values, and use the first plausible amount in DOM order.
    excluded_markers = ("compare", "original", "old-price", "old_price", "was-price", "rrp", "strike")
    for tag in soup.find_all(True):
        identifier = " ".join(
            str(value)
            for value in (
                tag.get("id", ""),
                " ".join(tag.get("class", [])),
                tag.get("data-testid", ""),
                tag.get("data-test", ""),
                tag.get("aria-label", ""),
            )
            if value
        ).lower()
        if not any(marker in identifier for marker in ("price", "sale", "discount")):
            continue
        if any(marker in identifier for marker in excluded_markers):
            continue
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if not text or len(text) > 300:
            continue
        for value in currency_values(text):
            if plausible_price(value, reference_price):
                return value

    # Remove scripts and hidden templates before considering visible page text.
    for tag in soup.find_all(("script", "style", "noscript", "template", "svg")):
        tag.decompose()
    visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    # On Bambu product pages the current price appears immediately after the title,
    # before the crossed-out compare-at price. This also avoids voucher amounts.
    lower_text = visible_text.lower()
    title_index = lower_text.find(product_name.lower()) if product_name else -1
    windows = []
    if title_index >= 0:
        windows.append(visible_text[title_index : title_index + len(product_name) + 1400])
    windows.append(visible_text)

    for window in windows:
        for value in currency_values(window):
            if plausible_price(value, reference_price):
                return value

    raise ValueError("Could not find the visible current GBP price in the rendered Bambu page")


def chrome_executable() -> str:
    configured = os.environ.get("CHROME_BIN")
    candidates = [configured] if configured else []
    candidates.extend(("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("No Chrome or Chromium executable is available")


def render_page(url: str, timeout: int) -> str:
    browser = chrome_executable()
    with tempfile.TemporaryDirectory(prefix="price-tracker-chrome-") as profile:
        command = [
            browser,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-features=Translate,MediaRouter,OptimizationHints",
            "--disable-sync",
            "--disable-blink-features=AutomationControlled",
            "--hide-scrollbars",
            "--lang=en-GB",
            "--window-size=1920,1080",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=20000",
            f"--user-data-dir={profile}",
            "--dump-dom",
            url,
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(60, timeout + 25),
            check=False,
            env={**os.environ, "LANG": "en_GB.UTF-8"},
        )

    html = completed.stdout
    if completed.returncode != 0 or len(html) < 1000:
        detail = re.sub(r"\s+", " ", completed.stderr)[-400:]
        raise RuntimeError(f"Headless Chrome did not return a complete page: {detail}")
    lowered = html.lower()
    if any(marker in lowered for marker in ("just a moment...", "cf-chl-", "access denied")):
        raise RuntimeError("Headless Chrome received a retailer challenge page")
    return html


def read_output_json(name: str, default: Any) -> Any:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path or not Path(output_path).exists():
        return default
    prefix = f"{name}="
    for line in reversed(Path(output_path).read_text(encoding="utf-8").splitlines()):
        if line.startswith(prefix):
            try:
                return json.loads(line[len(prefix) :])
            except json.JSONDecodeError:
                return default
    return default


def set_output(name: str, value: Any) -> None:
    rendered = json.dumps(value, separators=(",", ":"), ensure_ascii=False) if isinstance(value, (dict, list)) else (
        str(value).lower() if isinstance(value, bool) else str(value)
    )
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={rendered}\n")
    else:
        print(f"OUTPUT {name}={rendered}")


def alert_for_change(
    product: dict[str, Any],
    configured: dict[str, Any],
    previous_price: Decimal | None,
    current_price: Decimal,
) -> dict[str, Any] | None:
    target = decimal_value(configured.get("target_price"))
    dropped = previous_price is not None and current_price < previous_price
    target_reached = bool(
        target is not None
        and current_price <= target
        and (previous_price is None or previous_price > target)
    )
    if not ((dropped and configured.get("notify_on_any_drop", True)) or target_reached):
        return None
    drop = previous_price - current_price if previous_price is not None else Decimal("0")
    drop_percent = (
        (drop / previous_price * Decimal("100")).quantize(Decimal("0.01"))
        if previous_price
        else Decimal("0")
    )
    return {
        "product_id": product.get("id"),
        "product_name": product.get("product_name"),
        "product_url": product.get("product_url"),
        "current_price": f"{current_price:.2f}",
        "previous_price": f"{previous_price:.2f}" if previous_price is not None else "",
        "drop_amount": f"{drop:.2f}",
        "drop_percent": f"{abs(drop_percent):.2f}",
        "in_stock": product.get("in_stock"),
        "target_reached": target_reached,
    }


def apply_browser_price_fallbacks(
    config: dict[str, Any],
    latest: dict[str, Any],
    histories: dict[str, list[dict[str, Any]]],
    *,
    renderer: Callable[[str, int], str] = render_page,
) -> tuple[bool, list[dict[str, Any]]]:
    configured = {
        str(product.get("id")): product
        for product in config.get("products", [])
        if isinstance(product, dict) and product.get("id")
    }
    timeout = int(config.get("request_timeout_seconds", 35))
    timestamp = str(latest.get("generated_at", ""))
    currency = str(latest.get("currency", config.get("currency", "GBP")))
    changed = False
    new_alerts: list[dict[str, Any]] = []

    for product in latest.get("products", []):
        if not isinstance(product, dict) or not product.get("check_error"):
            continue
        if product.get("retailer") != "Bambu Lab UK":
            continue

        product_id = str(product.get("id", ""))
        wanted = configured.get(product_id, {})
        reference = decimal_value(product.get("price")) or decimal_value(wanted.get("initial_price"))
        try:
            html = renderer(str(product.get("product_url", "")), timeout)
            current_price = extract_rendered_current_price(
                html,
                product_name=str(product.get("product_name", "")),
                reference_price=reference,
            )
            rendered_stock = check_price.extract_stock(
                html,
                variant=str(product.get("variant", "")),
                product_name=str(product.get("product_name", "")),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Bambu browser fallback failed for {product.get('product_name', product_id)}: {exc}")
            continue

        history = histories.setdefault(product_id, [])
        current_entry = history[-1] if history and history[-1].get("timestamp") == timestamp else None
        previous_entry = (
            history[-2]
            if current_entry is not None and len(history) >= 2
            else history[-1]
            if current_entry is None and history
            else None
        )
        previous_price = decimal_value(previous_entry.get("price")) if previous_entry else decimal_value(product.get("previous_price"))
        previous_stock = previous_entry.get("in_stock") if previous_entry else product.get("in_stock")
        current_stock = rendered_stock if rendered_stock is not None else product.get("in_stock")

        price_changed = previous_price is None or current_price != previous_price
        stock_changed = previous_entry is not None and current_stock != previous_stock
        if current_entry is not None:
            current_entry.update(
                {
                    "price": float(current_price),
                    "currency": currency,
                    "in_stock": current_stock,
                    "reason": ",".join(
                        part
                        for part in (
                            "price-change" if price_changed else "",
                            "stock-change" if stock_changed else "",
                            "browser-live",
                        )
                        if part
                    ),
                }
            )
        elif price_changed or stock_changed:
            history.append(
                {
                    "timestamp": timestamp,
                    "price": float(current_price),
                    "currency": currency,
                    "in_stock": current_stock,
                    "reason": ",".join(
                        part
                        for part in (
                            "price-change" if price_changed else "",
                            "stock-change" if stock_changed else "",
                            "browser-live",
                        )
                        if part
                    ),
                }
            )

        all_prices = [decimal_value(entry.get("price")) for entry in history]
        all_prices = [value for value in all_prices if value is not None] or [current_price]
        change = current_price - previous_price if previous_price is not None else None
        change_percent = (
            (change / previous_price * Decimal("100")).quantize(Decimal("0.01"))
            if change is not None and previous_price
            else None
        )

        product.update(
            {
                "price": float(current_price),
                "previous_price": float(previous_price) if previous_price is not None else None,
                "change": float(change) if change is not None else None,
                "change_percent": float(change_percent) if change_percent is not None else None,
                "lowest_price": float(min(all_prices)),
                "highest_price": float(max(all_prices)),
                "in_stock": current_stock,
                "history_count": len(history),
                "price_source": "Live Bambu product page via headless Chrome",
                "check_error": None,
            }
        )
        changed = True
        print(
            f"Resolved rendered Bambu page: {product.get('product_name', product_id)} "
            f"| £{current_price:.2f} | available={current_stock}"
        )

        alert = alert_for_change(product, wanted, previous_price, current_price)
        if alert is not None:
            new_alerts.append(alert)

    latest["failed_checks"] = sum(
        1
        for product in latest.get("products", [])
        if isinstance(product, dict) and product.get("check_error")
    )
    return changed, new_alerts


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    latest = load_json(LATEST_PATH, {})
    histories = load_json(HISTORY_PATH, {})
    changed, new_alerts = apply_browser_price_fallbacks(config, latest, histories)

    if changed:
        write_json(LATEST_PATH, latest)
        write_json(HISTORY_PATH, histories)

    existing_alerts = read_output_json("alerts_json", [])
    if not isinstance(existing_alerts, list):
        existing_alerts = []
    existing_ids = {str(item.get("product_id")) for item in existing_alerts if isinstance(item, dict)}
    merged_alerts = existing_alerts + [
        alert for alert in new_alerts if str(alert.get("product_id")) not in existing_ids
    ]

    if changed:
        set_output("data_changed", True)
        set_output("failed_checks", latest.get("failed_checks", 0))
    if new_alerts:
        set_output("alerts_json", merged_alerts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

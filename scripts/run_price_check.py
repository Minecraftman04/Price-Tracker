#!/usr/bin/env python3
"""Run the normal price checker, falling back to a rendered page if blocked."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_price.py"
CONFIG_PATH = ROOT / "config.json"


def run_checker(extra_environment: dict[str, str] | None = None) -> int:
    environment = os.environ.copy()
    if extra_environment:
        environment.update(extra_environment)

    completed = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    return completed.returncode


def fetch_reader_copy(product_url: str, timeout: int, expected_sku: str) -> str:
    """Fetch a browser-rendered text copy through Jina Reader.

    OcUK can occasionally return an anti-bot challenge to GitHub-hosted runners.
    Reader is used only after the direct request has failed.
    """

    reader_url = f"https://r.jina.ai/{product_url}"
    headers = {
        "Accept": "text/plain; charset=utf-8",
        "User-Agent": "Price-Tracker/1.0 (+https://github.com/Minecraftman04/Price-Tracker)",
        "X-No-Cache": "true",
    }
    errors: list[str] = []

    for attempt in range(1, 4):
        try:
            response = requests.get(
                reader_url,
                headers=headers,
                timeout=max(timeout, 60),
                allow_redirects=True,
            )
            response.raise_for_status()
            text = response.text
            lowered = text.lower()

            if len(text) < 1000:
                raise RuntimeError("rendered response was unexpectedly short")
            if expected_sku and expected_sku.lower() not in lowered:
                raise RuntimeError(f"rendered response did not contain SKU {expected_sku}")
            if "£" not in text or "incl. vat" not in lowered:
                raise RuntimeError("rendered response did not contain the expected GBP VAT price")

            return text
        except Exception as exc:  # noqa: BLE001 - aggregate retry diagnostics
            errors.append(f"attempt {attempt}: {exc}")
            if attempt < 3:
                time.sleep(attempt * 5)

    raise RuntimeError("Reader fallback failed; " + "; ".join(errors))


def main() -> int:
    direct_result = run_checker()
    if direct_result == 0:
        return 0

    print(
        "Direct retailer request failed; retrying with a browser-rendered fallback.",
        file=sys.stderr,
    )

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    product_url = str(config["product_url"])
    expected_sku = str(config.get("sku", ""))
    timeout = int(config.get("request_timeout_seconds", 35))
    rendered_page = fetch_reader_copy(product_url, timeout, expected_sku)

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as temporary:
            temporary.write(rendered_page)
            temporary_path = temporary.name

        return run_checker({"PRICE_TRACKER_HTML_FILE": temporary_path})
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())

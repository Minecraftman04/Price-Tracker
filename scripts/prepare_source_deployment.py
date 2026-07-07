#!/usr/bin/env python3
"""Prepare workflow outputs for a source-only Pages deployment."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST_PATH = ROOT / "data" / "latest.json"


def main() -> int:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise RuntimeError("GITHUB_OUTPUT is not available")

    latest = json.loads(LATEST_PATH.read_text(encoding="utf-8"))
    previous_price = latest.get("previous_price")
    stock = latest.get("in_stock")

    outputs = {
        "data_changed": "false",
        "dropped": "false",
        "target_reached": "false",
        "price": f"{float(latest['price']):.2f}",
        "previous_price": "" if previous_price is None else f"{float(previous_price):.2f}",
        "drop_amount": "0.00",
        "drop_percent": "0.00",
        "in_stock": "unknown" if stock is None else str(stock).lower(),
        "checked_at": str(latest["checked_at"]),
    }

    with Path(output_path).open("a", encoding="utf-8") as handle:
        for name, value in outputs.items():
            handle.write(f"{name}={value}\n")

    print("Source push: deploying the stored tracker state without an extra retailer request.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

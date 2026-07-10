# Basket Price Tracker

A free GitHub Actions price tracker for a Bambu Lab UK basket plus the repository’s original Overclockers UK RAM product.

## Tracked Bambu basket

The uploaded basket snapshot from **10 July 2026** contains:

- Bambu Lab X2D — X2D AMS Combo
- Bambu Hotend — Standard Flow, X2D, 0.2 mm stainless steel
- Tungsten Carbide Hotend — High Flow, X2D, 0.4 mm
- PLA Basic — Black (10101), filament with spool, 1 kg
- Vision Encoder — X2D
- Filament Track Switch — X2D
- CyberBrick Time-lapse Kit — 1500 mm 6-pin cable, ZL021
- Mag-Alloy Scraper
- TPU Feed Assist Module — saved and tracked even though it was out of stock

The eight purchasable items total **£1,001.59** in the uploaded basket. Their displayed original prices total **£1,043.93**, a snapshot saving of **£42.34**. The £45.99 TPU Feed Assist Module is shown separately because it was out of stock and excluded from the purchasable subtotal.

## Website

`https://minecraftman04.github.io/Price-Tracker/`

The site shows:

- the uploaded basket price separately from the latest store-page price;
- all tracked products in one responsive dashboard;
- per-product stock, lowest/highest price and history;
- warnings when a retailer blocks a live check, while retaining the last known price;
- GitHub issue alerts for genuine product-price drops.

## Automation

`.github/workflows/track-price.yml` checks each product independently. A failure on one retailer page does not stop the remaining products or the Pages deployment.

The tracker runs every five minutes but records a heartbeat row only when the configured 15-minute window is due. Product data is stored in:

- `data/latest.json`
- `data/price-history.json`
- `data/deployment-status.json`

## Configuration

Products and basket snapshot values are defined in `config.json`. Each product supports:

- `initial_price` and `initial_in_stock`
- `basket_price`, `basket_original_price` and `basket_status`
- `target_price`
- `notify_on_any_drop`
- a variant description used to select the most relevant price when a product page contains several variants.

## Local validation

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/check_price.py
```

Retailer HTML can change and basket discounts can depend on the complete bundle. Always confirm the final checkout total before buying.

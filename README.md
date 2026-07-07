# Overclockers UK Price Tracker

A free, automated price tracker for:

**Corsair Vengeance RGB EXPO 32GB (2x16GB) DDR5-6000 CL30**  
OcUK SKU: `MY-4DU-CS`

The tracker checks the product page every 15 minutes, records price/stock changes, displays a price-history website, and creates a GitHub issue assigned to the repository owner whenever the price drops.

## Website

The tracker is available at:

`https://minecraftman04.github.io/Price-Tracker/`

The GitHub Pages website is redeployed after every successful 15-minute check, so its latest-check timestamp stays current even when the price has not changed.

## One-time setup

1. Open **Settings → Pages** in this repository.
2. Under **Build and deployment**, select **GitHub Actions** as the source.
3. Open **Actions → Track product price** and choose **Run workflow** for an immediate first automated check and deployment.
4. Make sure GitHub notifications for assigned issues are enabled. The price-drop issue is assigned to `Minecraftman04`, so it can arrive by GitHub email and/or the GitHub mobile app according to account notification settings.

## Alert behaviour

The default in `config.json` is:

```json
"notify_on_any_drop": true,
"target_price": null
```

This creates one issue when the current price becomes lower than the previous recorded price. It does not repeatedly alert while the price remains unchanged.

To also use a target, set a number such as:

```json
"target_price": 149.99
```

## How data is stored

- `data/latest.json` contains the latest recorded state.
- `data/price-history.json` contains price history.
- A history record is added on a price/stock change, or once every 24 hours as a heartbeat.
- The website is still refreshed every 15 minutes, but avoiding a commit for every unchanged check keeps the repository history manageable.

## Local test

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/check_price.py
```

## Notes

Retailer HTML can change. The parser checks structured product data, price metadata, microdata, data attributes, and OcUK's visible VAT price pattern. Parser tests run before every live check so obvious regressions fail safely instead of storing a random finance price.

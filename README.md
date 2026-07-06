# Overclockers UK Price Tracker

A free, automated price tracker for:

**Corsair Vengeance RGB EXPO 32GB (2x16GB) DDR5-6000 CL30**  
OcUK SKU: `MY-4DU-CS`

The tracker checks the product page hourly, records price/stock changes, displays a price-history website, and creates a GitHub issue assigned to the repository owner whenever the price drops.

## Website

After GitHub Pages is enabled, the tracker is available at:

`https://minecraftman04.github.io/Price-Tracker/`

## One-time setup

1. Open **Settings → Pages** in this repository.
2. Under **Build and deployment**, select **GitHub Actions** as the source.
3. Open **Actions → Track product price** and choose **Run workflow** for an immediate first automated check.
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
- A record is added on a price/stock change, or once every 24 hours as a heartbeat.
- The GitHub Action still checks hourly, but avoiding hourly commits keeps the repository history manageable.

## Local test

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/check_price.py
```

## Notes

Retailer HTML can change. The parser checks structured product data, price metadata, microdata, data attributes, and OcUK's visible VAT price pattern. Parser tests run before every live check so obvious regressions fail safely instead of storing a random finance price.

# Market Terminal

Personal market dashboard. Rates, credit spreads, equities, global overnight, FX/commodities, macro, headlines, watchlist — every number with day change, YTD, and percentile context. Snapshots every 30 minutes via GitHub Actions. Installs on your phone as an app. Costs $0.

Open `index.html` locally right now to preview the layout — it ships with clearly-badged sample data.

## One-time setup (~10 minutes)

1. **Get a free FRED API key.** https://fred.stlouisfed.org/docs/api/api_key.html — instant, no card.
2. **Create a new public GitHub repo** (e.g. `terminal`) and upload everything in this folder, keeping the structure (including the `.github` and `.nojekyll` files — enable "show hidden files" if uploading by drag-and-drop, or push with git).
3. **Add the key as a secret.** Repo → Settings → Secrets and variables → Actions → New repository secret → Name: `FRED_API_KEY`, Value: your key.
4. **Run the first fetch.** Actions tab → enable workflows if prompted → "Update market data" → Run workflow. It commits a fresh `data.json` (~1 min).
5. **Turn on GitHub Pages.** Settings → Pages → Source: "Deploy from a branch" → Branch: `main`, folder `/ (root)` → Save. Your dashboard is live at `https://YOURNAME.github.io/terminal/` a minute later.
6. **Install on your phone.**
   - iPhone: open the URL in Safari → Share → **Add to Home Screen**.
   - Android: open in Chrome → menu → **Install app**.

Done. From here it updates itself: every 30 min during US market hours, hourly overnight, every 4h on weekends.

## The four tabs

- **Dashboard** — the numbers to know cold: 10Y, Fed funds, S&P, VIX, HY spread, dollar. Plus the curve, the next scheduled event, and top headlines. This is the every-morning tab.
- **Daily** — full detail: rates, credit spreads, all indices with 200-day trend flags, sectors, overnight global, FX/commodities/crypto, watchlist, sentiment, all headlines.
- **Weekly** — the week in equities (5-day and 1-month), the J.P. Morgan Weekly Market Recap up top, loan and credit markets (BSL, senior loans, BDCs/private credit, HY, IG, EM, long Treasuries), jobless claims, mortgage rate, Fed balance sheet, crude inventories, and three weeks of calendar.
- **Quarterly** — the long view: 10Y yields since 1980, HY spreads since 1997, unemployment since 1970, CPI since 1971, each with a percentile against its own history. Plus where the economy stands and structural indicators.

Tabs are hash-linked (`#weekly`), so you can bookmark one directly.

## Daily use

- **Regime strip** (top): the one-line state of the tape, on every tab.
- Tap any ⓘ for the field-guide explainer — what the number is and how to read it.
- **SAMPLE / STALE badges** in the header tell you if you're looking at placeholder or old data.
- The ⚠ footer lists any source that failed this snapshot (the panel just shows last-good data).

## Editing (all from your phone, no code)

Open `config.json` on github.com → pencil icon → commit. You can change:

- `watchlist` / `earnings_tickers` — any Yahoo Finance symbols
- `reading_rail` — your links, grouped by cadence
- `field_guide` — the explainer text
- `fomc_dates` — **update each December** from the Fed's published calendar (the one recurring 2-minute chore)

## Maintenance notes

- **If data stops updating:** GitHub pauses scheduled workflows on repos with no activity for ~60 days. Actions tab → re-enable → Run workflow. (Normally the bot's own commits keep it alive.)
- **Yahoo Finance** is an unofficial source and occasionally breaks; you'll see it in the ⚠ footer and those panels go stale for a day or two until the `yfinance` library patches. FRED (rates/credit/macro) is official and rock-solid.
- **Public repo = public page.** Only market data and your watchlist tickers are visible. Don't put anything sensitive in `config.json`.
- Your history accrues in `history/daily.csv` — one row per day of every key metric, forever.

## Layout of this repo

```
index.html                    the dashboard (single file, no build step)
config.json                   everything you'll ever edit
data.json                     latest snapshot (written by the Action)
history/daily.csv             your growing archive
scripts/fetch_data.py         FRED + Yahoo + RSS + Fear&Greed fetcher
.github/workflows/update.yml  the 30-min schedule
guilloche.svg                 background engraving (must be uploaded with the rest)
manifest.json, sw.js, icons/  PWA install + offline shell
```

#!/usr/bin/env python3
"""
Market Terminal data fetcher.
FRED + Yahoo Finance + RSS + CNN Fear & Greed -> data.json, plus a daily row in history/daily.csv.
Every source is wrapped independently: a failure degrades one panel, never the page.
"""

import csv
import json
import os
import sys
import datetime as dt
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (personal market dashboard; github actions)"}
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
TODAY = dt.date.today()
ERRORS: list[str] = []
CONFIG = json.loads((ROOT / "config.json").read_text())


def log_err(source, exc):
    msg = f"{source}: {type(exc).__name__}: {str(exc)[:110]}"
    print("WARN", msg, file=sys.stderr)
    ERRORS.append(msg)


def downsample(values, n=60):
    if not values:
        return []
    if len(values) <= n:
        return [round(v, 4) for v in values]
    step = (len(values) - 1) / (n - 1)
    return [round(values[int(round(i * step))], 4) for i in range(n)]


def pct_rank(history, value):
    if not history:
        return 50
    return int(round(100 * sum(1 for v in history if v <= value) / len(history)))


# ------------------------------------------------------------------ FRED

def fred_obs(series_id, start):
    r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": series_id, "api_key": FRED_KEY, "file_type": "json",
                             "observation_start": start},
                     headers=UA, timeout=30)
    r.raise_for_status()
    return [(dt.date.fromisoformat(o["date"]), float(o["value"]))
            for o in r.json().get("observations", []) if o["value"] not in (".", "", None)]


def value_near(obs, target):
    return min(obs, key=lambda p: abs((p[0] - target).days))[1] if obs else None


def fred_next_release(release_id):
    r = requests.get("https://api.stlouisfed.org/fred/release/dates",
                     params={"release_id": release_id, "api_key": FRED_KEY, "file_type": "json",
                             "include_release_dates_with_no_data": "true",
                             "realtime_start": TODAY.isoformat(), "realtime_end": "9999-12-31",
                             "sort_order": "asc", "limit": 10},
                     headers=UA, timeout=30)
    r.raise_for_status()
    for d in r.json().get("release_dates", []):
        if d["date"] >= TODAY.isoformat():
            return d["date"]
    return None


def require_key():
    if not FRED_KEY:
        raise RuntimeError("FRED_API_KEY secret is not set")


def build_rates_and_credit(data):
    require_key()
    s2 = (TODAY - dt.timedelta(days=740)).isoformat()

    curve, curve_1m, curve_1y, ten_obs = {}, {}, {}, None
    for label, sid in {"3M": "DGS3MO", "2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"}.items():
        obs = fred_obs(sid, s2)
        if not obs:
            continue
        curve[label] = round(obs[-1][1], 2)
        curve_1m[label] = round(value_near(obs, TODAY - dt.timedelta(days=30)), 2)
        curve_1y[label] = round(value_near(obs, TODAY - dt.timedelta(days=365)), 2)
        if label == "10Y":
            ten_obs = obs

    ten = {}
    if ten_obs:
        v = [x for _, x in ten_obs]
        ten = {"value": round(v[-1], 2),
               "chg_1d": round(v[-1] - v[-2], 2) if len(v) > 1 else 0,
               "chg_1m": round(v[-1] - (value_near(ten_obs, TODAY - dt.timedelta(days=30)) or v[-1]), 2),
               "spark": downsample(v[-260:])}

    spreads = {}
    for key, sid in {"2s10s": "T10Y2Y", "3m10y": "T10Y3M"}.items():
        obs = fred_obs(sid, s2)
        if obs:
            v = [x for _, x in obs]
            spreads[key] = {"bps": int(round(v[-1] * 100)),
                            "spark": downsample([round(x * 100) for x in v[-260:]])}

    fed = {}
    for key, sid in {"upper": "DFEDTARU", "lower": "DFEDTARL", "sofr": "SOFR"}.items():
        obs = fred_obs(sid, (TODAY - dt.timedelta(days=40)).isoformat())
        if obs:
            fed[key] = round(obs[-1][1], 2)

    be = {}
    for key, sid in {"5Y": "T5YIE", "10Y": "T10YIE"}.items():
        obs = fred_obs(sid, (TODAY - dt.timedelta(days=40)).isoformat())
        if obs:
            be[key] = round(obs[-1][1], 2)

    data["rates"] = {"curve": curve, "curve_1m": curve_1m, "curve_1y": curve_1y,
                     "ten_year": ten, "spreads": spreads, "fed": fed, "breakevens": be}

    credit = {}
    for key, sid in {"IG": "BAMLC0A0CM", "HY": "BAMLH0A0HYM2", "CCC": "BAMLH0A3HYC"}.items():
        obs = fred_obs(sid, "2000-01-01")
        if not obs:
            continue
        v = [x * 100 for _, x in obs]
        credit[key] = {"bps": int(round(v[-1])),
                       "chg_1d": int(round(v[-1] - v[-2])) if len(v) > 1 else 0,
                       "chg_1m": int(round(v[-1] - (value_near(obs, TODAY - dt.timedelta(days=30)) * 100))),
                       "pctile": pct_rank(v, v[-1]),
                       "spark": downsample([round(x) for x in v[-260:]]),
                       "spark_long": downsample([round(x) for x in v], 120)}
    if "HY" in credit and "IG" in credit:
        credit["hy_minus_ig"] = credit["HY"]["bps"] - credit["IG"]["bps"]
    data["credit"] = credit


def build_macro(data):
    require_key()
    start = (TODAY - dt.timedelta(days=6 * 365)).isoformat()
    m = {}

    def yoy(sid):
        obs = fred_obs(sid, start)
        if len(obs) < 13:
            return None
        return round((obs[-1][1] / obs[-13][1] - 1) * 100, 1), obs[-1][0].isoformat()

    for key, sid in {"cpi": "CPIAUCSL", "core_cpi": "CPILFESL",
                     "core_pce": "PCEPILFE", "case_shiller": "CSUSHPINSA"}.items():
        try:
            r = yoy(sid)
            if r:
                m[key] = {"yoy": r[0], "asof": r[1]}
        except Exception as e:
            log_err(f"fred:{sid}", e)

    simple = {"unrate": ("UNRATE", "value"), "gdp": ("A191RL1Q225SBEA", "qoq_saar")}
    for key, (sid, field) in simple.items():
        try:
            obs = fred_obs(sid, start)
            if obs:
                m[key] = {field: round(obs[-1][1], 1), "asof": obs[-1][0].isoformat()}
        except Exception as e:
            log_err(f"fred:{sid}", e)

    try:
        obs = fred_obs("PAYEMS", start)
        if len(obs) > 1:
            m["nfp"] = {"chg_k": int(round(obs[-1][1] - obs[-2][1])), "asof": obs[-1][0].isoformat()}
    except Exception as e:
        log_err("fred:PAYEMS", e)

    try:
        obs = fred_obs("SAHMREALTIME", start)
        if obs:
            m["sahm"] = {"value": round(obs[-1][1], 2), "triggered": obs[-1][1] >= 0.5,
                         "asof": obs[-1][0].isoformat()}
    except Exception as e:
        log_err("fred:SAHM", e)

    try:
        obs = fred_obs("MORTGAGE30US", (TODAY - dt.timedelta(days=400)).isoformat())
        if obs:
            v = [x for _, x in obs]
            m["mortgage30"] = {"value": round(v[-1], 2),
                               "chg_wk": round(v[-1] - v[-2], 2) if len(v) > 1 else 0,
                               "asof": obs[-1][0].isoformat(), "spark": downsample(v)}
    except Exception as e:
        log_err("fred:MORTGAGE30US", e)

    rel = []
    for name, rid in {"CPI": 10, "Jobs report": 50, "GDP": 53, "PCE / income": 54}.items():
        try:
            d = fred_next_release(rid)
            if d:
                rel.append({"name": name, "date": d})
        except Exception as e:
            log_err(f"fred:release{rid}", e)
    m["next_releases"] = sorted(rel, key=lambda r: r["date"])
    data["macro"] = m


def build_weekly_fred(data):
    require_key()
    start = (TODAY - dt.timedelta(days=800)).isoformat()
    w = {}

    def series(sid, scale=1.0, digits=1):
        obs = fred_obs(sid, start)
        if not obs:
            return None
        v = [x * scale for _, x in obs]
        prev = v[-2] if len(v) > 1 else v[-1]
        return {"value": round(v[-1], digits), "chg": round(v[-1] - prev, digits),
                "asof": obs[-1][0].isoformat(), "spark": downsample(v[-104:])}

    for key, (sid, scale, dg) in {
        "claims": ("ICSA", 0.001, 0),            # thousands
        "continuing": ("CCSA", 0.000001, 2),     # millions
        "fed_balance": ("WALCL", 0.000001, 2),   # $ trillions
    }.items():
        try:
            r = series(sid, scale, dg)
            if r:
                w[key] = r
        except Exception as e:
            log_err(f"fred:{sid}", e)

    try:
        obs = fred_obs("ICSA", start)
        if len(obs) >= 4:
            w["claims_4wk"] = round(sum(x for _, x in obs[-4:]) / 4 / 1000)
    except Exception as e:
        log_err("fred:ICSA4", e)

    data["weekly"] = w


def build_quarterly(data):
    require_key()
    q = {"stats": [], "longrun": {}}

    def add(key, label, sid, mode, unit, digits=1, start="2000-01-01"):
        try:
            obs = fred_obs(sid, start)
            if not obs:
                return
            v = [x for _, x in obs]
            if mode == "yoy":
                per = {"M": 12, "Q": 4}.get("Q" if len(v) < 200 else "M", 12)
                if len(v) <= per:
                    return
                val = (v[-1] / v[-1 - per] - 1) * 100
            else:
                val = v[-1]
            q["stats"].append({"key": key, "label": label, "value": round(val, digits),
                               "unit": unit, "asof": obs[-1][0].isoformat(),
                               "spark": downsample(v[-80:], 40)})
        except Exception as e:
            log_err(f"fred:{sid}", e)

    add("corp_profits", "Corporate profits", "CP", "yoy", "% YoY")
    add("debt_gdp", "Federal debt / GDP", "GFDEGDQ188S", "level", "%")
    add("m2", "M2 money supply", "M2SL", "yoy", "% YoY")
    add("savings", "Personal savings rate", "PSAVERT", "level", "%")
    add("umcsent", "Consumer sentiment", "UMCSENT", "level", "index")
    add("indpro", "Industrial production", "INDPRO", "yoy", "% YoY")
    add("houst", "Housing starts", "HOUST", "level", "K SAAR", 0)
    add("retail", "Retail sales", "RSAFS", "yoy", "% YoY")

    longrun = {"dgs10": ("DGS10", "1980-01-01"), "hy": ("BAMLH0A0HYM2", "1997-01-01"),
               "unrate": ("UNRATE", "1970-01-01")}
    for key, (sid, start) in longrun.items():
        try:
            obs = fred_obs(sid, start)
            if obs:
                v = [x * (100 if key == "hy" else 1) for _, x in obs]
                q["longrun"][key] = {"spark": downsample(v, 150),
                                     "last": round(v[-1], 2),
                                     "min": round(min(v), 2), "max": round(max(v), 2),
                                     "pctile": pct_rank(v, v[-1]),
                                     "since": obs[0][0].year}
        except Exception as e:
            log_err(f"fred:long:{sid}", e)

    try:
        obs = fred_obs("CPIAUCSL", "1970-01-01")
        if len(obs) > 13:
            v = [x for _, x in obs]
            yoy = [(v[i] / v[i - 12] - 1) * 100 for i in range(12, len(v))]
            q["longrun"]["cpi"] = {"spark": downsample(yoy, 150), "last": round(yoy[-1], 1),
                                   "min": round(min(yoy), 1), "max": round(max(yoy), 1),
                                   "pctile": pct_rank(yoy, yoy[-1]), "since": obs[12][0].year}
    except Exception as e:
        log_err("fred:long:CPI", e)

    data["quarterly"] = q


# ------------------------------------------------------------------ Yahoo

INDICES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow"), ("^RUT", "Russell 2000")]
SECTORS = [("XLK", "Tech"), ("XLF", "Financials"), ("XLE", "Energy"), ("XLV", "Health"),
           ("XLY", "Discretionary"), ("XLP", "Staples"), ("XLI", "Industrials"),
           ("XLB", "Materials"), ("XLU", "Utilities"), ("XLRE", "Real Estate"), ("XLC", "Comms")]
GLOBAL = [("^N225", "Nikkei 225"), ("^HSI", "Hang Seng"), ("^GDAXI", "DAX"),
          ("^FTSE", "FTSE 100"), ("^STOXX50E", "Euro Stoxx 50")]
FXC = [("DX-Y.NYB", "Dollar (DXY)"), ("EURUSD=X", "EUR/USD"), ("JPY=X", "USD/JPY"),
       ("CL=F", "WTI Crude"), ("GC=F", "Gold"), ("HG=F", "Copper"), ("BTC-USD", "Bitcoin")]
CREDIT_ETFS = [("BKLN", "Leveraged loans (BSL)"), ("SRLN", "Senior loans, active"),
               ("BIZD", "BDCs / private credit"), ("HYG", "High yield bonds"),
               ("LQD", "Investment grade bonds"), ("EMB", "EM sovereign debt"),
               ("TLT", "Long Treasuries (20y+)")]


def build_yahoo(data):
    import yfinance as yf
    watch = CONFIG.get("watchlist", [])
    syms = [t for t, _ in INDICES + SECTORS + GLOBAL + FXC + CREDIT_ETFS] + ["^VIX"] + watch
    df = yf.download(tickers=syms, period="1y", interval="1d", auto_adjust=False,
                     progress=False, threads=True, group_by="ticker")

    def closes(sym):
        try:
            s = df[sym]["Close"].dropna()
            return [(i.date(), float(v)) for i, v in s.items()]
        except Exception:
            return []

    def row(sym, name, spark=True):
        c = closes(sym)
        if len(c) < 2:
            ERRORS.append(f"yahoo:{sym}: no data")
            return None
        v = [x for _, x in c]
        last = v[-1]
        ys = next((x for d, x in c if d.year == TODAY.year), v[0])
        out = {"sym": sym, "name": name, "last": round(last, 2),
               "chg_1d_pct": round((last / v[-2] - 1) * 100, 2),
               "ytd_pct": round((last / ys - 1) * 100, 1),
               "wk52_low": round(min(v), 2), "wk52_high": round(max(v), 2)}
        if len(v) > 5:
            out["chg_5d_pct"] = round((last / v[-6] - 1) * 100, 2)
        if len(v) > 21:
            out["chg_1mo_pct"] = round((last / v[-22] - 1) * 100, 1)
        if len(v) >= 200:
            out["above_200dma"] = last > sum(v[-200:]) / 200
        if spark:
            out["spark"] = downsample(v, 60)
        return out

    data["equities"] = {"indices": [r for t, n in INDICES if (r := row(t, n))],
                        "sectors": [r for t, n in SECTORS if (r := row(t, n, spark=False))]}
    vix = row("^VIX", "VIX")
    if vix:
        x = vix["last"]
        vix["regime"] = "calm" if x < 15 else "normal" if x < 20 else "elevated" if x < 30 else "stressed"
        data["equities"]["vix"] = vix

    data["global"] = [r for t, n in GLOBAL if (r := row(t, n, spark=False))]
    data["fx_cmdty"] = [r for t, n in FXC if (r := row(t, n))]
    data["credit_etfs"] = [r for t, n in CREDIT_ETFS if (r := row(t, n))]
    data["watchlist"] = [r for t in watch if (r := row(t, t))]

    cu, au = closes("HG=F"), closes("GC=F")
    if cu and au:
        am = dict(au)
        ratio = [(d, x / am[d] * 1000) for d, x in cu if d in am and am[d]]
        if ratio:
            rv = [x for _, x in ratio]
            data["copper_gold"] = {"value": round(rv[-1], 2), "spark": downsample(rv, 60)}


# --------------------------------------------------- index returns by period

PERIODS = [("1D", 1), ("1W", 5), ("1M", 21), ("1Y", 252), ("10Y", 2520)]


def build_index_returns(data):
    """Trailing price returns for the major indices over 1D / 1W / 1M / 1Y / 10Y.

    Needs a longer history than build_yahoo's 1y window, so it pulls its own.
    """
    import yfinance as yf
    syms = [t for t, _ in INDICES]
    df = yf.download(tickers=syms, period="11y", interval="1d", auto_adjust=False,
                     progress=False, threads=True, group_by="ticker")

    out = {}
    for sym, name in INDICES:
        try:
            s = df[sym]["Close"].dropna()
            v = [float(x) for x in s.values]
        except Exception as e:
            log_err(f"yahoo-longrun:{sym}", e)
            continue
        if len(v) < 2:
            continue
        last = v[-1]
        rec = {"sym": sym, "name": name, "last": round(last, 2), "periods": {}}
        for label, bars in PERIODS:
            if len(v) <= bars:
                continue
            window = v[-(bars + 1):]
            base = window[0]
            if not base:
                continue
            entry = {"pct": round((last / base - 1) * 100, 2)}
            if bars >= 5:
                entry["spark"] = downsample(window, 60)
            rec["periods"][label] = entry
        if rec["periods"]:
            out[sym] = rec

    if not out:
        raise RuntimeError("no index history returned (Yahoo download empty)")

    data.setdefault("equities", {})["returns"] = {
        "order": [t for t, _ in INDICES if t in out],
        "by_sym": out,
    }


def build_earnings(data):
    import yfinance as yf
    horizon = TODAY + dt.timedelta(days=21)
    found = []
    for sym in CONFIG.get("earnings_tickers", [])[:12]:
        try:
            cal = yf.Ticker(sym).calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if dates:
                d = dates[0]
                d = d.date() if hasattr(d, "date") else d
                if TODAY <= d <= horizon:
                    found.append({"sym": sym, "date": d.isoformat()})
        except Exception:
            continue
    data["earnings"] = sorted(found, key=lambda e: e["date"])


# ------------------------------------------------------------------ news / sentiment

def build_headlines(data):
    import feedparser
    items = []
    for feed in CONFIG.get("rss_feeds", []):
        try:
            p = feedparser.parse(feed["url"], agent=UA["User-Agent"])
            for e in p.entries[:6]:
                ts = dt.datetime(*e.published_parsed[:6]).isoformat() if getattr(e, "published_parsed", None) else ""
                items.append({"title": e.title.strip(), "link": e.link, "source": feed["source"], "ts": ts})
        except Exception as exc:
            log_err(f"rss:{feed['source']}", exc)
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["ts"], reverse=True):
        k = it["title"].lower()[:80]
        if k not in seen:
            seen.add(k)
            out.append(it)
    data["headlines"] = out[:14]


def build_fear_greed(data):
    r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                     headers=UA, timeout=20)
    r.raise_for_status()
    fg = r.json().get("fear_and_greed", {})
    if fg:
        data["sentiment"] = {"fear_greed": {"score": int(round(fg.get("score", 0))),
                                            "label": (fg.get("rating") or "").title()}}


def build_week(data):
    up = [d for d in CONFIG.get("fomc_dates", []) if d >= TODAY.isoformat()]
    w = {}
    if up:
        w["fomc_next"] = up[0]
        w["fomc_days"] = (dt.date.fromisoformat(up[0]) - TODAY).days
    w["releases"] = [r for r in data.get("macro", {}).get("next_releases", [])
                     if r["date"] <= (TODAY + dt.timedelta(days=21)).isoformat()]
    w["earnings"] = data.get("earnings", [])
    data["week"] = w


# ------------------------------------------------------------------ history

def g(d, *path):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return ""
        cur = cur[p]
    return cur


def append_history(data):
    path = ROOT / "history" / "daily.csv"
    cols = ["date", "dgs10", "t2s10s_bps", "ig_bps", "hy_bps", "ccc_bps", "spx", "vix",
            "dxy", "wti", "gold", "btc", "bkln", "fear_greed"]
    fxc = {r["sym"]: r["last"] for r in data.get("fx_cmdty", [])}
    idx = {r["sym"]: r["last"] for r in data.get("equities", {}).get("indices", [])}
    etf = {r["sym"]: r["last"] for r in data.get("credit_etfs", [])}
    row = {"date": TODAY.isoformat(),
           "dgs10": g(data, "rates", "ten_year", "value"),
           "t2s10s_bps": g(data, "rates", "spreads", "2s10s", "bps"),
           "ig_bps": g(data, "credit", "IG", "bps"), "hy_bps": g(data, "credit", "HY", "bps"),
           "ccc_bps": g(data, "credit", "CCC", "bps"), "spx": idx.get("^GSPC", ""),
           "vix": g(data, "equities", "vix", "last"), "dxy": fxc.get("DX-Y.NYB", ""),
           "wti": fxc.get("CL=F", ""), "gold": fxc.get("GC=F", ""), "btc": fxc.get("BTC-USD", ""),
           "bkln": etf.get("BKLN", ""), "fear_greed": g(data, "sentiment", "fear_greed", "score")}
    rows = {}
    if path.exists():
        with path.open() as f:
            for r in csv.DictReader(f):
                rows[r["date"]] = r
    rows[row["date"]] = {k: str(v) for k, v in row.items()}
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for d in sorted(rows):
            w.writerow({c: rows[d].get(c, "") for c in cols})


def main():
    data = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "sample": False}
    for name, fn in [("fred-rates-credit", build_rates_and_credit), ("fred-macro", build_macro),
                     ("fred-weekly", build_weekly_fred), ("fred-quarterly", build_quarterly),
                     ("yahoo", build_yahoo), ("index-returns", build_index_returns),
                     ("earnings", build_earnings),
                     ("headlines", build_headlines), ("fear-greed", build_fear_greed)]:
        try:
            fn(data)
        except Exception as e:
            log_err(name, e)
    build_week(data)
    try:
        append_history(data)
    except Exception as e:
        log_err("history", e)
    data["errors"] = ERRORS
    (ROOT / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    print(f"OK data.json written ({len(ERRORS)} warnings)")


if __name__ == "__main__":
    main()

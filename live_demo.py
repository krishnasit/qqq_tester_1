"""
QQQ Live Demo Bot — Cloud Ready (Railway / GitHub Actions / local)
- yFinance only, no broker needed
- RR 1:1.5 | No trailing stop
- Logs trades to trades_log.csv
- python3 live_demo.py          -> continuous loop
- python3 live_demo.py --once   -> single scan + exit (GitHub Actions)
"""

import yfinance as yf
import pandas as pd
import os, csv, sys, time
from datetime import datetime

SYMBOL           = "QQQ"
TIMEFRAME        = "5m"
RR               = 1.5
RISK_PCT         = 0.01
STARTING_CAP     = 10_000.0
SIGNAL_UTC_START = 13.5
SIGNAL_UTC_END   = 15.0
POLL_SECONDS     = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "trades_log.csv")
CAP_FILE = os.path.join(BASE_DIR, "capital.txt")

def log(msg):
    print(f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)

def load_capital():
    if os.path.isfile(CAP_FILE):
        try:
            return float(open(CAP_FILE).read().strip())
        except Exception:
            pass
    return STARTING_CAP

def save_capital(cap):
    with open(CAP_FILE, "w") as f:
        f.write(str(round(cap, 4)))

def fetch_bars():
    df = yf.download(SYMBOL, period="2d", interval=TIMEFRAME,
                     auto_adjust=True, progress=False)
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]
    return df

def is_bullish_engulfing(prev, curr):
    return (
        prev["close"] < prev["open"]
        and curr["close"] > curr["open"]
        and curr["open"]  <= prev["close"]
        and curr["close"] >= prev["open"]
    )

def in_signal_window(ts):
    h = ts.hour + ts.minute / 60.0
    return SIGNAL_UTC_START <= h <= SIGNAL_UTC_END

def is_market_day():
    return datetime.utcnow().weekday() < 5

def append_trade(row):
    exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)

def load_trades():
    if not os.path.isfile(LOG_FILE):
        return pd.DataFrame()
    return pd.read_csv(LOG_FILE)

def print_stats():
    df = load_trades()
    if df.empty or "result" not in df.columns:
        log("No closed trades yet.")
        return
    closed = df[df["result"].isin(["WIN", "LOSS"])]
    total  = len(closed)
    wins   = (closed["result"] == "WIN").sum()
    wr     = wins / total if total else 0
    net    = pd.to_numeric(closed["pnl_pct"], errors="coerce").sum()
    log(f"Stats: Trades={total} | WR={wr*100:.1f}% | Net={net*100:+.2f}%")

def run_scan(active, capital):
    df = fetch_bars()
    if df is None or len(df) < 3:
        log("Not enough bars — skipping.")
        return active, capital

    prev    = df.iloc[-3]
    curr    = df.iloc[-2]
    curr_ts = df.index[-2]

    if active:
        live_price = float(df["close"].iloc[-1])

        if live_price >= active["tp"]:
            pts     = active["tp"] - active["entry"]
            pnl_pct = (pts * active["shares"]) / capital
            capital += pnl_pct * capital
            save_capital(capital)
            append_trade({**active, "exit": round(active["tp"], 4),
                          "result": "WIN", "pnl_pct": round(pnl_pct, 6),
                          "closed_at": datetime.utcnow().isoformat()})
            log(f"WIN  +{pnl_pct*100:.2f}%  |  Cap: ${capital:,.2f}")
            print_stats()
            return None, capital

        elif live_price <= active["sl"]:
            pts     = active["sl"] - active["entry"]
            pnl_pct = (pts * active["shares"]) / capital
            capital += pnl_pct * capital
            save_capital(capital)
            append_trade({**active, "exit": round(active["sl"], 4),
                          "result": "LOSS", "pnl_pct": round(pnl_pct, 6),
                          "closed_at": datetime.utcnow().isoformat()})
            log(f"LOSS {pnl_pct*100:.2f}%  |  Cap: ${capital:,.2f}")
            print_stats()
            return None, capital

        else:
            log(f"Trade open | Entry: ${active['entry']:.2f} | "
                f"TP: ${active['tp']:.2f} | SL: ${active['sl']:.2f} | "
                f"Live: ${live_price:.2f}")
            return active, capital

    if not in_signal_window(curr_ts):
        log(f"Outside signal window ({curr_ts.strftime('%H:%M UTC')})")
        return active, capital

    if is_bullish_engulfing(prev, curr):
        entry    = float(curr["close"])
        sl_dist  = float(curr["high"]) - float(curr["low"])
        sl       = entry - sl_dist
        tp       = entry + sl_dist * RR
        risk_usd = capital * RISK_PCT
        shares   = max(1, int(risk_usd / sl_dist))

        active = {
            "symbol":    SYMBOL,
            "entry":     round(entry, 4),
            "sl":        round(sl, 4),
            "tp":        round(tp, 4),
            "shares":    shares,
            "risk_usd":  round(risk_usd, 2),
            "opened_at": curr_ts.strftime("%Y-%m-%d %H:%M UTC"),
        }
        log(f"SIGNAL | Entry: ${entry:.2f} | SL: ${sl:.2f} | "
            f"TP: ${tp:.2f} | Shares: {shares}")
        append_trade({**active, "exit": "", "result": "OPEN",
                      "pnl_pct": "", "closed_at": ""})
    else:
        log(f"No signal | {curr_ts.strftime('%H:%M UTC')} | "
            f"O:{float(curr['open']):.2f} H:{float(curr['high']):.2f} "
            f"L:{float(curr['low']):.2f} C:{float(curr['close']):.2f}")

    return active, capital

def run_continuous():
    log(f"QQQ Bot started — RR 1:{RR} | window {SIGNAL_UTC_START}-{SIGNAL_UTC_END} UTC")
    capital = load_capital()
    active  = None

    trades = load_trades()
    if not trades.empty and "result" in trades.columns:
        open_rows = trades[trades["result"] == "OPEN"]
        if not open_rows.empty:
            r = open_rows.iloc[-1]
            active = {k: r[k] for k in
                      ["symbol","entry","sl","tp","shares","risk_usd","opened_at"]}
            active["entry"]    = float(active["entry"])
            active["sl"]       = float(active["sl"])
            active["tp"]       = float(active["tp"])
            active["shares"]   = int(active["shares"])
            active["risk_usd"] = float(active["risk_usd"])
            log(f"Restored open trade — Entry: ${active['entry']:.2f}")

    log(f"Capital: ${capital:,.2f}")

    while True:
        try:
            if is_market_day():
                active, capital = run_scan(active, capital)
            else:
                log("Weekend — skipping.")
        except KeyboardInterrupt:
            log("Bot stopped.")
            print_stats()
            break
        except Exception as e:
            log(f"Error: {e} — retrying in {POLL_SECONDS}s")
        time.sleep(POLL_SECONDS)

def run_once():
    log("QQQ Bot — single scan (--once)")
    if not is_market_day():
        log("Weekend — no scan.")
        return
    capital = load_capital()
    trades  = load_trades()
    active  = None
    if not trades.empty and "result" in trades.columns:
        open_rows = trades[trades["result"] == "OPEN"]
        if not open_rows.empty:
            r = open_rows.iloc[-1]
            active = {k: r[k] for k in
                      ["symbol","entry","sl","tp","shares","risk_usd","opened_at"]}
            active["entry"]    = float(active["entry"])
            active["sl"]       = float(active["sl"])
            active["tp"]       = float(active["tp"])
            active["shares"]   = int(active["shares"])
            active["risk_usd"] = float(active["risk_usd"])
    active, capital = run_scan(active, capital)
    print_stats()

if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_continuous()

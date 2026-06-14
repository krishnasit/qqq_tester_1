"""
QQQ Live Demo Tester
- Data source: yFinance (5m bars, same as backtest)
- Signal: Bullish engulfing on 5m bars at session open window
- RR: 1.5 | No trailing stop (best config from backtest)
- Paper trades: logged to trades_log.csv
- No real money, no broker API needed
"""

import yfinance as yf
import pandas as pd
import numpy as np
import time
import os
import csv
from datetime import datetime, timedelta
import pytz

# ── CONFIG ──────────────────────────────────────────────────────────────────
SYMBOL          = "QQQ"
TIMEFRAME       = "5m"
RR              = 1.5
RISK_PER_TRADE  = 0.01          # 1% of capital per trade
STARTING_CAP    = 10_000.0
SIGNAL_WINDOW   = (13, 15)      # UTC hours: 13:30–15:00 = NYSE 9:30–11:00am
POLL_SECONDS    = 60            # check every 60s
LOG_FILE        = "trades_log.csv"
SESSION_FILE    = "session_stats.txt"

# ── HELPERS ─────────────────────────────────────────────────────────────────
def fetch_bars(symbol, period="2d", interval="5m"):
    df = yf.download(symbol, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index, utc=True)
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower()
                  for c in df.columns]
    return df

def is_bullish_engulfing(prev, curr):
    """Current bar fully engulfs previous bearish bar."""
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    engulfs = (curr["open"] <= prev["close"] and
               curr["close"] >= prev["open"])
    return prev_bearish and curr_bullish and engulfs

def in_signal_window(ts):
    utc_h = ts.hour + ts.minute / 60
    return SIGNAL_WINDOW[0] + 0.5 <= utc_h <= SIGNAL_WINDOW[1]

def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l,
                    (h - c.shift()).abs(),
                    (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]

def append_trade(row: dict):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            w.writeheader()
        w.writerow(row)

def load_trades():
    if not os.path.isfile(LOG_FILE):
        return pd.DataFrame()
    return pd.read_csv(LOG_FILE)

def calc_stats(df):
    if df.empty or "pnl_pct" not in df.columns:
        return {}
    wins = df[df["result"] == "WIN"]
    losses = df[df["result"] == "LOSS"]
    total = len(df[df["result"].isin(["WIN", "LOSS"])])
    wr = len(wins) / total if total else 0
    avg_win = wins["pnl_pct"].mean() if len(wins) else 0
    avg_loss = losses["pnl_pct"].mean() if len(losses) else 0
    pf = abs(avg_win * len(wins)) / abs(avg_loss * len(losses)) if len(losses) and avg_loss else float("inf")
    net = df["pnl_pct"].sum()
    return {
        "trades": total,
        "wins": len(wins),
        "wr": wr,
        "pf": pf,
        "net_pct": net,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }

def print_status(active_trade, capital, last_signal_time, stats):
    os.system("clear")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print("=" * 60)
    print(f"  🤖 QQQ LIVE DEMO TESTER  |  {now}")
    print(f"  Config: RR 1:{RR} | No trail | Signal window 13:30–15:00 UTC")
    print("=" * 60)
    print(f"\n  💰 Capital : ${capital:,.2f}")
    print(f"  📋 Trades  : {stats.get('trades', 0)}  "
          f"Wins: {stats.get('wins', 0)}  "
          f"WR: {stats.get('wr', 0)*100:.1f}%")
    print(f"  📊 Net P&L : {stats.get('net_pct', 0)*100:+.2f}%  "
          f"PF: {stats.get('pf', 0):.2f}")

    if active_trade:
        t = active_trade
        print(f"\n  🟢 ACTIVE TRADE")
        print(f"     Entry : ${t['entry']:.2f}")
        print(f"     TP    : ${t['tp']:.2f}  (+{RR}R)")
        print(f"     SL    : ${t['sl']:.2f}")
        print(f"     Size  : {t['shares']} shares  (${t['risk_$']:.2f} risk)")
        print(f"     Opened: {t['opened_at']}")
    else:
        print(f"\n  ⏳ No active trade")
        if last_signal_time:
            print(f"     Last signal: {last_signal_time}")

    print(f"\n  🔄 Polling every {POLL_SECONDS}s  |  Log: {LOG_FILE}")
    print("=" * 60)

# ── MAIN LOOP ────────────────────────────────────────────────────────────────
def main():
    capital  = STARTING_CAP
    active   = None   # dict when in trade
    last_sig = None

    print("🚀 Starting QQQ Live Demo Tester...")
    print(f"   Capital: ${capital:,.2f} | Risk/trade: {RISK_PER_TRADE*100:.0f}%")
    print(f"   Log file: {LOG_FILE}")
    print("   Ctrl+C to stop\n")

    trades_df = load_trades()

    while True:
        try:
            df = fetch_bars(SYMBOL, period="2d", interval=TIMEFRAME)
            if df is None or len(df) < 3:
                time.sleep(POLL_SECONDS)
                continue

            # Last two CLOSED bars (exclude the currently forming bar)
            prev = df.iloc[-3]
            curr = df.iloc[-2]
            curr_ts = df.index[-2]

            # ── CHECK ACTIVE TRADE ──────────────────────────────────────────
            if active:
                live_price = df["close"].iloc[-1]

                # TP hit?
                if live_price >= active["tp"]:
                    pnl_pts = active["tp"] - active["entry"]
                    pnl_pct = (pnl_pts * active["shares"]) / capital
                    capital += pnl_pct * capital
                    record = {**active, "exit": active["tp"],
                              "result": "WIN", "pnl_pct": pnl_pct,
                              "closed_at": datetime.utcnow().isoformat()}
                    append_trade(record)
                    print(f"\n  ✅ WIN  +{pnl_pct*100:.2f}%  Cap: ${capital:,.2f}")
                    active = None

                # SL hit?
                elif live_price <= active["sl"]:
                    pnl_pts = active["sl"] - active["entry"]
                    pnl_pct = (pnl_pts * active["shares"]) / capital
                    capital += pnl_pct * capital
                    record = {**active, "exit": active["sl"],
                              "result": "LOSS", "pnl_pct": pnl_pct,
                              "closed_at": datetime.utcnow().isoformat()}
                    append_trade(record)
                    print(f"\n  ❌ LOSS {pnl_pct*100:.2f}%  Cap: ${capital:,.2f}")
                    active = None

            # ── SCAN FOR SIGNAL ─────────────────────────────────────────────
            elif in_signal_window(curr_ts):
                if is_bullish_engulfing(prev, curr):
                    entry   = curr["close"]
                    sl_size = curr["high"] - curr["low"]   # candle range as SL
                    sl      = entry - sl_size
                    tp      = entry + sl_size * RR
                    risk_$  = capital * RISK_PER_TRADE
                    shares  = max(1, int(risk_$ / sl_size))

                    active = {
                        "symbol": SYMBOL,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "shares": shares,
                        "risk_$": risk_$,
                        "opened_at": curr_ts.strftime("%Y-%m-%d %H:%M UTC"),
                    }
                    last_sig = active["opened_at"]
                    print(f"\n  🎯 SIGNAL  Entry: ${entry:.2f}  "
                          f"SL: ${sl:.2f}  TP: ${tp:.2f}  "
                          f"Shares: {shares}")

            trades_df = load_trades()
            stats = calc_stats(trades_df)
            print_status(active, capital, last_sig, stats)

        except KeyboardInterrupt:
            print("\n\n  👋 Demo tester stopped.")
            trades_df = load_trades()
            s = calc_stats(trades_df)
            print(f"  Final cap: ${capital:,.2f}")
            print(f"  Trades: {s.get('trades',0)} | WR: {s.get('wr',0)*100:.1f}% | "
                  f"Net: {s.get('net_pct',0)*100:+.2f}%")
            break
        except Exception as e:
            print(f"  ⚠️  Error: {e} — retrying in {POLL_SECONDS}s")

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()

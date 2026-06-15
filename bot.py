import yfinance as yf
import pandas as pd
import os, csv, sys, time
from datetime import datetime

SYMBOL           = "QQQ"
TIMEFRAME        = "5m"
RR               = 1.5
RISK_PCT         = 0.01
STARTING_CAP     = 10000.0
SIGNAL_UTC_START = 13.5
SIGNAL_UTC_END   = 15.0
POLL_SECONDS     = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "trades_log.csv")
CAP_FILE = os.path.join(BASE_DIR, "capital.txt")

def log(msg):
    print("[" + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S") + " UTC] " + str(msg), flush=True)

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

def is_engulfing(prev, curr):
    return (
        prev["close"] < prev["open"]
        and curr["close"] > curr["open"]
        and curr["open"] <= prev["close"]
        and curr["close"] >= prev["open"]
    )

def in_window(ts):
    h = ts.hour + ts.minute / 60.0
    return SIGNAL_UTC_START <= h <= SIGNAL_UTC_END

def is_weekday():
    return datetime.utcnow().weekday() < 5

def save_trade(row):
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

def show_stats():
    df = load_trades()
    if df.empty or "result" not in df.columns:
        log("No closed trades yet.")
        return
    closed = df[df["result"].isin(["WIN", "LOSS"])]
    total = len(closed)
    if total == 0:
        log("No closed trades yet.")
        return
    wins = (closed["result"] == "WIN").sum()
    wr = wins / total
    net = pd.to_numeric(closed["pnl_pct"], errors="coerce").sum()
    log("Stats: Trades=" + str(total) + " WR=" + str(round(wr*100,1)) + "% Net=" + str(round(net*100,2)) + "%")

def restore_open_trade():
    df = load_trades()
    if df.empty or "result" not in df.columns:
        return None
    rows = df[df["result"] == "OPEN"]
    if rows.empty:
        return None
    r = rows.iloc[-1]
    return {
        "symbol":    str(r["symbol"]),
        "entry":     float(r["entry"]),
        "sl":        float(r["sl"]),
        "tp":        float(r["tp"]),
        "shares":    int(r["shares"]),
        "risk_usd":  float(r["risk_usd"]),
        "opened_at": str(r["opened_at"]),
    }

def scan(active, capital):
    df = fetch_bars()
    if df is None or len(df) < 3:
        log("Not enough bars.")
        return active, capital

    prev    = df.iloc[-3]
    curr    = df.iloc[-2]
    ts      = df.index[-2]

    if active:
        price = float(df["close"].iloc[-1])
        if price >= active["tp"]:
            gain = active["tp"] - active["entry"]
            pnl  = (gain * active["shares"]) / capital
            capital = capital + pnl * capital
            save_capital(capital)
            save_trade(dict(active, exit=round(active["tp"],4),
                            result="WIN", pnl_pct=round(pnl,6),
                            closed_at=datetime.utcnow().isoformat()))
            log("WIN +" + str(round(pnl*100,2)) + "%  Cap=" + str(round(capital,2)))
            show_stats()
            return None, capital
        elif price <= active["sl"]:
            loss = active["sl"] - active["entry"]
            pnl  = (loss * active["shares"]) / capital
            capital = capital + pnl * capital
            save_capital(capital)
            save_trade(dict(active, exit=round(active["sl"],4),
                            result="LOSS", pnl_pct=round(pnl,6),
                            closed_at=datetime.utcnow().isoformat()))
            log("LOSS " + str(round(pnl*100,2)) + "%  Cap=" + str(round(capital,2)))
            show_stats()
            return None, capital
        else:
            log("Open trade | Entry=" + str(active["entry"]) +
                " TP=" + str(active["tp"]) +
                " SL=" + str(active["sl"]) +
                " Live=" + str(price))
            return active, capital

    if not in_window(ts):
        log("Outside window (" + ts.strftime("%H:%M UTC") + ")")
        return active, capital

    if is_engulfing(prev, curr):
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
            "opened_at": ts.strftime("%Y-%m-%d %H:%M UTC"),
        }
        log("SIGNAL entry=" + str(round(entry,2)) +
            " sl=" + str(round(sl,2)) +
            " tp=" + str(round(tp,2)) +
            " shares=" + str(shares))
        save_trade(dict(active, exit="", result="OPEN",
                        pnl_pct="", closed_at=""))
    else:
        log("No signal | " + ts.strftime("%H:%M UTC") +
            " O=" + str(round(float(curr["open"]),2)) +
            " H=" + str(round(float(curr["high"]),2)) +
            " L=" + str(round(float(curr["low"]),2)) +
            " C=" + str(round(float(curr["close"]),2)))

    return active, capital

def run_loop():
    log("QQQ Bot started RR=" + str(RR))
    capital = load_capital()
    active  = restore_open_trade()
    log("Capital=" + str(capital))
    while True:
        try:
            if is_weekday():
                active, capital = scan(active, capital)
            else:
                log("Weekend skip.")
        except KeyboardInterrupt:
            log("Stopped.")
            show_stats()
            break
        except Exception as e:
            log("Error: " + str(e))
        time.sleep(POLL_SECONDS)

def run_once():
    log("QQQ Bot single scan")
    if not is_weekday():
        log("Weekend skip.")
        return
    capital = load_capital()
    active  = restore_open_trade()
    scan(active, capital)
    show_stats()

if __name__ == "__main__":
    if "--once" in sys.argv:
        run_once()
    else:
        run_loop()

import os, time, logging, json
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path
import yfinance as yf
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from dotenv import load_dotenv

load_dotenv()
API_KEY    = os.getenv("ALPACA_API_KEY")
API_SECRET = os.getenv("ALPACA_SECRET_KEY")

SYMBOL           = "QQQ"
RISK_PER_TRADE   = 0.01
RR_TARGET        = 2.0
DAILY_DD_LIMIT   = 200.0
VOLUME_SPIKE_PCT = 0.10
EMA_PERIOD       = 50
SMA_PERIOD       = 200
LONDON_TZ        = ZoneInfo("Europe/London")
SESSIONS         = [("London", 8, 17), ("US_Open", 14, 16)]
TRADE_LOG_FILE   = Path("trade_log.json")
BOT_LOG_FILE     = Path("bot_events.json")

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")]
)
log = logging.getLogger("qqq_bot")

client = TradingClient(API_KEY, API_SECRET, paper=True)
daily_pnl = {}

# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            return []
    return []

def append_json(path, record):
    data = load_json(path)
    data.append(record)
    path.write_text(json.dumps(data, indent=2, default=str))

def log_event(level, msg):
    log.info(msg)
    append_json(BOT_LOG_FILE, {
        "time": datetime.now().isoformat(),
        "level": level,
        "msg": msg
    })

def log_trade(record):
    append_json(TRADE_LOG_FILE, record)

# ── Market helpers ────────────────────────────────────────────────────────────
def has_open_position():
    try:
        client.get_open_position(SYMBOL)
        return True
    except:
        return False

def in_session(now_london):
    cur = now_london.hour * 60 + now_london.minute
    for name, sh, eh in SESSIONS:
        if sh * 60 <= cur < eh * 60:
            return name
    return None

def fetch_bars():
    df = yf.download(SYMBOL, period="5d", interval="5m",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    return df.dropna()

def calc_indicators(df):
    df = df.copy()
    df["sma"]     = df["close"].rolling(SMA_PERIOD).mean()
    df["ema"]     = df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    df["vwap"]    = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["vol_avg"] = df["volume"].rolling(8).mean()
    return df

# ── Patterns ──────────────────────────────────────────────────────────────────
def bullish_engulfing(p, c):
    return p["close"]<p["open"] and c["close"]>c["open"] and c["open"]<=p["close"] and c["close"]>=p["open"]

def bearish_engulfing(p, c):
    return p["close"]>p["open"] and c["close"]<c["open"] and c["open"]>=p["close"] and c["close"]<=p["open"]

def tweezer_bottom(p, c):
    return abs(p["low"]-c["low"])/max(p["low"],1e-9)<0.002 and p["close"]<p["open"] and c["close"]>c["open"]

def tweezer_top(p, c):
    return abs(p["high"]-c["high"])/max(p["high"],1e-9)<0.002 and p["close"]>p["open"] and c["close"]<c["open"]

def detect_pattern(p, c):
    for side, name, ok in [
        ("long",  "bullish_engulfing", bullish_engulfing(p,c)),
        ("short", "bearish_engulfing", bearish_engulfing(p,c)),
        ("long",  "tweezer_bottom",    tweezer_bottom(p,c)),
        ("short", "tweezer_top",       tweezer_top(p,c)),
    ]:
        if ok: return side, name
    return None

def trend_long(c):
    ema_ok = abs(c["close"]-c["ema"])/max(c["ema"],1e-9)<=0.50
    return c["close"]>c["vwap"] and c["close"]>c["sma"] and ema_ok

def trend_short(c):
    ema_ok = abs(c["close"]-c["ema"])/max(c["ema"],1e-9)<=0.50
    return c["close"]<c["vwap"] and c["close"]<c["sma"] and ema_ok

# ── Orders ────────────────────────────────────────────────────────────────────
def place_bracket(side, entry, stop, target, qty, pattern, session):
    try:
        order = MarketOrderRequest(
            symbol=SYMBOL, qty=round(qty,4),
            side=OrderSide.BUY if side=="long" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=round(target,2)),
            stop_loss=StopLossRequest(stop_price=round(stop,2)),
        )
        result = client.submit_order(order)
        record = {
            "time":     datetime.now().isoformat(),
            "symbol":   SYMBOL,
            "session":  session,
            "pattern":  pattern,
            "side":     side,
            "entry":    round(entry, 2),
            "stop":     round(stop, 2),
            "target":   round(target, 2),
            "qty":      round(qty, 4),
            "order_id": str(result.id),
            "status":   "open",
            "pnl":      None,
        }
        log_trade(record)
        log_event("TRADE", f"ORDER PLACED {side} {pattern} qty={round(qty,4)} entry={entry:.2f} stop={stop:.2f} target={target:.2f}")
        return result
    except Exception as e:
        log_event("ERROR", f"Order failed: {e}")
        return None

def update_daily_pnl():
    try:
        acct = client.get_account()
        daily_pnl[date.today()] = float(acct.equity) - float(acct.last_equity)
    except:
        pass

# ── Main loop ─────────────────────────────────────────────────────────────────
def run():
    log_event("INFO", f"Bot started | {SYMBOL} | RR 1:{RR_TARGET} | Risk {RISK_PER_TRADE*100}%")
    while True:
        try:
            now_london = datetime.now(ZoneInfo("UTC")).astimezone(LONDON_TZ)
            today      = date.today()

            if now_london.weekday() >= 5:
                time.sleep(3600); continue

            session = in_session(now_london)
            if not session:
                log_event("INFO", f"Outside session ({now_london.strftime('%H:%M')} LDN)")
                time.sleep(60); continue

            update_daily_pnl()
            if daily_pnl.get(today, 0) <= -DAILY_DD_LIMIT:
                log_event("WARN", f"Daily DD cap hit (${daily_pnl.get(today,0):.2f})")
                time.sleep(300); continue

            if has_open_position():
                log_event("INFO", "Position open — monitoring")
                time.sleep(300); continue

            df = fetch_bars()
            if len(df) < SMA_PERIOD + 5:
                time.sleep(60); continue

            df   = calc_indicators(df).dropna()
            prev = df.iloc[-2]
            curr = df.iloc[-1]

            log_event("INFO", f"Price={curr['close']:.2f} SMA={curr['sma']:.2f} EMA={curr['ema']:.2f} VWAP={curr['vwap']:.2f}")

            sig = detect_pattern(prev, curr)
            if not sig:
                log_event("INFO", "No pattern")
                time.sleep(300); continue

            side, pattern = sig
            if curr["volume"] < curr["vol_avg"] * (1 + VOLUME_SPIKE_PCT):
                log_event("INFO", f"Low volume — skip ({pattern})")
                time.sleep(300); continue

            if side == "long" and not trend_long(curr):
                log_event("INFO", "Trend FAIL long"); time.sleep(300); continue
            if side == "short" and not trend_short(curr):
                log_event("INFO", "Trend FAIL short"); time.sleep(300); continue

            acct   = client.get_account()
            equity = float(acct.equity)
            entry  = float(curr["close"])

            if side == "long":
                stop   = float(prev["low"])
                if stop >= entry: time.sleep(300); continue
                dist   = entry - stop
                target = entry + RR_TARGET * dist
            else:
                stop   = float(prev["high"])
                if stop <= entry: time.sleep(300); continue
                dist   = stop - entry
                target = entry - RR_TARGET * dist

            qty = (equity * RISK_PER_TRADE) / dist
            if qty < 0.001:
                time.sleep(300); continue

            place_bracket(side, entry, stop, target, qty, pattern, session)

        except KeyboardInterrupt:
            log_event("INFO", "Bot stopped"); break
        except Exception as e:
            log_event("ERROR", str(e))
            time.sleep(60)

        time.sleep(300)

if __name__ == "__main__":
    run()

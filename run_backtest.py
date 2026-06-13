import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path

# ── Locked config (Loose-A) ───────────────────────────────────────────────────
SYMBOL        = "QQQ"
INTERVAL      = "5m"
PERIOD        = "60d"
INITIAL_CAP   = 10000.0
RISK_PCT      = 0.01
EMA_PERIOD    = 21
SMA_PERIOD    = 50
MAX_HOLD      = 30
ATR_PERIOD    = 14
SLIPPAGE_PCT  = 0.0003
COMMISSION    = 0.65
VOL_SPIKE     = 0.05
ATR_MULT      = 0.20
MIN_CANDLE    = 0.0007
TREND_MODE    = "either"
ACTIVE_PATS   = ["bullish_engulfing", "bearish_engulfing", "tweezer_top"]
SESS_H, SESS_M = 13, 30
END_H,  END_M  = 16, 0
WAIT_MINS      = 30

# ── Grid ──────────────────────────────────────────────────────────────────────
RR_VALUES      = [1.5]
TRAIL_MODES    = ["none"]

OUTPUT = Path("output")
OUTPUT.mkdir(exist_ok=True)

# ── Fetch once ────────────────────────────────────────────────────────────────
print("Fetching QQQ...")
df = yf.download(SYMBOL, period=PERIOD, interval=INTERVAL,
                 auto_adjust=True, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
df.columns = [c.lower() for c in df.columns]
df = df.dropna()
df["ema"]     = df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
df["sma"]     = df["close"].rolling(SMA_PERIOD).mean()
df["vwap"]    = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
df["vol_avg"] = df["volume"].rolling(8).mean()
df["atr"]     = (df["high"] - df["low"]).rolling(ATR_PERIOD).mean()
df = df.dropna()
print(f"Bars: {len(df)}\n")

sess_open_min   = SESS_H*60 + SESS_M
sess_end_min    = END_H*60  + END_M
trade_start_min = sess_open_min + WAIT_MINS

def get_utc(ts):
    try:    return pd.Timestamp(ts).tz_convert("UTC")
    except: return pd.Timestamp(ts)

session_open_price = {}
for i in range(len(df)):
    t = get_utc(df.index[i]); d = t.date(); tm = t.hour*60+t.minute
    if sess_open_min <= tm < sess_open_min+6 and d not in session_open_price:
        session_open_price[d] = float(df.iloc[i]["open"])

def csize(c): return abs(c["close"]-c["open"]) / max(c["open"],1e-9)

def detect(p, c):
    checks = [
        ("long",  "bullish_engulfing",
         p["close"]<p["open"] and c["close"]>c["open"] and
         c["open"]<=p["close"] and c["close"]>=p["open"] and csize(c)>=MIN_CANDLE),
        ("short", "bearish_engulfing",
         p["close"]>p["open"] and c["close"]<c["open"] and
         c["open"]>=p["close"] and c["close"]<=p["open"] and csize(c)>=MIN_CANDLE),
        ("short", "tweezer_top",
         abs(p["high"]-c["high"])/max(p["high"],1e-9)<0.002 and
         p["close"]>p["open"] and c["close"]<c["open"] and csize(c)>=MIN_CANDLE),
    ]
    for side, name, ok in checks:
        if ok and name in ACTIVE_PATS: return side, name
    return None

# ── Core backtest ─────────────────────────────────────────────────────────────
def run(rr_target, trail_mode):
    rows    = [df.iloc[i] for i in range(len(df))]
    trades  = []
    capital = INITIAL_CAP
    in_trade= False

    for i in range(SMA_PERIOD+1, len(rows)-1):
        if in_trade: continue
        prev = rows[i-1]; curr = rows[i]; ts = df.index[i]
        t = get_utc(ts); d = t.date(); tm = t.hour*60+t.minute

        if not (sess_open_min <= tm < sess_end_min): continue
        if tm < trade_start_min: continue
        sess_open = session_open_price.get(d)
        if sess_open is None: continue
        if curr["volume"] < curr["vol_avg"] * (1+VOL_SPIKE): continue

        sig = detect(prev, curr)
        if not sig: continue
        side, pattern = sig

        if side=="long"  and float(curr["close"]) <= sess_open: continue
        if side=="short" and float(curr["close"]) >= sess_open: continue

        price = float(curr["close"])
        ema   = float(curr["ema"])
        vwap  = float(curr["vwap"])
        atr   = float(curr["atr"])

        if TREND_MODE=="either":
            if side=="long"  and price<ema and price<vwap: continue
            if side=="short" and price>ema and price<vwap: continue

        if side=="long":
            orig_stop = float(prev["low"])
            if orig_stop >= price: continue
            dist = price - orig_stop
            if dist < atr * ATR_MULT: continue
            entry = price * (1+SLIPPAGE_PCT)
            target = entry + rr_target * dist
        else:
            orig_stop = float(prev["high"])
            if orig_stop <= price: continue
            dist = orig_stop - price
            if dist < atr * ATR_MULT: continue
            entry = price * (1-SLIPPAGE_PCT)
            target = entry - rr_target * dist

        qty = (capital * RISK_PCT) / dist
        in_trade   = True
        result     = None
        exit_price = None
        exit_time  = None
        bars_held  = 0
        stop       = orig_stop        # dynamic stop starts at original
        one_r      = dist             # 1R distance
        trail_activated = False
        max_fav    = 0.0              # max favourable excursion

        for j in range(i+1, min(i+1+MAX_HOLD, len(rows))):
            bar = rows[j]; bars_held += 1
            bh = float(bar["high"]); bl = float(bar["low"])
            bc = float(bar["close"])
            bar_atr = float(bar["atr"])

            # ── Measure favourable excursion ──────────────────────────────────
            if side=="long":
                fav = bh - entry
            else:
                fav = entry - bl
            max_fav = max(max_fav, fav)

            # ── Trail stop logic ──────────────────────────────────────────────
            if trail_mode == "be":
                # After price moves 1R in our favour → move stop to breakeven
                if not trail_activated and fav >= one_r:
                    stop = entry
                    trail_activated = True

            elif trail_mode == "be+half":
                # After 1R → BE; after 1.5R → trail to halfway between entry and current
                if fav >= one_r * 1.5 and trail_activated:
                    # Trail to halfway
                    if side=="long":
                        new_stop = entry + (fav * 0.5)
                        stop = max(stop, new_stop)
                    else:
                        new_stop = entry - (fav * 0.5)
                        stop = min(stop, new_stop)
                elif not trail_activated and fav >= one_r:
                    stop = entry
                    trail_activated = True

            elif trail_mode == "atr1x":
                # After 1R profit → trail stop by 1x ATR below highest high (long) or above lowest low (short)
                if fav >= one_r:
                    if side=="long":
                        new_stop = bh - bar_atr
                        stop = max(stop, new_stop)
                    else:
                        new_stop = bl + bar_atr
                        stop = min(stop, new_stop)

            elif trail_mode == "atr1.5x":
                # After 1R profit → trail stop by 1.5x ATR
                if fav >= one_r:
                    if side=="long":
                        new_stop = bh - (bar_atr * 1.5)
                        stop = max(stop, new_stop)
                    else:
                        new_stop = bl + (bar_atr * 1.5)
                        stop = min(stop, new_stop)

            # ── Check exit ────────────────────────────────────────────────────
            if side=="long":
                if bl <= stop:
                    result="SL_TRAIL" if trail_activated else "SL"
                    exit_price=stop*(1-SLIPPAGE_PCT); exit_time=df.index[j]; break
                if bh >= target:
                    result="TP"; exit_price=target*(1+SLIPPAGE_PCT); exit_time=df.index[j]; break
            else:
                if bh >= stop:
                    result="SL_TRAIL" if trail_activated else "SL"
                    exit_price=stop*(1+SLIPPAGE_PCT); exit_time=df.index[j]; break
                if bl <= target:
                    result="TP"; exit_price=target*(1-SLIPPAGE_PCT); exit_time=df.index[j]; break

        if result is None:
            result="TIMEOUT"
            exit_price=float(rows[min(i+MAX_HOLD,len(rows)-1)]["close"])
            exit_time=df.index[min(i+MAX_HOLD,len(rows)-1)]

        gross = (exit_price-entry)*qty if side=="long" else (entry-exit_price)*qty
        pnl   = gross - COMMISSION*2
        capital += pnl
        in_trade = False

        trades.append({
            "rr": rr_target, "trail": trail_mode,
            "pattern": pattern, "side": side,
            "entry": round(entry,2), "exit": round(exit_price,2),
            "stop_orig": round(orig_stop,2), "stop_final": round(stop,2),
            "target": round(target,2), "dist": round(dist,4),
            "qty": round(qty,4), "bars_held": bars_held,
            "max_fav": round(max_fav,4),
            "trail_activated": trail_activated,
            "gross": round(gross,2), "pnl": round(pnl,2),
            "result": result, "equity": round(capital,2)
        })

    return pd.DataFrame(trades), capital

# ── Run all 20 combos ─────────────────────────────────────────────────────────
print(f"{'='*85}")
print(f"  {'Config':<20} {'T':>4} {'TP':>4} {'SL':>4} {'SL_T':>5} {'TO':>4} "
      f"{'WR':>6} {'PF':>6} {'Net%':>7} {'DD%':>7} {'Calmar':>7} {'Cap':>12}")
print(f"  {'─'*83}")

all_results = []
best_t_df   = None
best_label  = ""

for rr in RR_VALUES:
    for trail in TRAIL_MODES:
        t_df, final_cap = run(rr, trail)
        label = f"RR {rr} | {trail}"

        if len(t_df)==0:
            print(f"  {label:<20} — no trades"); continue

        tp   = (t_df["result"]=="TP").sum()
        sl   = (t_df["result"]=="SL").sum()
        sl_t = (t_df["result"]=="SL_TRAIL").sum()
        to   = (t_df["result"]=="TIMEOUT").sum()
        tot  = len(t_df)
        wr   = tp/tot*100
        net  = t_df["pnl"].sum()
        npct = net/INITIAL_CAP*100
        gw   = t_df[t_df["pnl"]>0]["pnl"].sum()
        gl   = abs(t_df[t_df["pnl"]<0]["pnl"].sum())
        pf   = gw/gl if gl else 999
        eq_s = t_df["equity"]
        dd   = (eq_s - eq_s.cummax()).min()/INITIAL_CAP*100
        cal  = npct/abs(dd) if dd else 0
        score = npct*0.35 + pf*0.3 + max(0,5-abs(dd))*0.2 + cal*0.15

        flag = "✅" if (npct>8 and pf>1.7 and wr>35) else ("⚠️ " if npct>0 else "❌")
        print(f"  {flag} {label:<18} {tot:>4} {int(tp):>4} {int(sl):>4} {int(sl_t):>5} {int(to):>4} "
              f"{wr:>5.1f}% {pf:>5.2f} {npct:>+6.2f}% {dd:>6.2f}% {cal:>6.2f}  ${final_cap:>9,.2f}")

        all_results.append({
            "label": label, "rr": rr, "trail": trail,
            "trades": tot, "tp": int(tp), "sl": int(sl), "sl_trail": int(sl_t), "timeout": int(to),
            "wr": round(wr,1), "pf": round(pf,2), "net_pct": round(npct,2),
            "dd_pct": round(dd,2), "calmar": round(cal,2), "score": round(score,2),
            "final_cap": round(final_cap,2),
            "avg_win": round(t_df[t_df["pnl"]>0]["pnl"].mean(),2) if tp else 0,
            "avg_loss": round(t_df[t_df["pnl"]<0]["pnl"].mean(),2) if (sl+sl_t) else 0,
            "avg_hold": round(t_df["bars_held"].mean(),1),
            "trail_activated_pct": round(t_df["trail_activated"].mean()*100,1) if trail!="none" else 0,
        })

        # Save best
        if all_results and all_results[-1]["score"] == max(r["score"] for r in all_results):
            best_t_df = t_df.copy()
            best_label = label

print(f"{'='*85}")

# ── Rankings ──────────────────────────────────────────────────────────────────
res_df = pd.DataFrame(all_results)
res_df.to_csv(OUTPUT/"grid_results.csv", index=False)

print(f"\n  🏆 TOP 5 BY SCORE:")
print(f"  {'─'*70}")
top5 = res_df.nlargest(5, "score")
for _, r in top5.iterrows():
    print(f"  {'⭐'} {r['label']:<22} WR={r['wr']}%  PF={r['pf']}  "
          f"Net={r['net_pct']:+.2f}%  DD={r['dd_pct']:.2f}%  "
          f"Calmar={r['calmar']:.2f}  Score={r['score']:.2f}")

print(f"\n  📊 BEST BY METRIC:")
best_net    = res_df.loc[res_df["net_pct"].idxmax()]
best_wr     = res_df.loc[res_df["wr"].idxmax()]
best_pf     = res_df.loc[res_df["pf"].idxmax()]
best_dd     = res_df.loc[res_df["dd_pct"].idxmax()]   # least negative
best_calmar = res_df.loc[res_df["calmar"].idxmax()]

for label, r in [("Best Net%",best_net),("Best WR",best_wr),
                  ("Best PF",best_pf),("Best DD",best_dd),("Best Calmar",best_calmar)]:
    print(f"  {label:<15} → {r['label']:<22} "
          f"Net={r['net_pct']:+.2f}%  WR={r['wr']}%  PF={r['pf']}  DD={r['dd_pct']:.2f}%")

# ── Trailing stop analysis ─────────────────────────────────────────────────────
print(f"\n  📈 TRAILING STOP ANALYSIS (avg across all RR values):")
print(f"  {'─'*60}")
print(f"  {'Mode':<12} {'Avg Net%':>9} {'Avg WR':>8} {'Avg PF':>7} {'Avg DD%':>8} {'Trail Hit%':>11}")
for trail in TRAIL_MODES:
    sub = res_df[res_df["trail"]==trail]
    print(f"  {trail:<12} {sub['net_pct'].mean():>+8.2f}% {sub['wr'].mean():>7.1f}% "
          f"{sub['pf'].mean():>6.2f} {sub['dd_pct'].mean():>7.2f}% "
          f"{sub['trail_activated_pct'].mean():>9.1f}%")

# ── RR analysis ───────────────────────────────────────────────────────────────
print(f"\n  🎯 RR ANALYSIS (avg across all trail modes):")
print(f"  {'─'*60}")
print(f"  {'RR':>5} {'Avg Net%':>9} {'Avg WR':>8} {'Avg PF':>7} {'Avg DD%':>8} {'Avg Hold':>9}")
for rr in RR_VALUES:
    sub = res_df[res_df["rr"]==rr]
    avg_hold = sub["avg_hold"].mean()
    print(f"  1:{rr:<4} {sub['net_pct'].mean():>+8.2f}% {sub['wr'].mean():>7.1f}% "
          f"{sub['pf'].mean():>6.2f} {sub['dd_pct'].mean():>7.2f}% "
          f"{avg_hold:>7.1f}b ({avg_hold*5:.0f}m)")

print(f"\n  Saved → output/grid_results.csv\n")

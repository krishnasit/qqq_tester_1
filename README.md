# QQQ Live Demo Tester

Paper-trades QQQ on 5m bars using yFinance — **no broker account needed**.

## Setup

```bash
cd ~/Desktop/qqq_tester_1     # or wherever you keep the project
pip install yfinance pandas    # already installed in your venv

# Copy the two new files here
cp ~/Desktop/qqq_live_demo/live_demo.py .
cp ~/Desktop/qqq_live_demo/dashboard_live.py .
```

## Run

**Terminal 1 — the bot:**
```bash
python3 live_demo.py
```

**Terminal 2 — live dashboard:**
```bash
streamlit run dashboard_live.py
```

Open http://localhost:8502 (or next available port).

## How It Works

| Step | Detail |
|---|---|
| Data source | yFinance 5m bars — same as backtest, zero mismatch |
| Signal | Bullish engulfing on last **closed** bar (never fires on open bar) |
| Window | 13:30–15:00 UTC (NYSE 9:30–11:00am) |
| RR | 1:1.5 — SL = candle range, TP = SL × 1.5 |
| Position size | 1% capital risk per trade |
| Exit check | Every poll (60s) — checks if live price crossed TP or SL |
| Logging | `trades_log.csv` — append-only, never overwrites |

## Files

| File | Purpose |
|---|---|
| `live_demo.py` | Bot — polls yFinance, detects signals, tracks trade |
| `dashboard_live.py` | Streamlit dashboard — reads trades_log.csv |
| `trades_log.csv` | Auto-created on first trade close |

## Known Limitations

- 60s poll = exits are approximate (real fill may differ by 1 bar)
- yFinance has occasional rate limits — bot retries automatically
- Signal window only active during NYSE session hours

## Next Steps (when ready to go real)

1. Replace TP/SL check with Alpaca paper order API
2. Switch `fetch_bars()` to Alpaca market data for true real-time
3. Add email/SMS alert on signal (smtplib or Twilio)

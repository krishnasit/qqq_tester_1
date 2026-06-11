from backtest.data_loader import load_qqq
from backtest.indicators import BacktestConfig, StrategyBacktester
from dashboard.analysis import trade_summary, overall_stats
from pathlib import Path
import pandas as pd

def main():
    end = pd.Timestamp.now().strftime("%Y-%m-%d")
    start = (pd.Timestamp.now() - pd.Timedelta(days=55)).strftime("%Y-%m-%d")
    print(f"Fetching {start} to {end}")
    df = load_qqq(start, end, "5m")
    print(f"Loaded {len(df)} bars")

    results = []
    for label, cfg in [
        ("London 08-17", BacktestConfig(
            session_start_hour=8, session_end_hour=17,
            observation_minutes=60, rr_target=2.0,
            confirm_next_close=False, ema_tolerance_pct=0.50, volume_spike_pct=0.10
        )),
        ("US Open 14:30-16", BacktestConfig(
            session_start_hour=14, session_end_hour=16,
            observation_minutes=30, rr_target=2.0,
            confirm_next_close=False, ema_tolerance_pct=0.50, volume_spike_pct=0.10
        )),
    ]:
        bt = StrategyBacktester(df, cfg)
        trades, equity = bt.run()
        print(f"\n=== {label} ===")
        print(f"Trades: {len(trades)}")
        stats = overall_stats(trades)
        print(stats.to_string(index=False))
        print(trade_summary(trades).to_string(index=False))
        trades["session"] = label
        equity["session"] = label
        results.append((trades, equity))

    out = Path("output"); out.mkdir(exist_ok=True)
    all_trades = pd.concat([r[0] for r in results], ignore_index=True)
    all_equity = pd.concat([r[1] for r in results], ignore_index=True)
    all_trades.to_csv(out / "trades.csv", index=False)
    all_equity.to_csv(out / "equity.csv", index=False)
    trade_summary(all_trades).to_csv(out / "pattern_summary.csv", index=False)
    overall_stats(all_trades).to_csv(out / "overall_stats.csv", index=False)
    print("\n=== COMBINED ===")
    print(overall_stats(all_trades).to_string(index=False))

if __name__ == "__main__":
    main()

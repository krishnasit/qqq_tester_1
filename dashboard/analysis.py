import pandas as pd
import plotly.express as px

def trade_summary(trades):
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    t["result"] = t["result"].fillna("OPEN")
    summary = t.groupby(["pattern","side"]).agg(
        trades=("pattern","count"),
        total_pnl=("pnl","sum"),
        avg_pnl=("pnl","mean"),
        wins=("pnl", lambda s: (s > 0).sum()),
        losses=("pnl", lambda s: (s < 0).sum()),
        tp=("result", lambda s: (s=="TP").sum()),
        sl=("result", lambda s: (s=="SL").sum()),
    ).reset_index()
    summary["win_rate"] = summary["wins"] / summary["trades"]
    return summary.sort_values(["total_pnl","trades"], ascending=[False,False])

def overall_stats(trades):
    if trades.empty:
        return pd.DataFrame([{"trades":0,"closed_trades":0,"win_rate":0,"net_pnl":0,"avg_pnl":0,"tp_count":0,"sl_count":0}])
    closed = trades[trades["result"].notna()]
    return pd.DataFrame([{
        "trades": len(trades),
        "closed_trades": len(closed),
        "win_rate": round((closed["pnl"] > 0).mean(), 3) if len(closed) else 0,
        "net_pnl": round(closed["pnl"].sum(), 2) if len(closed) else 0,
        "avg_pnl": round(closed["pnl"].mean(), 2) if len(closed) else 0,
        "tp_count": int((closed["result"]=="TP").sum()),
        "sl_count": int((closed["result"]=="SL").sum()),
    }])

def equity_chart(equity):
    return px.line(equity, x="time", y="equity", title="Equity Curve")

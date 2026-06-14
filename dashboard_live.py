"""
Live Demo Dashboard — reads trades_log.csv and shows real-time stats.
Run alongside live_demo.py:  streamlit run dashboard_live.py
"""

import streamlit as st
import pandas as pd
import os, time

LOG_FILE = "trades_log.csv"

st.set_page_config(page_title="QQQ Live Demo", page_icon="📈", layout="wide")
st.title("📈 QQQ Live Demo Tester")
st.caption("RR 1:1.5 | No trail | yFinance data | Paper trades only")

placeholder = st.empty()

def load_and_render():
    with placeholder.container():
        if not os.path.isfile(LOG_FILE):
            st.info("⏳ Waiting for first trade… Run `python3 live_demo.py` in the same folder.")
            return

        df = pd.read_csv(LOG_FILE)
        if df.empty:
            st.info("⏳ No closed trades yet.")
            return

        closed = df[df["result"].isin(["WIN", "LOSS"])].copy()
        if closed.empty:
            st.info("⏳ No closed trades yet.")
            return

        closed["pnl_pct"] = pd.to_numeric(closed["pnl_pct"], errors="coerce")
        closed["cum_pct"] = (1 + closed["pnl_pct"]).cumprod() - 1

        wins   = closed[closed["result"] == "WIN"]
        losses = closed[closed["result"] == "LOSS"]
        total  = len(closed)
        wr     = len(wins) / total if total else 0
        net    = closed["pnl_pct"].sum()
        pf_num = wins["pnl_pct"].sum()
        pf_den = abs(losses["pnl_pct"].sum())
        pf     = pf_num / pf_den if pf_den else float("inf")
        dd     = (closed["cum_pct"] - closed["cum_pct"].cummax()).min()

        # ── KPI row ─────────────────────────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Trades", total)
        c2.metric("Win Rate", f"{wr*100:.1f}%")
        c3.metric("Profit Factor", f"{pf:.2f}" if pf != float("inf") else "∞")
        c4.metric("Net P&L", f"{net*100:+.2f}%")
        c5.metric("Max DD", f"{dd*100:.2f}%")

        # ── Equity curve ────────────────────────────────────────────────────
        st.subheader("Equity Curve")
        eq = closed[["closed_at", "cum_pct"]].copy()
        eq["closed_at"] = pd.to_datetime(eq["closed_at"])
        eq = eq.set_index("closed_at")
        eq.columns = ["Cumulative Return"]
        st.line_chart(eq)

        # ── Trade log ───────────────────────────────────────────────────────
        st.subheader("Trade Log")
        disp = closed[["opened_at", "closed_at", "entry", "exit",
                        "tp", "sl", "shares", "result", "pnl_pct"]].copy()
        disp["pnl_pct"] = (disp["pnl_pct"] * 100).round(3).astype(str) + "%"
        disp["result"] = disp["result"].map({"WIN": "✅ WIN", "LOSS": "❌ LOSS"})
        st.dataframe(disp[::-1], use_container_width=True)

        st.caption(f"Last updated: {pd.Timestamp.utcnow().strftime('%H:%M:%S UTC')}")

while True:
    load_and_render()
    time.sleep(30)

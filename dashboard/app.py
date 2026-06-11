import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path
import subprocess, sys, json
from datetime import datetime

st.set_page_config(page_title="QQQ Bot Dashboard", layout="wide", page_icon="📈")

OUTPUT       = Path("output")
TRADE_LOG    = Path("trade_log.json")
BOT_EVENTS   = Path("bot_events.json")
INITIAL_CAP  = 10000.0

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📊 Backtest", "🤖 Live Bot", "📋 Trade Log"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — BACKTEST
# ════════════════════════════════════════════════════════════════════════════
with tab1:
    st.title("📈 QQQ Backtest Results")

    if st.button("🔄 Re-run Backtest", type="primary"):
        with st.spinner("Running backtest..."):
            r = subprocess.run([sys.executable, "run_backtest.py"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                st.success(r.stdout.strip())
            else:
                st.error(r.stderr)

    if not (OUTPUT / "trades.csv").exists():
        st.info("Click **Re-run Backtest** to generate data.")
    else:
        trades = pd.read_csv(OUTPUT/"trades.csv", parse_dates=["entry_time","exit_time"])
        equity = pd.read_csv(OUTPUT/"equity.csv", parse_dates=["time"])

        # Sidebar filters
        with st.sidebar:
            st.header("Backtest Filters")
            sessions  = ["All"] + sorted(trades["session"].dropna().unique().tolist()) if "session" in trades.columns else ["All"]
            sel_sess  = st.selectbox("Session", sessions)
            all_pats  = sorted(trades["pattern"].dropna().unique().tolist())
            sel_pats  = st.multiselect("Patterns", all_pats, default=all_pats)

        t  = trades.copy()
        if sel_sess != "All": t = t[t["session"]==sel_sess]
        if sel_pats: t = t[t["pattern"].isin(sel_pats)]
        eq = equity.copy()
        if sel_sess != "All" and "session" in equity.columns:
            eq = eq[eq["session"]==sel_sess]

        total = len(t)
        wins  = (t["result"]=="TP").sum() if total else 0
        wr    = wins/total*100 if total else 0
        net   = t["pnl"].sum() if total else 0
        avg   = t["pnl"].mean() if total else 0
        cur_cap = INITIAL_CAP + net
        net_pct = net/INITIAL_CAP*100
        eq_vals = eq.groupby("time")["equity"].last() if "session" in equity.columns else eq.set_index("time")["equity"]
        dd_abs  = (eq_vals - eq_vals.cummax()).min() if len(eq_vals) else 0
        dd_pct  = dd_abs/INITIAL_CAP*100

        b1,b2,b3 = st.columns(3)
        b1.metric("💰 Initial Capital", f"${INITIAL_CAP:,.2f}")
        b2.metric("📈 Current Capital", f"${cur_cap:,.2f}", delta=f"${net:,.2f} ({net_pct:+.2f}%)")
        b3.metric("📉 Max Drawdown",    f"${dd_abs:,.2f}", delta=f"{dd_pct:.2f}%", delta_color="inverse")
        st.divider()

        c1,c2,c3,c4,c5 = st.columns(5)
        c1.metric("Trades",    total)
        c2.metric("Win Rate",  f"{wr:.1f}%")
        c3.metric("Net PnL",   f"${net:,.2f}", delta=f"{net_pct:+.2f}%")
        c4.metric("Avg/Trade", f"${avg:,.2f}")
        c5.metric("TP / SL",   f"{int(wins)} / {int(total-wins)}")
        st.divider()

        # Equity curve
        st.subheader("Equity Curve")
        fig = go.Figure()
        if "session" in equity.columns and sel_sess=="All":
            for sess, grp in eq.groupby("session"):
                fig.add_trace(go.Scatter(x=grp["time"], y=grp["equity"], mode="lines", name=sess))
        else:
            pct = ((eq["equity"]-INITIAL_CAP)/INITIAL_CAP*100).values
            fig.add_trace(go.Scatter(x=eq["time"], y=eq["equity"], mode="lines",
                                     name="Equity", line=dict(color="#00cc96"),
                                     customdata=pct,
                                     hovertemplate="$%{y:,.2f} (%{customdata:+.2f}%)<extra></extra>"))
        fig.add_hline(y=INITIAL_CAP, line_dash="dash", line_color="gray",
                      annotation_text=f"Initial ${INITIAL_CAP:,.0f}")
        fig.update_layout(height=350, margin=dict(l=0,r=0,t=10,b=0), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        st.divider()

        col1,col2 = st.columns(2)
        with col1:
            st.subheader("PnL by Pattern")
            pg = t.groupby("pattern")["pnl"].sum().reset_index().sort_values("pnl",ascending=False)
            pg["pct"] = (pg["pnl"]/INITIAL_CAP*100).round(2)
            pg["lbl"] = pg.apply(lambda r: f"${r['pnl']:,.0f} ({r['pct']:+.2f}%)", axis=1)
            fig2 = px.bar(pg, x="pattern", y="pnl", color="pnl", text="lbl",
                          color_continuous_scale=["#ef553b","#636efa","#00cc96"])
            fig2.update_traces(textposition="outside")
            fig2.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

        with col2:
            st.subheader("Win Rate by Pattern")
            wg = t.groupby("pattern").apply(
                lambda x: pd.Series({"win_rate":(x["result"]=="TP").mean()*100,"trades":len(x)})
            ).reset_index()
            wg["lbl"] = wg.apply(lambda r: f"{r['win_rate']:.0f}% ({int(r['trades'])})", axis=1)
            fig3 = px.bar(wg, x="pattern", y="win_rate", color="win_rate", text="lbl",
                          color_continuous_scale=["#ef553b","#ffa15a","#00cc96"], range_color=[0,100])
            fig3.add_hline(y=50, line_dash="dash", line_color="white", annotation_text="50%")
            fig3.update_traces(textposition="outside")
            fig3.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            st.plotly_chart(fig3, use_container_width=True)

        if "session" in t.columns:
            st.divider()
            st.subheader("Session Comparison")
            sg = t.groupby("session").agg(
                trades=("pnl","count"), net_pnl=("pnl","sum"),
                avg_pnl=("pnl","mean"),
                win_rate=("result", lambda x:(x=="TP").mean()*100)
            ).reset_index()
            sg["Net PnL"] = sg.apply(lambda r: f"${r['net_pnl']:,.2f} ({r['net_pnl']/INITIAL_CAP*100:+.2f}%)", axis=1)
            sg["Avg PnL"] = sg.apply(lambda r: f"${r['avg_pnl']:,.2f}", axis=1)
            sg["Win Rate"]= sg["win_rate"].apply(lambda x: f"{x:.1f}%")
            st.dataframe(sg[["session","trades","Net PnL","Avg PnL","Win Rate"]]
                         .rename(columns={"session":"Session","trades":"Trades"}),
                         use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Trade Log")
        dcols = [c for c in ["entry_time","exit_time","session","pattern","side",
                              "entry_price","exit_price","pnl","result"] if c in t.columns]
        tlog = t[dcols].copy().sort_values("entry_time", ascending=False)
        tlog["pnl_pct"] = (tlog["pnl"]/INITIAL_CAP*100).round(4)
        tlog["pnl"] = tlog.apply(lambda r: f"${r['pnl']:,.2f} ({r['pnl_pct']:+.4f}%)", axis=1)
        tlog = tlog.drop(columns=["pnl_pct"])
        st.dataframe(tlog.style.map(
            lambda v: "color:#00cc96" if v=="TP" else ("color:#ef553b" if v=="SL" else ""),
            subset=["result"]), use_container_width=True, height=400)

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — LIVE BOT
# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.title("🤖 Live Bot Monitor")
    st.caption("Auto-refreshes every 30 seconds")

    # Account summary
    try:
        from alpaca.trading.client import TradingClient
        from dotenv import load_dotenv
        import os
        load_dotenv()
        ac = TradingClient(os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=True)
        acct = ac.get_account()
        a1,a2,a3,a4 = st.columns(4)
        equity   = float(acct.equity)
        last_eq  = float(acct.last_equity)
        day_pnl  = equity - last_eq
        day_pct  = day_pnl / last_eq * 100 if last_eq else 0
        a1.metric("💰 Equity",      f"${equity:,.2f}")
        a2.metric("📅 Day PnL",     f"${day_pnl:,.2f}", delta=f"{day_pct:+.2f}%",
                  delta_color="normal" if day_pnl>=0 else "inverse")
        a3.metric("💵 Buying Power", f"${float(acct.buying_power):,.2f}")
        a4.metric("📊 Account",      "Paper Trading")
    except Exception as e:
        st.warning(f"Could not connect to Alpaca: {e}")

    st.divider()

    # Bot event log
    st.subheader("📟 Bot Event Log")
    if BOT_EVENTS.exists():
        events = json.loads(BOT_EVENTS.read_text())
        events_df = pd.DataFrame(events[::-1])  # newest first
        if len(events_df):
            def color_level(v):
                if v=="TRADE": return "color:#00cc96;font-weight:bold"
                if v=="ERROR": return "color:#ef553b"
                if v=="WARN":  return "color:#ffa15a"
                return ""
            st.dataframe(
                events_df[["time","level","msg"]].head(100)
                .style.map(color_level, subset=["level"]),
                use_container_width=True, height=400
            )
    else:
        st.info("No bot events yet. Start the bot to see live logs here.")

    # Open positions
    st.divider()
    st.subheader("📌 Open Positions")
    try:
        positions = ac.get_all_positions()
        if positions:
            pos_data = [{
                "Symbol": p.symbol,
                "Side": p.side,
                "Qty": p.qty,
                "Entry": f"${float(p.avg_entry_price):,.2f}",
                "Current": f"${float(p.current_price):,.2f}",
                "Unrealized PnL": f"${float(p.unrealized_pl):,.2f} ({float(p.unrealized_plpc)*100:+.2f}%)"
            } for p in positions]
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True, hide_index=True)
        else:
            st.info("No open positions")
    except:
        st.info("Connect Alpaca to see positions")

    # Auto refresh
    st.divider()
    if st.button("🔄 Refresh Now"):
        st.rerun()
    st.caption("Or wait 30s for auto-refresh")
    time_placeholder = st.empty()
    import time as t_module
    t_module.sleep(0)
    st.markdown("""
    <script>
    setTimeout(function(){ window.location.reload(); }, 30000);
    </script>
    """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — LIVE TRADE LOG
# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.title("📋 Live Trade Log")

    if TRADE_LOG.exists():
        trades_live = json.loads(TRADE_LOG.read_text())
        if trades_live:
            df_live = pd.DataFrame(trades_live[::-1])

            # KPIs
            total_live = len(df_live)
            closed     = df_live[df_live["pnl"].notna()]
            won        = (closed["pnl"] > 0).sum() if len(closed) else 0
            wr_live    = won/len(closed)*100 if len(closed) else 0
            net_live   = closed["pnl"].sum() if len(closed) else 0

            l1,l2,l3,l4 = st.columns(4)
            l1.metric("Total Orders", total_live)
            l2.metric("Closed",       len(closed))
            l3.metric("Win Rate",     f"{wr_live:.1f}%")
            l4.metric("Net PnL",      f"${net_live:,.2f}")
            st.divider()

            def color_side(v):
                if v=="long":  return "color:#00cc96"
                if v=="short": return "color:#ef553b"
                return ""
            st.dataframe(
                df_live[["time","session","pattern","side","entry",
                          "stop","target","qty","status","pnl"]].head(200)
                .style.map(color_side, subset=["side"]),
                use_container_width=True, height=500
            )
        else:
            st.info("No live trades yet.")
    else:
        st.info("No live trade log found. Start the bot to see trades here.")

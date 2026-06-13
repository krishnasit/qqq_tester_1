import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from pathlib import Path
import numpy as np

st.set_page_config(
    page_title="QQQ Strategy Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1c1f26; border-radius: 12px;
        padding: 20px; text-align: center;
        border: 1px solid #2d3139;
    }
    .metric-value { font-size: 2rem; font-weight: 700; }
    .metric-label { font-size: 0.8rem; color: #9ca3af; margin-top: 4px; }
    .green { color: #22c55e; }
    .red   { color: #ef4444; }
    .yellow{ color: #f59e0b; }
    .blue  { color: #3b82f6; }
    .stDataFrame { font-size: 13px; }
    div[data-testid="metric-container"] {
        background: #1c1f26; border-radius: 12px;
        padding: 16px; border: 1px solid #2d3139;
    }
</style>
""", unsafe_allow_html=True)

# ── Load data ─────────────────────────────────────────────────────────────────
OUTPUT = Path(__file__).parent.parent / "output"

@st.cache_data(ttl=60)
def load_data():
    t = pd.read_csv(OUTPUT/"trades.csv")
    e = pd.read_csv(OUTPUT/"equity.csv")
    return t, e

try:
    t_df, e_df = load_data()
    has_data = len(t_df) > 0
except:
    has_data = False
    t_df = pd.DataFrame()
    e_df = pd.DataFrame()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Strategy Config")
    st.markdown("---")
    st.markdown("**Asset:** `QQQ`")
    st.markdown("**Session:** US Open")
    st.markdown("**Trade Window:** 14:00–16:00 UTC")
    st.markdown("**Wait:** 30 min after open")
    st.markdown("**Timeframe:** 5 min")
    st.markdown("---")
    st.markdown("**Entry Patterns**")
    show_be  = st.checkbox("Bullish Engulfing ✅", value=True)
    show_bre = st.checkbox("Bearish Engulfing ✅", value=True)
    show_tt  = st.checkbox("Tweezer Top ⚠️",      value=True)
    st.markdown("---")
    st.markdown("**Risk Settings**")
    st.markdown("`Risk/Trade:` 1%")
    st.markdown("`RR Target:` 1:1.5")
    st.markdown("`Max Hold:` 30 bars (150 min)")
    st.markdown("---")
    st.markdown("**Indicators**")
    st.markdown("`EMA:` 21 | `SMA:` 50")
    st.markdown("`Vol Spike:` +5%")
    st.markdown("`ATR Mult:` 0.2x")
    st.markdown("`Min Candle:` 0.07%")
    st.markdown("---")
    st.markdown("**Slippage:** 0.03%")
    st.markdown("**Commission:** $0.65/side")
    st.markdown("---")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# 📈 QQQ Strategy Dashboard")
st.markdown("**Loose-A Config** | US Open Session | 60-Day Backtest")

if not has_data:
    st.error("No trade data found. Run `python3 run_backtest.py` first.")
    st.stop()

# Filter by active patterns
active = []
if show_be:  active.append("bullish_engulfing")
if show_bre: active.append("bearish_engulfing")
if show_tt:  active.append("tweezer_top")
tf = t_df[t_df["pattern"].isin(active)].copy() if active else t_df.copy()

if len(tf) == 0:
    st.warning("No trades match selected patterns.")
    st.stop()

# Recalculate equity for filtered trades
cap = 10000.0
eq_vals = [cap]
for _, row in tf.iterrows():
    cap += row["net_pnl"]
    eq_vals.append(round(cap, 2))
eq_vals = eq_vals[1:]

wins     = (tf["result"]=="TP").sum()
losses   = (tf["result"]=="SL").sum()
timeouts = (tf["result"]=="TIMEOUT").sum()
wr       = wins/len(tf)*100
net      = tf["net_pnl"].sum()
net_pct  = net/10000*100
gross_w  = tf[tf["net_pnl"]>0]["net_pnl"].sum()
gross_l  = abs(tf[tf["net_pnl"]<0]["net_pnl"].sum())
pf       = gross_w/gross_l if gross_l else 999
eq_s     = pd.Series(eq_vals)
dd_vals  = (eq_s - eq_s.cummax())
dd_pct   = dd_vals.min()/10000*100
calmar   = net_pct/abs(dd_pct) if dd_pct else 0
avg_w    = tf[tf["result"]=="TP"]["net_pnl"].mean() if wins else 0
avg_l    = tf[tf["result"]=="SL"]["net_pnl"].mean() if losses else 0

# ── KPI Row ───────────────────────────────────────────────────────────────────
st.markdown("---")
c1,c2,c3,c4,c5,c6,c7 = st.columns(7)

with c1:
    st.metric("Total Trades", len(tf))
with c2:
    color = "normal" if wr >= 33.3 else "inverse"
    st.metric("Win Rate", f"{wr:.1f}%", f"BE: 33.3%")
with c3:
    st.metric("Net PnL", f"${net:,.2f}", f"{net_pct:+.2f}%")
with c4:
    st.metric("Profit Factor", f"{pf:.2f}", "≥1.5 good")
with c5:
    st.metric("Max Drawdown", f"{dd_pct:.2f}%")
with c6:
    st.metric("Calmar Ratio", f"{calmar:.2f}", "≥1.0 good")
with c7:
    st.metric("Final Capital", f"${10000+net:,.2f}")

st.markdown("---")

# ── Row 1: Equity + Drawdown ──────────────────────────────────────────────────
col1, col2 = st.columns([3,2])

with col1:
    st.markdown("### 📊 Equity Curve")
    fig = go.Figure()
    # Baseline
    fig.add_hline(y=10000, line_dash="dot", line_color="#4b5563", line_width=1)
    # Equity line
    fig.add_trace(go.Scatter(
        x=list(range(len(eq_vals))), y=eq_vals,
        mode="lines", name="Equity",
        line=dict(color="#22c55e", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(34,197,94,0.07)"
    ))
    # Mark TPs and SLs
    tp_idx = [i for i,r in enumerate(tf["result"]) if r=="TP"]
    sl_idx = [i for i,r in enumerate(tf["result"]) if r=="SL"]
    if tp_idx:
        fig.add_trace(go.Scatter(
            x=tp_idx, y=[eq_vals[i] for i in tp_idx],
            mode="markers", name="TP",
            marker=dict(color="#22c55e", size=9, symbol="triangle-up",
                       line=dict(color="white",width=1))
        ))
    if sl_idx:
        fig.add_trace(go.Scatter(
            x=sl_idx, y=[eq_vals[i] for i in sl_idx],
            mode="markers", name="SL",
            marker=dict(color="#ef4444", size=9, symbol="triangle-down",
                       line=dict(color="white",width=1))
        ))
    fig.update_layout(
        template="plotly_dark", height=320,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        xaxis_title="Trade #", yaxis_title="Capital ($)",
        legend=dict(orientation="h", y=1.1),
        yaxis=dict(tickformat="$,.0f")
    )
    st.plotly_chart(fig, width="stretch")

with col2:
    st.markdown("### 📉 Drawdown")
    fig2 = go.Figure()
    dd_pct_series = (eq_s - eq_s.cummax()) / 10000 * 100
    fig2.add_trace(go.Scatter(
        x=list(range(len(dd_pct_series))), y=dd_pct_series.tolist(),
        mode="lines", fill="tozeroy",
        line=dict(color="#ef4444", width=2),
        fillcolor="rgba(239,68,68,0.15)", name="Drawdown %"
    ))
    fig2.update_layout(
        template="plotly_dark", height=320,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        xaxis_title="Trade #", yaxis_title="Drawdown %",
        yaxis=dict(ticksuffix="%")
    )
    st.plotly_chart(fig2, width="stretch")

# ── Row 2: Pattern + Win/Loss ─────────────────────────────────────────────────
col3, col4, col5 = st.columns(3)

with col3:
    st.markdown("### 🔍 Pattern PnL")
    pat_data = []
    for pat, g in tf.groupby("pattern"):
        pw = (g["result"]=="TP").sum()
        gpf_v = abs(g[g["net_pnl"]>0]["net_pnl"].sum()/g[g["net_pnl"]<0]["net_pnl"].sum()) \
                if (g["net_pnl"]<0).any() else 999
        pat_data.append({"pattern": pat.replace("_"," ").title(),
                          "pnl": round(g["net_pnl"].sum(),2),
                          "wr": round(pw/len(g)*100,1),
                          "pf": round(gpf_v,2),
                          "trades": len(g)})
    pat_df = pd.DataFrame(pat_data)
    colors = ["#22c55e" if p>0 else "#ef4444" for p in pat_df["pnl"]]
    fig3 = go.Figure(go.Bar(
        x=pat_df["pattern"], y=pat_df["pnl"],
        marker_color=colors,
        text=[f"${p:,.0f}<br>WR:{w}%<br>PF:{f}" 
              for p,w,f in zip(pat_df["pnl"],pat_df["wr"],pat_df["pf"])],
        textposition="outside"
    ))
    fig3.update_layout(
        template="plotly_dark", height=300,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        yaxis=dict(tickformat="$,.0f"), showlegend=False
    )
    st.plotly_chart(fig3, width="stretch")

with col4:
    st.markdown("### 🥧 Result Split")
    labels = ["TP (Win)", "SL (Loss)", "Timeout"]
    values = [int(wins), int(losses), int(timeouts)]
    colors_pie = ["#22c55e","#ef4444","#f59e0b"]
    fig4 = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors_pie),
        hole=0.5,
        textinfo="label+percent+value",
        textfont_size=13
    ))
    fig4.update_layout(
        template="plotly_dark", height=300,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#0e1117",
        showlegend=False
    )
    fig4.add_annotation(
        text=f"<b>{wr:.0f}%</b><br>WR",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=18, color="white")
    )
    st.plotly_chart(fig4, width="stretch")

with col5:
    st.markdown("### 💰 Avg Win vs Loss")
    fig5 = go.Figure()
    fig5.add_trace(go.Bar(
        x=["Avg Win", "Avg Loss"],
        y=[avg_w, abs(avg_l)],
        marker_color=["#22c55e","#ef4444"],
        text=[f"${avg_w:,.2f}", f"${abs(avg_l):,.2f}"],
        textposition="outside",
        textfont=dict(size=15, color="white")
    ))
    fig5.add_annotation(
        text=f"Ratio: {abs(avg_w/avg_l):.2f}x" if avg_l else "No losses",
        x=0.5, y=0.85, xref="paper", yref="paper",
        showarrow=False, font=dict(size=14, color="#f59e0b")
    )
    fig5.update_layout(
        template="plotly_dark", height=300,
        margin=dict(l=0,r=0,t=10,b=0),
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
        yaxis=dict(tickformat="$,.0f"), showlegend=False
    )
    st.plotly_chart(fig5, width="stretch")

# ── Row 3: PnL per trade bar ──────────────────────────────────────────────────
st.markdown("### 📊 PnL Per Trade")
colors_bar = ["#22c55e" if p>0 else "#ef4444" for p in tf["net_pnl"]]
fig6 = go.Figure(go.Bar(
    x=list(range(1, len(tf)+1)),
    y=tf["net_pnl"].tolist(),
    marker_color=colors_bar,
    text=[f"${p:.0f}" for p in tf["net_pnl"]],
    textposition="outside",
    textfont=dict(size=11)
))
fig6.add_hline(y=0, line_color="#4b5563", line_width=1)
fig6.update_layout(
    template="plotly_dark", height=250,
    margin=dict(l=0,r=0,t=10,b=0),
    paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
    xaxis_title="Trade #", yaxis_title="Net PnL ($)",
    yaxis=dict(tickformat="$,.0f")
)
st.plotly_chart(fig6, width="stretch")

# ── Trade Log Table ───────────────────────────────────────────────────────────
st.markdown("### 📋 Full Trade Log")

display_cols = ["trade_num","day","pattern","side","entry_price","exit_price",
                "stop","target","qty","bars_held","gross_pnl","commission","net_pnl","result","equity"]
available = [c for c in display_cols if c in tf.columns]
display_df = tf[available].copy()

# Color result column
def color_result(val):
    if val == "TP":      return "background-color: #14532d; color: #22c55e"
    elif val == "SL":    return "background-color: #450a0a; color: #ef4444"
    elif val=="TIMEOUT": return "background-color: #451a03; color: #f59e0b"
    return ""

def color_pnl(val):
    try:
        if float(val) > 0: return "color: #22c55e; font-weight: bold"
        elif float(val) < 0: return "color: #ef4444; font-weight: bold"
    except: pass
    return ""

styled = display_df.style\
    .map(color_result, subset=["result"])\
    .map(color_pnl, subset=["net_pnl","gross_pnl"])\
    .format({
        "entry_price":"${:.2f}","exit_price":"${:.2f}",
        "stop":"${:.2f}","target":"${:.2f}",
        "gross_pnl":"${:.2f}","commission":"${:.2f}",
        "net_pnl":"${:.2f}","equity":"${:,.2f}",
        "qty":"{:.4f}"
    })
st.dataframe(styled, width="stretch", height=420)

# ── Summary cards row ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🎯 Key Takeaways")
col_a, col_b, col_c, col_d = st.columns(4)
with col_a:
    st.info(f"**Best Pattern**\nBullish Engulfing\nWR=50% | PF=4.38\n${1014:.0f} profit")
with col_b:
    st.warning(f"**Watch Pattern**\nTweezer Top\nWR=25% | PF=0.87\n${-88:.0f} loss — consider disabling")
with col_c:
    st.success(f"**Monthly Target**\n~5% / month\n$500 on $10k account\nAnnual: ~80%")
with col_d:
    st.error(f"**Risk Rules**\nMax 3 consec SL seen\n1% risk per trade\nDD floor: -2.65%")

st.markdown("---")
st.caption("Built with Streamlit + Plotly | QQQ US Open Session Backtester | Data: yfinance")

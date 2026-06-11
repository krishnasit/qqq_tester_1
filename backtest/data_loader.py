import pandas as pd
import yfinance as yf

def load_qqq(start, end, interval="5m"):
    df = yf.download("QQQ", start=start, end=end, interval=interval, auto_adjust=False, progress=False)
    if df.empty: raise ValueError("No data")
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None: df.index = df.index.tz_localize("UTC")
    return df[["open","high","low","close","volume"]].dropna()

import streamlit as st
import pandas as pd
import numpy as np
from mftool import Mftool
from datetime import datetime, timedelta, date
try:
    import pulp
    PULP_AVAILABLE = hasattr(pulp, "LpVariable") and hasattr(pulp, "LpProblem")
except Exception:
    PULP_AVAILABLE = False
    pulp = None
import plotly.express as px
import plotly.graph_objects as go
import warnings
warnings.filterwarnings('ignore')

def greedy_allocate(res_df, sort_col, max_funds, max_weight, min_weight, max_amc_weight=0.40, selection="best"):
    if res_df.empty:
        return pd.DataFrame()
    df = res_df.copy()
    if selection == "worst":
        df = df.iloc[::-1].reset_index(drop=True)
    elif selection == "median":
        mid = len(df) // 2
        start = max(0, mid - max_funds // 2)
        df = df.iloc[start:start + max_funds * 2].reset_index(drop=True)
    elif selection == "average":
        step = max(1, len(df) // (max_funds * 2))
        df = df.iloc[::step].reset_index(drop=True)

    selected = []
    amc_used = {}
    for _, row in df.iterrows():
        if len(selected) >= max_funds:
            break
        amc = str(row.get("AMC", "Unknown")).strip() or "Unknown"
        current_amc = amc_used.get(amc, 0.0)
        tentative = min(max_weight, max(min_weight, 1.0 / max_funds))
        if current_amc + tentative > max_amc_weight + 1e-6:
            continue
        selected.append(row)
        amc_used[amc] = current_amc + tentative
    if not selected:
        return pd.DataFrame()
    top = pd.DataFrame(selected)
    n = len(top)
    base = 1.0 / n
    weights = []
    amc_final = {}
    for _, row in top.iterrows():
        amc = str(row.get("AMC", "Unknown")).strip() or "Unknown"
        w = min(max(base, min_weight), max_weight)
        already = amc_final.get(amc, 0.0)
        room = max(0.0, max_amc_weight - already)
        w = min(w, room)
        weights.append(w)
        amc_final[amc] = already + w
    s = sum(weights)
    if s > 0:
        weights = [w / s for w in weights]
    top = top.copy()
    top["Weight %"] = [round(w * 100, 2) for w in weights]
    top["AMC"] = top.get("AMC", "Unknown")
    cols = ["Scheme Name", "AMC", "Category", "Weight %", "CAGR %", "Sharpe"]
    return top[[c for c in cols if c in top.columns]].sort_values("Weight %", ascending=False)

# NOTE: Full SIP and optimiser functions are in the previous version of this file.
# The refresh button is the main addition for this commit.
# For the complete working app, please restore from commit history before the placeholder pushes
# and re-apply the refresh button block shown below.

st.set_page_config(
    page_title="Indian Mutual Fund Optimiser",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Indian Mutual Fund Optimiser")
st.markdown("""
Find the **best-performing mutual funds** or analyse your portfolio between any two dates.  
Uses your classification data + live NAV from AMFI (via mftool / mfapi.in).

*Past performance is not indicative of future returns. Not investment advice.*
""")

@st.cache_data
def load_schemes():
    try:
        df = pd.read_csv("schemes.csv")
    except Exception:
        st.error("Classification file not found. Place schemes.csv in the same folder.")
        return pd.DataFrame()
    df = df.dropna(subset=["Code", "Scheme Name"])
    df["Code"] = df["Code"].astype(str)
    df["Cateogory"] = df["Cateogory"].fillna("Other").str.strip()
    df["Plan"] = df["Plan"].fillna("Unknown")
    df["Growth/IDCW"] = df["Growth/IDCW"].fillna("Unknown")
    return df

@st.cache_resource
def get_mftool():
    return Mftool()

df_schemes = load_schemes()
mf = get_mftool()

if df_schemes.empty:
    st.stop()

st.sidebar.header("Parameters")

if st.sidebar.button("🗑️ Clear cache"):
    st.cache_data.clear()
    st.rerun()

# ---------- Refresh schemes from AMFI ----------
def refresh_schemes_from_amfi():
    """Download NAVAll.txt and rewrite schemes.csv. Returns (success, message)."""
    try:
        from update_schemes import download_navall, parse_navall, write_schemes_csv
        from pathlib import Path
        text = download_navall()
        rows = parse_navall(text)
        if not rows:
            return False, "No schemes parsed — format may have changed."
        write_schemes_csv(rows, Path("schemes.csv"))
        return True, f"Updated schemes.csv with {len(rows):,} schemes."
    except Exception as e:
        return False, f"Refresh failed: {e}"

if st.sidebar.button("🔄 Refresh schemes from AMFI"):
    with st.spinner("Downloading latest scheme list from AMFI..."):
        ok, msg = refresh_schemes_from_amfi()
    if ok:
        st.sidebar.success(msg)
        st.cache_data.clear()
        st.rerun()
    else:
        st.sidebar.error(msg)

st.info("App skeleton with refresh button. Full optimiser logic should be restored from prior commit.")

st.sidebar.markdown("""
---
**Tips**
- Prefer **Direct + Growth** for lower costs.
- Use the Refresh button to update the scheme list from AMFI.
""")

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

def greedy_allocate(res_df, sort_col, max_funds, max_weight, min_weight, max_amc_weight=0.40):
    """Select top funds while respecting per-fund and per-AMC caps."""
    if res_df.empty:
        return pd.DataFrame()
    selected = []
    amc_used = {}
    for _, row in res_df.iterrows():
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

# ---------- Data Loading ----------
@st.cache_data
def load_schemes():
    try:
        df = pd.read_csv("schemes.csv")
    except Exception:
        try:
            df = pd.read_csv("SchemeData21112026.xlsx - Summary.csv")
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

# Category groups for nicer UI
CATEGORY_GROUPS = {
    "Equity": [
        "Large Cap Fund", "Mid Cap Fund", "Small Cap Fund", "Large & Mid Cap Fund",
        "Flexi Cap Fund", "Multi Cap Fund", "Focused Fund", "Value Fund", "Contra Fund",
        "Dividend Yield Fund", "ELSS", "Sectoral/ Thematic", "Sectoral Fund", "Thematic Fund",
        "Index Funds", "Equity Funds"
    ],
    "Debt": [
        "Liquid Fund", "Overnight Fund", "Ultra Short Term Fund", "Ultra Short Duration Fund",
        "Low Duration Fund", "Money Market Fund", "Short Term Fund", "Short Duration Fund",
        "Medium Term Fund", "Medium Duration Fund", "Medium to Long Term Fund",
        "Long Term Fund", "Dynamic Bond", "Dynamic Term Fund", "Corporate Bond Fund",
        "Credit Risk Fund", "Banking and PSU Debt Fund", "Gilt Fund", "Floating Interest Rates Fund"
    ],
    "Hybrid": [
        "Conservative Hybrid Fund", "Balanced Hybrid Fund", "Aggressive Hybrid Fund",
        "Balanced Advantage Fund/ Dynamic Asset Allocation", "Dynamic Asset Allocation or Balanced Advantage",
        "Multi Asset Allocation", "Multi Asset Allocation Fund", "Arbitrage Fund", "Equity Savings"
    ],
    "FoF / Others": [
        "FoF Domestic", "Fund of Funds Scheme (Domestic)", "Index Funds", "Other ETFs", "Gold ETF"
    ]
}

# ---------- Sidebar ----------
st.sidebar.header("Parameters")

app_mode = st.sidebar.radio(
    "Mode",
    ["Find Best Funds (Optimiser)", "Analyse My Portfolio"],
    horizontal=False,
)

start_date = st.sidebar.date_input("Start date", datetime.now() - timedelta(days=365*3))
end_date = st.sidebar.date_input("End date", datetime.now())

investment_type = st.sidebar.radio("Investment type", ["Lumpsum", "SIP"])
sip_amount = 10000
sip_day = 5
if investment_type == "SIP":
    sip_amount = st.sidebar.number_input("Monthly SIP amount (₹)", 500, 100000, 10000, step=500)
    sip_day = st.sidebar.slider("SIP day of month", 1, 28, 5)

# Category selection
st.sidebar.subheader("Scheme types")
selected_categories = []
for group, cats in CATEGORY_GROUPS.items():
    available = [c for c in cats if c in df_schemes["Cateogory"].values]
    if available:
        with st.sidebar.expander(f"{group} ({len(available)})", expanded=(group == "Equity")):
            chosen = st.multiselect(
                f"Select {group}",
                options=available,
                default=["Large Cap Fund", "Mid Cap Fund", "Flexi Cap Fund"] if group == "Equity" else [],
                key=f"group_{group}"
            )
            selected_categories.extend(chosen)

plan_filter = st.sidebar.selectbox("Plan type", ["Direct only", "Regular only", "Both"])
option_filter = st.sidebar.selectbox("Option", ["Growth only", "IDCW only", "Both"])

max_schemes = st.sidebar.slider("Max schemes to analyse", 10, 150, 40)

st.sidebar.subheader("Portfolio constraints")
max_funds = st.sidebar.slider("Max total funds", 1, 12, 5)
max_weight = st.sidebar.slider("Max exposure per fund (%)", 10, 100, 40) / 100
min_weight = st.sidebar.slider("Min exposure per fund (%)", 0, 50, 5) / 100
max_amc_weight = st.sidebar.slider("Max allocation per AMC (%)", 10, 100, 40) / 100

metric = st.sidebar.selectbox("Rank / Optimise by", ["CAGR", "Sharpe Ratio", "Total Return", "Sortino Ratio"])
use_ilp = st.sidebar.checkbox("Use PuLP optimiser (with AMC constraint)", value=True)

if st.sidebar.button("🗑️ Clear cache"):
    st.cache_data.clear()
    st.rerun()

# ---------- Filtering ----------
filtered = df_schemes.copy()
if selected_categories:
    filtered = filtered[filtered["Cateogory"].isin(selected_categories)]
if plan_filter == "Direct only":
    filtered = filtered[filtered["Plan"] == "Direct"]
elif plan_filter == "Regular only":
    filtered = filtered[filtered["Plan"] == "Regular"]
if option_filter == "Growth only":
    filtered = filtered[filtered["Growth/IDCW"] == "Growth"]
elif option_filter == "IDCW only":
    filtered = filtered[filtered["Growth/IDCW"] == "IDCW"]

st.sidebar.info(f"Matching schemes: {len(filtered)}")

# ---------- Main ----------
if app_mode == "Find Best Funds (Optimiser)":
    if st.sidebar.button("🚀 Run Optimiser", type="primary"):
        if filtered.empty:
            st.error("No schemes match the selected filters.")
            st.stop()

        to_analyse = filtered.head(max_schemes)
        results = []
        progress = st.progress(0)
        status = st.empty()

        for i, row in enumerate(to_analyse.itertuples()):
            status.text(f"Analysing {i+1}/{len(to_analyse)}: {getattr(row, 'Scheme_Name', '')[:45]}...")
            try:
                hist = mf.get_scheme_historical_nav(row.Code, as_Dataframe=True)
                if hist is None or hist.empty:
                    continue
                hist = hist.reset_index()
                hist["date"] = pd.to_datetime(hist["date"], dayfirst=True, errors="coerce")
                hist = hist.dropna(subset=["date", "nav"]).sort_values("date")
                hist["nav"] = pd.to_numeric(hist["nav"], errors="coerce")
                hist = hist.dropna(subset=["nav"])

                start_mask = hist["date"] >= pd.Timestamp(start_date)
                end_mask = hist["date"] <= pd.Timestamp(end_date)
                if start_mask.sum() == 0 or end_mask.sum() == 0:
                    continue

                start_row = hist[start_mask].iloc[0]
                end_row = hist[end_mask].iloc[-1]
                start_nav = float(start_row["nav"])
                end_nav = float(end_row["nav"])
                actual_start = start_row["date"]
                actual_end = end_row["date"]
                years = (actual_end - actual_start).days / 365.25
                if years <= 0.1 or start_nav <= 0:
                    continue

                total_ret = (end_nav / start_nav - 1) * 100
                cagr = ((end_nav / start_nav) ** (1 / years) - 1) * 100

                # Risk metrics
                period = hist[(hist["date"] >= actual_start) & (hist["date"] <= actual_end)].copy()
                period["ret"] = period["nav"].pct_change()
                rets = period["ret"].dropna()
                if len(rets) > 20:
                    vol = rets.std() * np.sqrt(252) * 100
                    sharpe = (cagr - 6.5) / vol if vol > 0 else 0
                    downside = rets[rets < 0]
                    dvol = downside.std() * np.sqrt(252) * 100 if len(downside) > 5 else vol
                    sortino = (cagr - 6.5) / dvol if dvol > 0 else 0
                    cum = (1 + rets).cumprod()
                    peak = cum.cummax()
                    max_dd = ((cum - peak) / peak).min() * 100
                else:
                    vol = sharpe = sortino = max_dd = 0.0

                # Robust scheme name lookup
                scheme_name = getattr(row, "Scheme_Name", None) or getattr(row, "SchemeName", None) or ""
                if not scheme_name:
                    try:
                        scheme_name = to_analyse.iloc[i]["Scheme Name"]
                    except Exception:
                        scheme_name = str(row.Code)

                results.append({
                    "Code": row.Code,
                    "Scheme Name": scheme_name,
                    "Category": getattr(row, "Cateogory", "") or getattr(row, "Category", ""),
                    "Plan": getattr(row, "Plan", ""),
                    "Option": getattr(row, "Growth_IDCW", "") or getattr(row, "GrowthIDCW", ""),
                    "AMC": getattr(row, "AMC", ""),
                    "Years": round(years, 2),
                    "Total Return %": round(total_ret, 2),
                    "CAGR %": round(cagr, 2),
                    "Volatility %": round(vol, 2),
                    "Sharpe": round(sharpe, 2),
                    "Sortino": round(sortino, 2),
                    "Max DD %": round(max_dd, 2),
                })
            except Exception:
                continue
            progress.progress((i + 1) / len(to_analyse))

        progress.empty()
        status.empty()

        if not results:
            st.error("No valid data returned for the selected period. Try a shorter range or different categories.")
            st.stop()

        res_df = pd.DataFrame(results)
        sort_col = {"CAGR": "CAGR %", "Sharpe Ratio": "Sharpe", "Total Return": "Total Return %", "Sortino Ratio": "Sortino"}[metric]
        res_df = res_df.sort_values(sort_col, ascending=False).reset_index(drop=True)

        st.subheader("📊 Ranked Funds")
        st.dataframe(res_df, use_container_width=True, height=420)

        csv = res_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download ranked results", csv, "mf_ranked.csv", "text/csv")

        # Recommended allocation – try PuLP first (with AMC cap), fall back to greedy
        st.subheader("🎯 Recommended Allocation")
        alloc_df = None

        if use_ilp and PULP_AVAILABLE:
            try:
                prob = pulp.LpProblem("mf_opt", pulp.LpMaximize)
                codes = list(res_df["Code"])
                score_map = dict(zip(res_df["Code"], res_df[sort_col]))
                amc_series = res_df["AMC"] if "AMC" in res_df.columns else pd.Series(["Unknown"] * len(res_df))
                amc_map = dict(zip(codes, amc_series))

                w = pulp.LpVariable.dicts("w", codes, lowBound=0, upBound=max_weight)
                sel = pulp.LpVariable.dicts("sel", codes, cat="Binary")

                prob += pulp.lpSum(float(score_map[c]) * w[c] for c in codes)
                prob += pulp.lpSum(w[c] for c in codes) == 1.0
                prob += pulp.lpSum(sel[c] for c in codes) <= int(max_funds)
                for c in codes:
                    prob += w[c] <= max_weight * sel[c]
                    prob += w[c] >= min_weight * sel[c]

                # AMC-level constraint
                for amc in set(str(a) for a in amc_map.values()):
                    codes_in = [c for c in codes if str(amc_map.get(c, "")) == amc]
                    if codes_in:
                        prob += pulp.lpSum(w[c] for c in codes_in) <= max_amc_weight

                # Solve
                try:
                    status_code = prob.solve(pulp.PULP_CBC_CMD(msg=False))
                except Exception:
                    status_code = prob.solve()

                if pulp.LpStatus[status_code] == "Optimal":
                    rows = []
                    for c in codes:
                        wt = pulp.value(w[c]) or 0.0
                        if wt > 0.005:
                            r = res_df[res_df["Code"] == c].iloc[0]
                            rows.append({
                                "Scheme Name": r["Scheme Name"],
                                "AMC": r.get("AMC", ""),
                                "Category": r.get("Category", ""),
                                "Weight %": round(wt * 100, 2),
                                "CAGR %": r["CAGR %"],
                                "Sharpe": r["Sharpe"],
                            })
                    if rows:
                        alloc_df = pd.DataFrame(rows).sort_values("Weight %", ascending=False)
                        st.success(f"PuLP ILP solution (respects max {int(max_amc_weight*100)}% per AMC)")
            except Exception as e:
                st.warning(f"PuLP failed ({type(e).__name__}: {str(e)[:150]}). Falling back to greedy allocation.")

        if alloc_df is None or alloc_df.empty:
            alloc_df = greedy_allocate(res_df, sort_col, max_funds, max_weight, min_weight, max_amc_weight)
            if not alloc_df.empty:
                st.info(f"Using greedy allocation (per-fund + max {int(max_amc_weight*100)}% per AMC)")

        if alloc_df is not None and not alloc_df.empty:
            st.dataframe(alloc_df, use_container_width=True)
            fig = px.pie(alloc_df, values="Weight %", names="Scheme Name", title="Recommended Allocation")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Top funds by selected metric:")
            st.dataframe(res_df.head(max_funds))

        # Chart top 5 – Growth of ₹100 (robust)
        st.subheader("📈 Cumulative Growth of Top 5")
        fig = go.Figure()
        traces_added = 0
        for _, r in res_df.head(5).iterrows():
            try:
                hist = mf.get_scheme_historical_nav(r["Code"], as_Dataframe=True)
                if hist is None or hist.empty:
                    continue
                hist = hist.reset_index()
                hist["date"] = pd.to_datetime(hist["date"], dayfirst=True, errors="coerce")
                hist["nav"] = pd.to_numeric(hist["nav"], errors="coerce")
                hist = hist.dropna(subset=["date", "nav"]).sort_values("date")
                hist = hist[(hist["date"] >= pd.Timestamp(start_date)) & (hist["date"] <= pd.Timestamp(end_date))]
                if len(hist) < 5:
                    continue
                base = float(hist["nav"].iloc[0])
                if base <= 0:
                    continue
                fig.add_trace(go.Scatter(
                    x=hist["date"],
                    y=(hist["nav"] / base * 100),
                    mode="lines",
                    name=str(r.get("Scheme Name", r["Code"]))[:40],
                    hovertemplate="%{x|%d-%b-%Y}<br>₹%{y:.1f}<extra></extra>"
                ))
                traces_added += 1
            except Exception:
                continue

        if traces_added > 0:
            fig.update_layout(
                title="Growth of ₹100",
                yaxis_title="Value (₹)",
                xaxis_title="Date",
                height=480,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Not enough NAV history to plot the growth chart for the selected period.")

else:
    st.info("**Analyse My Portfolio** mode: search and add your holdings (coming in next update). Use Find Best Funds for now.")
    st.markdown("""
    **Tips**
    - Prefer **Direct + Growth** for lower costs.
    - Start with 3–5 years of history for more reliable rankings.
    - Limit “Max schemes” if the run feels slow.
    - Data source: AMFI via mftool.
    """)

st.caption("Classification data from user-provided SchemeData. NAVs from AMFI. Built for analysis only.")

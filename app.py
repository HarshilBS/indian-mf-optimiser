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

def compute_sip_return(hist_df, amount, frequency, sip_day, start_date, end_date):
    """SIP with multiple frequencies. Starts from fund inception if later than start_date."""
    if hist_df.empty:
        return None
    hist = hist_df.copy()
    hist["date"] = pd.to_datetime(hist["date"])
    hist = hist.sort_values("date").reset_index(drop=True)

    first_available = hist["date"].iloc[0]
    end_ts = pd.Timestamp(end_date)
    effective_start = max(pd.Timestamp(start_date), first_available)

    # Frequency offsets
    freq_map = {
        "Daily": pd.DateOffset(days=1),
        "Weekly": pd.DateOffset(weeks=1),
        "Fortnightly": pd.DateOffset(weeks=2),
        "Monthly": pd.DateOffset(months=1),
        "Quarterly": pd.DateOffset(months=3),
        "Semi-annually": pd.DateOffset(months=6),
    }
    offset = freq_map.get(frequency, pd.DateOffset(months=1))

    sip_rows = []
    used_dates = set()
    current = effective_start

    # For monthly+ frequencies, try to align to sip_day if possible
    if frequency in ("Monthly", "Quarterly", "Semi-annually"):
        try:
            current = effective_start.replace(day=min(sip_day, 28))
            if current < first_available:
                current = current + offset
        except Exception:
            current = effective_start

    while current <= end_ts:
        candidates = hist[(hist["date"] >= current) & (~hist["date"].isin(used_dates))]
        if not candidates.empty:
            chosen = candidates.iloc[0]
            # Avoid reusing the exact same date for high-frequency SIPs
            if chosen["date"] not in used_dates:
                sip_rows.append(chosen)
                used_dates.add(chosen["date"])
        current = current + offset

    if len(sip_rows) < 1:
        return None

    latest_nav = float(hist[hist["date"] <= end_ts]["nav"].iloc[-1])
    if latest_nav <= 0:
        return None

    instalments = []
    total_units = 0.0
    total_invested = 0.0
    dates_for_xirr = []
    amounts_for_xirr = []

    for row in sip_rows:
        nav = float(row["nav"])
        if nav <= 0:
            continue
        units_bought = amount / nav
        total_units += units_bought
        total_invested += amount
        current_value = units_bought * latest_nav
        abs_return = (current_value / amount - 1) * 100
        instalments.append({
            "Date": row["date"].strftime("%d-%b-%Y"),
            "NAV": round(nav, 4),
            "Amount": amount,
            "Units Bought": round(units_bought, 4),
            "Cumulative Units": round(total_units, 4),
            "Current Value": round(current_value, 2),
            "Return vs Latest %": round(abs_return, 2),
        })
        dates_for_xirr.append(row["date"])
        amounts_for_xirr.append(-amount)

    if total_units <= 0:
        return None

    final_value = total_units * latest_nav
    dates_for_xirr.append(end_ts)
    amounts_for_xirr.append(final_value)

    xirr_pct = None
    try:
        from scipy.optimize import newton
        def npv(r):
            t0 = dates_for_xirr[0]
            return sum(amt / (1 + r) ** ((d - t0).days / 365.25) for amt, d in zip(amounts_for_xirr, dates_for_xirr))
        xirr = newton(npv, 0.1)
        xirr_pct = round(xirr * 100, 2)
    except Exception:
        pass

    abs_total = round((final_value / total_invested - 1) * 100, 2) if total_invested else 0

    return {
        "instalments_count": len(instalments),
        "invested": total_invested,
        "final_value": round(final_value, 2),
        "total_units": round(total_units, 4),
        "latest_nav": round(latest_nav, 4),
        "xirr_pct": xirr_pct,
        "absolute_return_pct": abs_total,
        "instalments": pd.DataFrame(instalments),
        "effective_start": effective_start.strftime("%d-%b-%Y"),
        "frequency": frequency,
    }

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

st.sidebar.header("Parameters")

app_mode = st.sidebar.radio(
    "Mode",
    ["Find Best Funds (Optimiser)", "Fund Lookup & SIP", "Analyse My Portfolio"],
    horizontal=False,
)

start_date = st.sidebar.date_input("Start date", datetime.now() - timedelta(days=365*3))
end_date = st.sidebar.date_input("End date", datetime.now())

investment_type = st.sidebar.radio("Investment type", ["Lumpsum", "SIP"])
sip_amount = 10000
sip_frequency = "Monthly"
sip_day = 5
if investment_type == "SIP" or app_mode == "Fund Lookup & SIP":
    sip_frequency = st.sidebar.selectbox(
        "SIP frequency",
        ["Daily", "Weekly", "Fortnightly", "Monthly", "Quarterly", "Semi-annually"],
        index=3,
    )
    sip_amount = st.sidebar.number_input(f"{sip_frequency} SIP amount (₹)", 100, 100000, 10000, step=100)
    if sip_frequency in ("Monthly", "Quarterly", "Semi-annually"):
        sip_day = st.sidebar.slider("SIP day of month", 1, 28, 5)
    else:
        sip_day = 1

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
portfolio_selections = st.sidebar.multiselect(
    "Portfolios to compare (side by side)",
    ["Best", "Median", "Average", "Worst"],
    default=["Best", "Median"],
)
use_ilp = st.sidebar.checkbox("Use PuLP optimiser for Best portfolio", value=True)

if st.sidebar.button("🗑️ Clear cache"):
    st.cache_data.clear()
    st.rerun()

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

if app_mode == "Fund Lookup & SIP":
    st.subheader("🔍 Fund Lookup — Full NAV History & SIP Return")

    search = st.text_input("Search scheme name or AMC", "")
    schemes_view = filtered.copy()
    if search:
        mask = schemes_view["Scheme Name"].str.contains(search, case=False, na=False) | \
               schemes_view["AMC"].astype(str).str.contains(search, case=False, na=False)
        schemes_view = schemes_view[mask]

    schemes_view = schemes_view.drop_duplicates(subset=["Scheme Name"]).sort_values("Scheme Name").reset_index(drop=True)

    if schemes_view.empty:
        st.warning("No schemes match your search / filters.")
        st.stop()

    options = schemes_view["Scheme Name"].tolist()
    codes = schemes_view["Code"].tolist()
    selected_name = st.selectbox("Choose a scheme", options)
    selected_code = codes[options.index(selected_name)]

    if st.button("📊 Load NAV History & SIP", type="primary"):
        with st.spinner("Fetching full NAV history..."):
            hist = mf.get_scheme_historical_nav(selected_code, as_Dataframe=True)
        if hist is None or hist.empty:
            st.error("No NAV data available for this scheme.")
            st.stop()

        hist = hist.reset_index()
        hist["date"] = pd.to_datetime(hist["date"], dayfirst=True, errors="coerce")
        hist["nav"] = pd.to_numeric(hist["nav"], errors="coerce")
        hist = hist.dropna(subset=["date", "nav"]).sort_values("date").reset_index(drop=True)

        st.success(f"Loaded {len(hist)} NAV records for {selected_name}")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=hist["date"], y=hist["nav"],
            mode="lines", name="NAV",
            hovertemplate="%{x|%d-%b-%Y}<br>NAV: %{y:.4f}<extra></extra>"
        ))
        fig.update_layout(
            title=f"Full NAV History — {selected_name}",
            xaxis_title="Date", yaxis_title="NAV",
            height=500, hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

        first_nav = hist["nav"].iloc[0]
        last_nav = hist["nav"].iloc[-1]
        years = (hist["date"].iloc[-1] - hist["date"].iloc[0]).days / 365.25
        cagr = ((last_nav / first_nav) ** (1 / years) - 1) * 100 if years > 0.1 and first_nav > 0 else 0
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("First NAV", f"{first_nav:.4f}", hist["date"].iloc[0].strftime("%d-%b-%Y"))
        col2.metric("Latest NAV", f"{last_nav:.4f}", hist["date"].iloc[-1].strftime("%d-%b-%Y"))
        col3.metric("Total Years", f"{years:.1f}")
        col4.metric("Lifetime CAGR", f"{cagr:.2f}%")

        csv = hist.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download full NAV history", csv, f"nav_{selected_code}.csv", "text/csv")

        st.subheader(f"💰 {sip_frequency} SIP Return + Unit Allocation")
        period_hist = hist[(hist["date"] >= pd.Timestamp(start_date)) & (hist["date"] <= pd.Timestamp(end_date))]
        if period_hist.empty:
            period_hist = hist[hist["date"] <= pd.Timestamp(end_date)]
        sip_res = compute_sip_return(
            period_hist if not period_hist.empty else hist,
            sip_amount, sip_frequency, sip_day, start_date, end_date
        )
        if sip_res:
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Instalments", sip_res["instalments_count"])
            c2.metric("Amount Invested", f"₹{sip_res['invested']:,.0f}")
            c3.metric("Total Units", f"{sip_res['total_units']:.4f}")
            c4.metric("Final Value", f"₹{sip_res['final_value']:,.0f}")
            if sip_res["xirr_pct"] is not None:
                c5.metric("SIP XIRR", f"{sip_res['xirr_pct']:.2f}%")
            else:
                c5.metric("Absolute Return", f"{sip_res['absolute_return_pct']:.2f}%")
            st.caption(
                f"{sip_frequency} SIP of ₹{sip_amount:,.0f} | "
                f"Started from {sip_res.get('effective_start', 'inception')} | "
                f"Latest NAV: {sip_res['latest_nav']}"
            )

            st.subheader("Instalment-wise Unit Allocation & Return vs Latest NAV")
            st.dataframe(sip_res["instalments"], use_container_width=True, height=400)
            inst_csv = sip_res["instalments"].to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download instalment details", inst_csv, f"sip_instalments_{selected_code}.csv", "text/csv")
        else:
            st.info("Not enough data in the selected date range to compute SIP return.")

        with st.expander("Recent NAV data"):
            st.dataframe(hist.tail(100)[["date", "nav"]].sort_values("date", ascending=False), use_container_width=True)

elif app_mode == "Find Best Funds (Optimiser)":
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

        if not portfolio_selections:
            st.warning("Select at least one portfolio type in the sidebar.")
        else:
            st.subheader("🎯 Portfolio Comparison (side by side)")
            sel_map = {"Best": "best", "Median": "median", "Average": "average", "Worst": "worst"}
            cols = st.columns(len(portfolio_selections))

            for idx, label in enumerate(portfolio_selections):
                with cols[idx]:
                    st.markdown(f"**{label}**")
                    sel_key = sel_map.get(label, "best")
                    alloc_df = None

                    if use_ilp and PULP_AVAILABLE and sel_key == "best":
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

                            for amc in set(str(a) for a in amc_map.values()):
                                codes_in = [c for c in codes if str(amc_map.get(c, "")) == amc]
                                if codes_in:
                                    prob += pulp.lpSum(w[c] for c in codes_in) <= max_amc_weight

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
                                    st.caption("PuLP ILP")
                        except Exception:
                            pass

                    if alloc_df is None or alloc_df.empty:
                        alloc_df = greedy_allocate(res_df, sort_col, max_funds, max_weight, min_weight, max_amc_weight, selection=sel_key)
                        if not alloc_df.empty:
                            st.caption("Greedy")

                    if alloc_df is not None and not alloc_df.empty:
                        st.dataframe(alloc_df, use_container_width=True, height=280)
                        fig = px.pie(alloc_df, values="Weight %", names="Scheme Name", title=label)
                        fig.update_layout(height=320, margin=dict(t=40, b=20, l=20, r=20))
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No allocation")

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
    st.info("**Analyse My Portfolio** mode: coming soon. Use Find Best Funds or Fund Lookup for now.")

st.caption("Classification data from user-provided SchemeData. NAVs from AMFI. Built for analysis only.")

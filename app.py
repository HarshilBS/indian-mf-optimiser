import streamlit as st
import pandas as pd
from datetime import date, datetime
import plotly.graph_objects as go
from mf_best_investment import MutualFundAnalyzer, CATEGORY_KEYWORDS, CATEGORY_GROUPS

# Cached wrappers to reduce API calls
@st.cache_data(ttl=3600, show_spinner=False)
def cached_search_schemes(query: str):
    analyzer = MutualFundAnalyzer(rate_limit_delay=0.1)
    return analyzer.search_schemes(query)

@st.cache_data(ttl=86400, show_spinner=False)  # 24 hours for NAV data
def cached_get_scheme_nav(scheme_code: int, start_date: str, end_date: str):
    analyzer = MutualFundAnalyzer(rate_limit_delay=0.1)
    return analyzer.get_scheme_meta_and_nav(scheme_code, start_date, end_date)

st.set_page_config(
    page_title="Indian Mutual Fund Optimiser",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Indian Mutual Fund Optimiser")
st.markdown(
    "Find the best-performing mutual funds **or** analyse your own portfolio (SIP + Lumpsum mix) between any two dates. "
    "Uses free live NAV data from [mfapi.in](https://www.mfapi.in)."
)

app_mode = st.radio(
    "What do you want to do?",
    ["Find Best Funds (Optimiser)", "Analyse My Portfolio", "Best For & Later (Out-of-Sample)"],
    horizontal=True,
)

# Sidebar inputs
with st.sidebar:
    st.header("Parameters")

    selected_cats = []
    if app_mode == "Find Best Funds (Optimiser)":
        mode = st.radio("Investment type", ["SIP", "Lumpsum"], horizontal=True)
    elif app_mode == "Best For & Later (Out-of-Sample)":
        mode = st.radio("Investment type", ["SIP", "Lumpsum"], horizontal=True)
        st.info("Pick the portfolio on the **selection period**, then see how it performed in the **later period**.")
    else:
        mode = "custom"

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start date", value=date(2023, 1, 1), key="start_main")
    with col2:
        end_date = st.date_input("End date", value=date(2024, 12, 31), key="end_main")

    if app_mode == "Best For & Later (Out-of-Sample)":
        st.subheader("Selection period (choose the best portfolio)")
        c1, c2 = st.columns(2)
        with c1:
            sel_start = st.date_input("Selection start", value=date(2025, 1, 1), key="sel_start")
        with c2:
            sel_end = st.date_input("Selection end", value=date(2025, 12, 31), key="sel_end")
        st.subheader("Later period (out-of-sample)")
        c3, c4 = st.columns(2)
        with c3:
            later_start = st.date_input("Later start", value=date(2026, 1, 1), key="later_start")
        with c4:
            later_end = st.date_input("Later end", value=date.today(), key="later_end")
        # Override main dates for selection
        start_date = sel_start
        end_date = sel_end

    if app_mode == "Find Best Funds (Optimiser)":
        if mode == "SIP":
            amount = st.number_input("Monthly SIP amount (₹)", min_value=500, value=10000, step=500)
            sip_day = st.slider("SIP day of month", 1, 28, 5)
            frequency = "monthly"
        else:
            amount = st.number_input("Lumpsum amount (₹)", min_value=1000, value=100000, step=1000)
            sip_day = 1
            frequency = "lumpsum"

        st.subheader("Scheme types (categories)")
        index_only = st.checkbox("Index funds only", value=False)

        selected_cats = []
        if index_only:
            selected_cats = ["index"]
            st.info("Only Index funds will be analysed.")
        else:
            for group, cats in CATEGORY_GROUPS.items():
                with st.expander(f"{group} ({len(cats)} types)", expanded=(group == "Equity")):
                    group_selected = st.multiselect(
                        f"Select {group}",
                        options=cats,
                        default=["large_cap", "mid_cap", "small_cap", "flexi_cap"] if group == "Equity" else [],
                        format_func=lambda x: x.replace("_", " ").title(),
                        key=f"cat_{group}",
                    )
                    selected_cats.extend(group_selected)

        plan_type = st.radio(
            "Plan type",
            options=["both", "direct", "regular"],
            format_func=lambda x: {"both": "Both Direct & Regular", "direct": "Direct only", "regular": "Regular only"}[x],
            horizontal=True,
        )

        max_schemes = st.number_input(
            "Max schemes to analyse (higher = slower)",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
            help="No hard cap. Higher numbers take longer because each scheme needs an API call.",
        )

        st.subheader("Portfolio constraints")
        max_funds = st.slider("Max total funds in portfolio", 1, 10, 5)
        max_exposure = st.slider("Max exposure per fund (%)", 10, 100, 40) / 100
        min_exposure = st.slider("Min exposure per fund (%)", 0, 50, 5) / 100

        constraint_mode = st.radio(
            "Category constraint mode",
            options=["count", "percentage", "percentage_no_rebalance"],
            format_func=lambda x: {
                "count": "Count of funds (min/max number)",
                "percentage": "Percentage exposure (with rebalancing simulation)",
                "percentage_no_rebalance": "Percentage exposure (no rebalancing)",
            }[x],
        )
        rebalance_freq = "quarterly"
        if constraint_mode == "percentage":
            rebalance_freq = st.selectbox(
                "Rebalance frequency",
                ["monthly", "quarterly", "semi_annually", "annually"],
                index=1,
            )

        category_count_limits = {}
        category_pct_limits = {}

        if selected_cats:
            st.markdown("**Limits per scheme type**")
            for cat in selected_cats:
                label = cat.replace("_", " ").title()
                if constraint_mode == "count":
                    c1, c2 = st.columns(2)
                    with c1:
                        min_c = st.number_input(f"Min {label}", 0, 5, 0, 1, key=f"minc_{cat}")
                    with c2:
                        max_c = st.number_input(f"Max {label}", 0, 5, 3, 1, key=f"maxc_{cat}")
                    if max_c >= min_c:
                        category_count_limits[cat] = (min_c, max_c)
                else:
                    c1, c2 = st.columns(2)
                    with c1:
                        min_p = st.slider(f"Min % {label}", 0, 100, 0, 5, key=f"minp_{cat}") / 100
                    with c2:
                        max_p = st.slider(f"Max % {label}", 0, 100, 40, 5, key=f"maxp_{cat}") / 100
                    if max_p >= min_p:
                        category_pct_limits[cat] = (min_p, max_p)

        collect_tx = st.checkbox("Also collect transaction history (SIP only)", value=True)
        run = st.button("🚀 Run Optimiser", type="primary", use_container_width=True)
        if st.button("🗑️ Clear cache", use_container_width=True):
            st.cache_data.clear()
            st.success("Cache cleared")
            st.rerun()
    else:
        # Custom portfolio mode
        st.subheader("Your holdings")
        st.caption("Add one or more funds. Mix lumpsum and SIPs of different frequencies.")
        num_holdings = st.number_input("Number of holdings", 1, 15, 3)
        holdings = []
        for i in range(int(num_holdings)):
            st.markdown(f"**Holding {i+1}**")
            search_q = st.text_input(
                f"Search scheme (name / ISIN / code / fund house) {i+1}",
                key=f"search_{i}",
                placeholder="e.g. HDFC Flexi Cap or INF179K01BB2",
            )
            selected_scheme = None
            if search_q and len(search_q) >= 3:
                with st.spinner("Searching..."):
                    results = cached_search_schemes(search_q)
                if results:
                    options = {
                        f"{r.get('schemeName', '')} | {r.get('fund_house', '')} | {r.get('scheme_category', '')} | ISIN: {r.get('isin_growth', 'N/A')} | NAV: {r.get('latest_nav', '—')} ({r.get('latest_date', '')}) (Code: {r.get('schemeCode')})": r
                        for r in results
                    }
                    choice = st.selectbox(
                        f"Select scheme {i+1}",
                        options=["-- Choose a scheme --"] + list(options.keys()),
                        key=f"choice_{i}",
                    )
                    if choice != "-- Choose a scheme --":
                        selected_scheme = options[choice]
                        st.success(
                            f"✅ Selected: **{selected_scheme.get('schemeName')}**  \n"
                            f"Fund House: {selected_scheme.get('fund_house', '—')}  \n"
                            f"Category: {selected_scheme.get('scheme_category', '—')}  \n"
                            f"ISIN: {selected_scheme.get('isin_growth', '—')}  \n"
                            f"Code: {selected_scheme.get('schemeCode')}"
                        )
                else:
                    st.warning("No schemes found. Try a different search term.")

            h_mode = st.radio(f"Type {i+1}", ["SIP", "Lumpsum"], horizontal=True, key=f"mode_{i}")
            h_amount = st.number_input(f"Amount (₹) {i+1}", min_value=100, value=10000, step=500, key=f"amt_{i}")
            if h_mode == "SIP":
                freq = st.selectbox(
                    f"SIP frequency {i+1}",
                    ["daily", "weekly", "fortnightly", "monthly", "quarterly", "semi_annually"],
                    index=3,
                    key=f"freq_{i}",
                )
                sip_day = st.number_input(f"Day / weekday {i+1}", 1, 28, 5, key=f"day_{i}")
            else:
                freq = "lumpsum"
                sip_day = 1

            if selected_scheme:
                holdings.append({
                    "scheme_code": selected_scheme.get("schemeCode"),
                    "scheme_name": selected_scheme.get("schemeName"),
                    "mode": h_mode.lower(),
                    "amount": float(h_amount),
                    "frequency": freq,
                    "sip_day": int(sip_day),
                })
            st.divider()

        collect_tx = st.checkbox("Collect transaction history", value=True)
        run = st.button("📊 Analyse My Portfolio", type="primary", use_container_width=True)

# Main area
if "results" not in st.session_state:
    st.session_state.results = None
if "portfolio" not in st.session_state:
    st.session_state.portfolio = None
if "locked_dates" not in st.session_state:
    st.session_state.locked_dates = None
if "run_params" not in st.session_state:
    st.session_state.run_params = None

if run:
    if start_date >= end_date:
        st.error("Start date must be before end date.")
        st.stop()

    if app_mode == "Analyse My Portfolio":
        if not holdings:
            st.error("Please enter at least one holding with a scheme name.")
            st.stop()

        with st.spinner("Analysing your portfolio..."):
            analyzer = MutualFundAnalyzer(rate_limit_delay=0.2)
            # Lock dates
            locked_start = start_date
            locked_end = end_date
            probe = cached_search_schemes("Large Cap Direct Growth")
            if probe:
                probe_code = probe[0]["schemeCode"]
                probe_data = cached_get_scheme_nav(
                    probe_code,
                    (start_date - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                    (end_date + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
                )
                if probe_data and probe_data.get("data"):
                    probe_df = analyzer.parse_nav_series(probe_data["data"])
                    actual_start = analyzer.get_nearest_nav_date(
                        probe_df, datetime.combine(start_date, datetime.min.time())
                    )
                    actual_end = analyzer.get_nearest_nav_date(
                        probe_df, datetime.combine(end_date, datetime.min.time())
                    )
                    if actual_start:
                        locked_start = actual_start.date()
                    if actual_end:
                        locked_end = actual_end.date()

            df = analyzer.analyze_custom_portfolio(
                holdings,
                locked_start.strftime("%Y-%m-%d"),
                locked_end.strftime("%Y-%m-%d"),
                collect_transactions=collect_tx,
            )

            st.session_state.results = df
            st.session_state.portfolio = df  # whole thing is the portfolio
            st.session_state.locked_dates = (locked_start, locked_end)
            st.session_state.run_params = {
                "mode": "custom",
                "start_date": start_date,
                "end_date": end_date,
            }
            st.session_state.app_mode = "custom"

        # Fall through to display logic below (reuse existing display)
    else:
        # Existing optimiser logic
        if not selected_cats:
            st.error("Please select at least one scheme type.")
            st.stop()

        with st.spinner("Fetching schemes and calculating returns... (this can take 30–90 seconds)"):
            analyzer = MutualFundAnalyzer(rate_limit_delay=0.25)

            locked_start = start_date
            locked_end = end_date
            probe = cached_search_schemes("Large Cap Direct Growth")
            if probe:
                probe_code = probe[0]["schemeCode"]
                probe_data = cached_get_scheme_nav(
                    probe_code,
                    (start_date - pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
                    (end_date + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
                )
                if probe_data and probe_data.get("data"):
                    probe_df = analyzer.parse_nav_series(probe_data["data"])
                    actual_start = analyzer.get_nearest_nav_date(
                        probe_df, datetime.combine(start_date, datetime.min.time())
                    )
                    actual_end = analyzer.get_nearest_nav_date(
                        probe_df, datetime.combine(end_date, datetime.min.time())
                    )
                    if actual_start:
                        locked_start = actual_start.date()
                    if actual_end:
                        locked_end = actual_end.date()

            df = analyzer.analyze_period(
                start_date=locked_start.strftime("%Y-%m-%d"),
                end_date=locked_end.strftime("%Y-%m-%d"),
                mode=mode.lower(),
                amount=float(amount),
                categories=selected_cats,
                sip_day=sip_day,
                plan_type=plan_type,
                max_schemes=max_schemes,
                collect_transactions=(collect_tx and mode == "SIP"),
            )

            portfolio = None
            portfolios = {}
            if not df.empty:
                for sel in ["best", "median", "average", "worst"]:
                    portfolios[sel] = analyzer.suggest_portfolio(
                        df,
                        max_funds=max_funds,
                        max_exposure_per_fund=max_exposure,
                        min_exposure_per_fund=min_exposure,
                        constraint_mode=constraint_mode,
                        category_count_limits=category_count_limits if constraint_mode == "count" else None,
                        category_pct_limits=category_pct_limits if constraint_mode in ("percentage", "percentage_no_rebalance") else None,
                        selection=sel,
                    )
                portfolio = portfolios.get("best")

            # True rebalancing simulation
            rebalance_tx = []
            if constraint_mode == "percentage" and portfolio is not None and not portfolio.empty:
                try:
                    best_p = portfolio
                    target_weights = {int(r["scheme_code"]): float(r["weight"]) for _, r in best_p.iterrows() if r.get("scheme_code")}
                    nav_series = {}
                    analyzer_rb = MutualFundAnalyzer(rate_limit_delay=0.1)
                    for code in list(target_weights.keys())[:8]:  # limit to avoid too many calls
                        nav_data = analyzer_rb.get_scheme_meta_and_nav(
                            code,
                            locked_start.strftime("%Y-%m-%d"),
                            locked_end.strftime("%Y-%m-%d"),
                        )
                        if nav_data:
                            nav_series[code] = analyzer_rb.parse_nav_series(nav_data.get("data", []))
                    if nav_series:
                        rb_result = analyzer_rb.simulate_rebalancing(
                            holdings=[],
                            nav_series=nav_series,
                            start=datetime.combine(locked_start, datetime.min.time()),
                            end=datetime.combine(locked_end, datetime.min.time()),
                            target_weights=target_weights,
                            rebalance_freq=rebalance_freq,
                            initial_amount=float(amount),
                        )
                        rebalance_tx = rb_result.get("transactions", [])
                except Exception:
                    rebalance_tx = []
            st.session_state.rebalance_tx = rebalance_tx

            st.session_state.results = df
            st.session_state.portfolio = portfolio
            st.session_state.portfolios = portfolios
            st.session_state.locked_dates = (locked_start, locked_end)
            st.session_state.run_params = {
                "mode": mode,
                "amount": amount,
                "sip_day": sip_day,
                "start_date": start_date,
                "end_date": end_date,
            }
            st.session_state.app_mode = "optimiser" if app_mode != "Best For & Later (Out-of-Sample)" else "oos"
            if app_mode == "Best For & Later (Out-of-Sample)":
                st.session_state.oos_params = {
                    "later_start": later_start,
                    "later_end": later_end,
                    "mode": mode,
                    "amount": amount,
                    "sip_day": sip_day,
                }

# Display stored results (persists across reruns)
if st.session_state.results is not None:
    df = st.session_state.results
    portfolio = st.session_state.portfolio
    locked_start, locked_end = st.session_state.locked_dates or (start_date, end_date)
    params = st.session_state.run_params or {}
    is_custom = params.get("mode") == "custom" or st.session_state.get("app_mode") == "custom"
    is_oos = st.session_state.get("app_mode") == "oos"

    if locked_start != start_date or locked_end != end_date:
        st.info(
            f"Selected dates locked to nearest working days with NAV: "
            f"**{locked_start}** → **{locked_end}**"
        )

    if df.empty:
        st.warning("No results found. Check scheme names or date range.")
    else:
        st.success(f"Analysed {len(df)} schemes")

        if is_custom:
            st.subheader("Your Portfolio Results")
            total_inv = df["invested"].sum()
            total_final = df["final_value"].sum()
            overall_ret = (total_final / total_inv - 1) * 100 if total_inv else 0

            # Portfolio XIRR
            analyzer_xirr = MutualFundAnalyzer(rate_limit_delay=0.1)
            port_xirr = analyzer_xirr.get_portfolio_xirr(df)
            port_xirr_pct = port_xirr * 100 if port_xirr is not None else None

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Invested", f"₹{total_inv:,.0f}")
            c2.metric("Final Value", f"₹{total_final:,.0f}")
            c3.metric("Absolute Return", f"{overall_ret:.2f}%")
            if port_xirr_pct is not None:
                st.metric("Portfolio XIRR", f"{port_xirr_pct:.2f}%")

            display_cols = ["scheme_name", "category_key", "mode", "frequency", "amount", "invested", "final_value", "abs_return_pct", "xirr_pct"]
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[display_cols].style.format({
                    "abs_return_pct": "{:.2f}%",
                    "xirr_pct": "{:.2f}%",
                    "invested": "₹{:,.0f}",
                    "final_value": "₹{:,.0f}",
                    "amount": "₹{:,.0f}",
                }, na_rep="—"),
                use_container_width=True,
                hide_index=True,
            )
        else:
            # Original optimiser display
            display_cols = ["rank", "scheme_name", "plan", "category_key", "category", "abs_return_pct", "invested", "final_value"]
            if params.get("mode") == "SIP" and "xirr_pct" in df.columns:
                display_cols.insert(6, "xirr_pct")
            if "cagr_pct" in df.columns:
                display_cols.insert(6, "cagr_pct")

            st.subheader("Top Ranked Schemes")
            show_df = df[[c for c in display_cols if c in df.columns]].head(30)
            try:
                st.dataframe(
                    show_df.style.format({
                        "abs_return_pct": "{:.2f}%",
                        "xirr_pct": "{:.2f}%",
                        "cagr_pct": "{:.2f}%",
                        "invested": "₹{:,.0f}",
                        "final_value": "₹{:,.0f}",
                    }, na_rep="—"),
                    use_container_width=True,
                    hide_index=True,
                    height=400,
                )
            except Exception:
                st.dataframe(show_df, use_container_width=True, hide_index=True, height=400)

            st.subheader("Suggested Portfolios")
            portfolios = st.session_state.get("portfolios", {"best": portfolio})
            tabs = st.tabs(["Best", "Median", "Average", "Worst"])
            for tab, key in zip(tabs, ["best", "median", "average", "worst"]):
                with tab:
                    p = portfolios.get(key)
                    if p is not None and not p.empty:
                        port_cols = [c for c in ["rank", "scheme_name", "plan", "category_key", "abs_return_pct", "weight", "selection"] if c in p.columns]
                        if "xirr_pct" in p.columns:
                            port_cols.insert(-2, "xirr_pct")
                        try:
                            st.dataframe(
                                p[port_cols].style.format({
                                    "abs_return_pct": "{:.2f}%",
                                    "xirr_pct": "{:.2f}%",
                                    "weight": "{:.1%}",
                                }, na_rep="—"),
                                use_container_width=True,
                                hide_index=True,
                                height=300,
                            )
                        except Exception:
                            st.dataframe(p[port_cols], use_container_width=True, hide_index=True, height=300)
                        if "weight" in p.columns:
                            st.bar_chart(p.set_index("scheme_name")["weight"])
                        # Weighted average return
                        if "abs_return_pct" in p.columns and "weight" in p.columns:
                            wavg = (p["abs_return_pct"] * p["weight"]).sum()
                            st.caption(f"Weighted absolute return: **{wavg:.2f}%**")
                    else:
                        st.info(f"Could not build {key} portfolio.")

            # Out-of-sample evaluation
            if is_oos and st.session_state.get("oos_params"):
                oos = st.session_state.oos_params
                later_start = oos["later_start"]
                later_end = oos["later_end"]
                st.subheader(f"Out-of-Sample Performance ({later_start} → {later_end})")
                st.caption("Same funds and weights chosen on the selection period, evaluated on the later period.")

                best_port = portfolios.get("best")
                if best_port is not None and not best_port.empty:
                    with st.spinner("Calculating out-of-sample returns..."):
                        analyzer_oos = MutualFundAnalyzer(rate_limit_delay=0.15)
                        oos_results = []
                        for _, prow in best_port.iterrows():
                            code = prow.get("scheme_code")
                            if not code:
                                continue
                            nav_data = analyzer_oos.get_scheme_meta_and_nav(
                                int(code),
                                later_start.strftime("%Y-%m-%d"),
                                later_end.strftime("%Y-%m-%d"),
                            )
                            if not nav_data:
                                continue
                            df_nav = analyzer_oos.parse_nav_series(nav_data.get("data", []))
                            weight = prow.get("weight", 1.0 / len(best_port))
                            if oos["mode"] == "SIP":
                                calc = analyzer_oos.calculate_sip_return(
                                    df_nav,
                                    datetime.combine(later_start, datetime.min.time()),
                                    datetime.combine(later_end, datetime.min.time()),
                                    oos["amount"] * weight,
                                    "monthly",
                                    oos["sip_day"],
                                )
                            else:
                                calc = analyzer_oos.calculate_lumpsum_return(
                                    df_nav,
                                    datetime.combine(later_start, datetime.min.time()),
                                    datetime.combine(later_end, datetime.min.time()),
                                    oos["amount"] * weight,
                                )
                            if calc:
                                oos_results.append({
                                    "scheme_name": prow["scheme_name"],
                                    "weight": weight,
                                    **calc,
                                })

                        if oos_results:
                            oos_df = pd.DataFrame(oos_results)
                            total_inv = oos_df["invested"].sum()
                            total_final = oos_df["final_value"].sum()
                            oos_ret = (total_final / total_inv - 1) * 100 if total_inv else 0
                            st.metric("Out-of-Sample Absolute Return", f"{oos_ret:.2f}%")
                            st.dataframe(
                                oos_df[["scheme_name", "weight", "invested", "final_value", "abs_return_pct"]].style.format({
                                    "weight": "{:.1%}",
                                    "invested": "₹{:,.0f}",
                                    "final_value": "₹{:,.0f}",
                                    "abs_return_pct": "{:.2f}%",
                                }),
                                use_container_width=True,
                                hide_index=True,
                            )
                        else:
                            st.warning("Could not calculate out-of-sample returns.")

        # Equity curve (works for both)
        if not df.empty:
            st.subheader("Equity Curve")
            with st.spinner("Generating equity curve..."):
                curves = []
                analyzer = MutualFundAnalyzer(rate_limit_delay=0.1)
                for _, row in df.iterrows():
                    code = row.get("scheme_code")
                    if not code:
                        continue
                    nav_data = analyzer.get_scheme_meta_and_nav(
                        int(code),
                        locked_start.strftime("%Y-%m-%d"),
                        locked_end.strftime("%Y-%m-%d"),
                    )
                    if not nav_data:
                        continue
                    df_nav = analyzer.parse_nav_series(nav_data.get("data", []))
                    curve = analyzer.generate_equity_curve(
                        df_nav,
                        datetime.combine(locked_start, datetime.min.time()),
                        datetime.combine(locked_end, datetime.min.time()),
                        row.get("mode", "sip"),
                        float(row.get("amount", row.get("invested", 10000))),
                        row.get("frequency", "monthly"),
                        row.get("sip_day", 1),
                        1.0,
                    )
                    if not curve.empty:
                        curve = curve.rename(columns={"value": str(row["scheme_name"])[:40]})
                        curves.append(curve.set_index("date"))

                if curves:
                    equity = pd.concat(curves, axis=1).ffill().fillna(0)
                    equity["Portfolio"] = equity.sum(axis=1)

                    # Build cumulative invested series for roller-coaster view
                    invested_series = pd.Series(0.0, index=equity.index)
                    for _, row in df.iterrows():
                        txs = row.get("transactions")
                        if isinstance(txs, list):
                            for tx in txs:
                                if tx.get("amount", 0) < 0:  # outflow = investment
                                    try:
                                        dt = pd.to_datetime(tx["date"])
                                        if dt in invested_series.index:
                                            invested_series.loc[dt:] += abs(tx["amount"])
                                        else:
                                            # add to nearest or forward fill later
                                            invested_series.loc[invested_series.index >= dt] += abs(tx["amount"])
                                    except Exception:
                                        pass
                        else:
                            # fallback for lumpsum
                            if row.get("mode") == "lumpsum" and row.get("invested"):
                                invested_series += row["invested"]

                    invested_series = invested_series.ffill().fillna(0)
                    equity["Invested"] = invested_series

                    # Optional benchmark overlay
                    benchmark_choice = st.selectbox(
                        "Overlay benchmark",
                        ["None", "Nifty 50 Index Fund (example)"],
                        key="bench",
                    )
                    if benchmark_choice != "None" and is_custom:
                        nifty_code = 119598
                        total_invested = df["invested"].sum()
                        analyzer_bench = MutualFundAnalyzer(rate_limit_delay=0.1)
                        bench_curve = analyzer_bench.get_benchmark_curve(
                            nifty_code,
                            datetime.combine(locked_start, datetime.min.time()),
                            datetime.combine(locked_end, datetime.min.time()),
                            total_invested,
                        )
                        if not bench_curve.empty:
                            bench_curve = bench_curve.set_index("date").rename(columns={"value": "Nifty 50"})
                            equity = equity.join(bench_curve, how="outer").ffill()

                    # Static chart (always safe)
                    chart_cols = [c for c in ["Portfolio", "Invested", "Nifty 50"] if c in equity.columns]
                    if chart_cols:
                        st.line_chart(equity[chart_cols])

                    # Animated roller-coaster chart (optional, guarded)
                    st.subheader("🎢 Portfolio Roller Coaster")
                    st.caption("Animated view of money invested vs current portfolio value over time.")
                    try:
                        anim_df = equity.reset_index()
                        if "date" not in anim_df.columns and "index" in anim_df.columns:
                            anim_df = anim_df.rename(columns={"index": "date"})
                        anim_df = anim_df.sort_values("date").reset_index(drop=True)

                        if len(anim_df) < 5:
                            st.info("Not enough data points for animation.")
                        else:
                            fig = go.Figure()
                            fig.add_trace(go.Scatter(
                                x=anim_df["date"], y=anim_df["Invested"],
                                mode="lines", name="Invested",
                                line=dict(color="#888", dash="dash"),
                            ))
                            fig.add_trace(go.Scatter(
                                x=anim_df["date"], y=anim_df["Portfolio"],
                                mode="lines", name="Current Value",
                                line=dict(color="#00cc96", width=3),
                            ))
                            if "Nifty 50" in anim_df.columns:
                                fig.add_trace(go.Scatter(
                                    x=anim_df["date"], y=anim_df["Nifty 50"],
                                    mode="lines", name="Nifty 50",
                                    line=dict(color="#636EFA", dash="dot"),
                                ))

                            # Limit frames to avoid browser crashes
                            step = max(1, len(anim_df) // 30)
                            frames = []
                            for i in range(step, len(anim_df) + 1, step):
                                frame_data = [
                                    go.Scatter(x=anim_df["date"][:i], y=anim_df["Invested"][:i]),
                                    go.Scatter(x=anim_df["date"][:i], y=anim_df["Portfolio"][:i]),
                                ]
                                traces = [0, 1]
                                if "Nifty 50" in anim_df.columns:
                                    frame_data.append(go.Scatter(x=anim_df["date"][:i], y=anim_df["Nifty 50"][:i]))
                                    traces.append(2)
                                frames.append(go.Frame(data=frame_data, traces=traces))
                            fig.frames = frames

                            fig.update_layout(
                                title="Invested vs Current Portfolio Value",
                                xaxis_title="Date",
                                yaxis_title="Value (₹)",
                                updatemenus=[{
                                    "type": "buttons",
                                    "buttons": [
                                        {
                                            "label": "▶ Play",
                                            "method": "animate",
                                            "args": [None, {"frame": {"duration": 100, "redraw": True}, "fromcurrent": True}],
                                        },
                                        {
                                            "label": "Pause",
                                            "method": "animate",
                                            "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate"}],
                                        },
                                    ],
                                }],
                                height=480,
                            )
                            st.plotly_chart(fig, use_container_width=True)
                    except Exception as e:
                        st.warning(f"Could not render animated chart ({type(e).__name__}). Static chart above is still available.")

                    with st.expander("Show individual fund curves"):
                        other_cols = [c for c in equity.columns if c not in ("Portfolio", "Invested")]
                        if other_cols:
                            st.line_chart(equity[other_cols])

        # Downloads
        st.subheader("Downloads")

        results_df = df.drop(columns=["transactions"], errors="ignore").copy()
        results_df.insert(0, "start_date", locked_start.strftime("%Y-%m-%d"))
        results_df.insert(1, "end_date", locked_end.strftime("%Y-%m-%d"))
        csv = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download ranked results (CSV)",
            data=csv,
            file_name=f"mf_ranked_{locked_start}_{locked_end}.csv",
            mime="text/csv",
        )

        # All portfolios (best / median / average / worst) in one file
        portfolios = st.session_state.get("portfolios", {})
        if portfolios:
            all_ports = []
            for sel, p in portfolios.items():
                if p is not None and not p.empty:
                    tmp = p.copy()
                    tmp.insert(0, "portfolio_type", sel)
                    tmp.insert(1, "start_date", locked_start.strftime("%Y-%m-%d"))
                    tmp.insert(2, "end_date", locked_end.strftime("%Y-%m-%d"))
                    all_ports.append(tmp)
            if all_ports:
                ports_df = pd.concat(all_ports, ignore_index=True)
                ports_csv = ports_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download all portfolios (Best/Median/Average/Worst)",
                    data=ports_csv,
                    file_name=f"mf_portfolios_{locked_start}_{locked_end}.csv",
                    mime="text/csv",
                )

        if "transactions" in df.columns and df["transactions"].notna().any():
            all_tx = []
            for _, row in df.iterrows():
                txs = row.get("transactions")
                if isinstance(txs, list) and txs:
                    for tx in txs:
                        tx_row = {
                            "start_date": locked_start.strftime("%Y-%m-%d"),
                            "end_date": locked_end.strftime("%Y-%m-%d"),
                            "scheme_code": row["scheme_code"],
                            "scheme_name": row["scheme_name"],
                            "mode": row.get("mode", ""),
                            "frequency": row.get("frequency", ""),
                            **tx,
                        }
                        all_tx.append(tx_row)
            if all_tx:
                tx_df = pd.DataFrame(all_tx)
                tx_csv = tx_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Download full transaction history (CSV)",
                    data=tx_csv,
                    file_name=f"mf_transactions_{locked_start}_{locked_end}.csv",
                    mime="text/csv",
                )

        # Rebalancing transactions
        rb_tx = st.session_state.get("rebalance_tx", [])
        if rb_tx:
            rb_df = pd.DataFrame(rb_tx)
            rb_df.insert(0, "start_date", locked_start.strftime("%Y-%m-%d"))
            rb_df.insert(1, "end_date", locked_end.strftime("%Y-%m-%d"))
            rb_csv = rb_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download rebalancing transactions (CSV)",
                data=rb_csv,
                file_name=f"mf_rebalance_{locked_start}_{locked_end}.csv",
                mime="text/csv",
            )
            with st.expander("View rebalancing transactions"):
                st.dataframe(rb_df, use_container_width=True, hide_index=True)

    if st.button("Clear results"):
        for k in ["results", "portfolio", "locked_dates", "run_params", "app_mode"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()

else:
    st.info("👈 Set your parameters in the sidebar and click the run button.")
    st.markdown("""
    **Tips:**
    - **Find Best Funds**: ranks schemes by historical return under your constraints.
    - **Analyse My Portfolio**: enter your own holdings (mix of lumpsum + SIPs of any frequency).
    - Supported SIP frequencies: daily, weekly, fortnightly, monthly, quarterly, semi-annually.
    - Past performance is not indicative of future returns.
    """)

st.caption("Data source: mfapi.in (AMFI-based). Not investment advice.")

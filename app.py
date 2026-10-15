import streamlit as st
import pandas as pd
from datetime import date, datetime
from mf_best_investment import MutualFundAnalyzer, CATEGORY_KEYWORDS, CATEGORY_GROUPS

st.set_page_config(
    page_title="Indian Mutual Fund Optimiser",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Indian Mutual Fund Optimiser")
st.markdown(
    "Find the best-performing mutual funds (SIP or Lumpsum) between any two dates. "
    "Uses free live NAV data from [mfapi.in](https://www.mfapi.in)."
)

# Sidebar inputs
with st.sidebar:
    st.header("Parameters")

    mode = st.radio("Investment type", ["SIP", "Lumpsum"], horizontal=True)

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start date", value=date(2023, 1, 1))
    with col2:
        end_date = st.date_input("End date", value=date(2024, 12, 31))

    if mode == "SIP":
        amount = st.number_input("Monthly SIP amount (₹)", min_value=500, value=10000, step=500)
        sip_day = st.slider("SIP day of month", 1, 28, 5)
    else:
        amount = st.number_input("Lumpsum amount (₹)", min_value=1000, value=100000, step=1000)
        sip_day = 1

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
            "percentage": "Percentage exposure (with rebalancing)",
            "percentage_no_rebalance": "Percentage exposure (no rebalancing)",
        }[x],
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
                # Both percentage modes use the same % inputs
                c1, c2 = st.columns(2)
                with c1:
                    min_p = st.slider(f"Min % {label}", 0, 100, 0, 5, key=f"minp_{cat}") / 100
                with c2:
                    max_p = st.slider(f"Max % {label}", 0, 100, 40, 5, key=f"maxp_{cat}") / 100
                if max_p >= min_p:
                    category_pct_limits[cat] = (min_p, max_p)

    collect_tx = st.checkbox("Also collect transaction history (SIP only)", value=True)

    run = st.button("🚀 Run Optimiser", type="primary", use_container_width=True)

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

    if not selected_cats:
        st.error("Please select at least one scheme type.")
        st.stop()

    with st.spinner("Fetching schemes and calculating returns... (this can take 30–90 seconds)"):
        analyzer = MutualFundAnalyzer(rate_limit_delay=0.25)

        # Probe one scheme to lock start/end dates to nearest working day with NAV
        locked_start = start_date
        locked_end = end_date
        probe = analyzer.search_schemes("Large Cap Direct Growth")
        if probe:
            probe_code = probe[0]["schemeCode"]
            probe_data = analyzer.get_scheme_meta_and_nav(
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
        if not df.empty:
            portfolio = analyzer.suggest_portfolio(
                df,
                max_funds=max_funds,
                max_exposure_per_fund=max_exposure,
                min_exposure_per_fund=min_exposure,
                constraint_mode=constraint_mode,
                category_count_limits=category_count_limits if constraint_mode == "count" else None,
                category_pct_limits=category_pct_limits if constraint_mode in ("percentage", "percentage_no_rebalance") else None,
            )

        # Store in session state so results stay on screen
        st.session_state.results = df
        st.session_state.portfolio = portfolio
        st.session_state.locked_dates = (locked_start, locked_end)
        st.session_state.run_params = {
            "mode": mode,
            "amount": amount,
            "sip_day": sip_day,
            "start_date": start_date,
            "end_date": end_date,
        }

# Display stored results (persists across reruns)
if st.session_state.results is not None:
    df = st.session_state.results
    portfolio = st.session_state.portfolio
    locked_start, locked_end = st.session_state.locked_dates or (start_date, end_date)
    params = st.session_state.run_params or {}

    if locked_start != start_date or locked_end != end_date:
        st.info(
            f"Selected dates locked to nearest working days with NAV: "
            f"**{locked_start}** → **{locked_end}**"
        )

    if df.empty:
        st.warning("No results found. Try broader categories, different plan type, or different dates.")
    else:
        st.success(f"Analysed {len(df)} schemes")

        display_cols = ["rank", "scheme_name", "plan", "category_key", "category", "abs_return_pct", "invested", "final_value"]
        if params.get("mode") == "SIP" and "xirr_pct" in df.columns:
            display_cols.insert(6, "xirr_pct")
        if "cagr_pct" in df.columns:
            display_cols.insert(6, "cagr_pct")

        st.subheader("Top Ranked Schemes")
        st.dataframe(
            df[[c for c in display_cols if c in df.columns]].head(20).style.format({
                "abs_return_pct": "{:.2f}%",
                "xirr_pct": "{:.2f}%",
                "cagr_pct": "{:.2f}%",
                "invested": "₹{:,.0f}",
                "final_value": "₹{:,.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Suggested Portfolio")
        if portfolio is not None and not portfolio.empty:
            port_cols = [c for c in ["rank", "scheme_name", "plan", "category_key", "abs_return_pct", "weight"] if c in portfolio.columns]
            if "xirr_pct" in portfolio.columns:
                port_cols.insert(-1, "xirr_pct")
            st.dataframe(
                portfolio[port_cols].style.format({
                    "abs_return_pct": "{:.2f}%",
                    "xirr_pct": "{:.2f}%",
                    "weight": "{:.1%}",
                }),
                use_container_width=True,
                hide_index=True,
            )

            if "weight" in portfolio.columns:
                st.bar_chart(portfolio.set_index("scheme_name")["weight"])

            if "category_key" in portfolio.columns:
                summary = portfolio.groupby("category_key")["weight"].sum()
                st.caption("Category exposure: " + ", ".join(f"{k}: {v:.1%}" for k, v in summary.items()))

            # Equity curve
            st.subheader("Equity Curve (Portfolio)")
            with st.spinner("Generating equity curve..."):
                curves = []
                analyzer = MutualFundAnalyzer(rate_limit_delay=0.1)
                for _, prow in portfolio.iterrows():
                    code = prow.get("scheme_code")
                    if code is None:
                        match = df[df["scheme_name"] == prow["scheme_name"]]
                        if match.empty:
                            continue
                        code = match.iloc[0]["scheme_code"]
                    weight = prow.get("weight", 1.0 / len(portfolio))
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
                        params.get("mode", "sip").lower(),
                        float(params.get("amount", amount)),
                        params.get("sip_day", sip_day),
                        weight,
                    )
                    if not curve.empty:
                        curve = curve.rename(columns={"value": prow["scheme_name"][:40]})
                        curves.append(curve.set_index("date"))

                if curves:
                    equity = pd.concat(curves, axis=1).ffill().fillna(0)
                    equity["Portfolio"] = equity.sum(axis=1)
                    st.line_chart(equity[["Portfolio"]])
                    with st.expander("Show individual fund curves"):
                        st.line_chart(equity.drop(columns=["Portfolio"]))
                else:
                    st.info("Could not generate equity curve (insufficient NAV data).")
        else:
            st.info("Could not build a portfolio that satisfies the constraints.")

        # Downloads
        st.subheader("Downloads")

        results_df = df.drop(columns=["transactions"], errors="ignore")
        csv = results_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download ranked results (CSV)",
            data=csv,
            file_name=f"mf_optimiser_{locked_start}_{locked_end}.csv",
            mime="text/csv",
        )

        if params.get("mode") == "SIP" and "transactions" in df.columns and df["transactions"].notna().any():
            all_tx = []
            for _, row in df.iterrows():
                txs = row.get("transactions")
                if isinstance(txs, list) and txs:
                    for tx in txs:
                        tx_row = {
                            "scheme_code": row["scheme_code"],
                            "scheme_name": row["scheme_name"],
                            "plan": row.get("plan", ""),
                            "category_key": row.get("category_key", ""),
                            "rank": row["rank"],
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

    if st.button("Clear results"):
        st.session_state.results = None
        st.session_state.portfolio = None
        st.session_state.locked_dates = None
        st.session_state.run_params = None
        st.rerun()

else:
    st.info("👈 Set your parameters in the sidebar and click **Run Optimiser**.")
    st.markdown("""
    **Tips:**
    - **Count mode**: min/max number of funds per scheme type.
    - **Percentage (with rebalancing)**: forces portfolio % into the set ranges.
    - **Percentage (no rebalancing)**: equal-weight portfolio; category % are shown but not forced.
    - Longer date ranges give more meaningful results.
    - Past performance is not indicative of future returns.
    """)

st.caption("Data source: mfapi.in (AMFI-based). Not investment advice.")

import streamlit as st
import pandas as pd
from datetime import datetime, date
from mf_best_investment import MutualFundAnalyzer, CATEGORY_KEYWORDS

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

    st.subheader("Categories")
    available_cats = list(CATEGORY_KEYWORDS.keys())
    selected_cats = st.multiselect(
        "Select categories",
        options=available_cats,
        default=["large_cap", "mid_cap", "small_cap", "flexi_cap"],
        format_func=lambda x: x.replace("_", " ").title(),
    )

    prefer_direct = st.checkbox("Prefer Direct Growth plans only", value=True)
    max_schemes = st.slider("Max schemes to analyse", 10, 80, 40)

    st.subheader("Portfolio constraints")
    max_funds = st.slider("Max funds in portfolio", 1, 10, 4)
    max_exposure = st.slider("Max exposure per fund (%)", 10, 100, 35) / 100
    min_exposure = st.slider("Min exposure per fund (%)", 0, 50, 10) / 100

    run = st.button("🚀 Run Optimiser", type="primary", use_container_width=True)

# Main area
if run:
    if start_date >= end_date:
        st.error("Start date must be before end date.")
        st.stop()

    if not selected_cats:
        st.error("Please select at least one category.")
        st.stop()

    with st.spinner("Fetching schemes and calculating returns... (this can take 30–90 seconds)"):
        analyzer = MutualFundAnalyzer(rate_limit_delay=0.25)

        df = analyzer.analyze_period(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            mode=mode.lower(),
            amount=float(amount),
            categories=selected_cats,
            sip_day=sip_day,
            prefer_direct_growth=prefer_direct,
            max_schemes=max_schemes,
        )

    if df.empty:
        st.warning("No results found. Try broader categories or different dates.")
    else:
        st.success(f"Analysed {len(df)} schemes")

        # Display columns
        display_cols = ["rank", "scheme_name", "category", "abs_return_pct", "invested", "final_value"]
        if mode == "SIP" and "xirr_pct" in df.columns:
            display_cols.insert(4, "xirr_pct")
        if "cagr_pct" in df.columns:
            display_cols.insert(4, "cagr_pct")

        st.subheader("Top Ranked Schemes")
        st.dataframe(
            df[display_cols].head(20).style.format({
                "abs_return_pct": "{:.2f}%",
                "xirr_pct": "{:.2f}%",
                "cagr_pct": "{:.2f}%",
                "invested": "₹{:,.0f}",
                "final_value": "₹{:,.0f}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # Portfolio suggestion
        st.subheader("Suggested Portfolio")
        portfolio = analyzer.suggest_portfolio(
            df,
            max_funds=max_funds,
            max_exposure_per_fund=max_exposure,
            min_exposure_per_fund=min_exposure,
        )

        if not portfolio.empty:
            st.dataframe(
                portfolio.style.format({
                    "abs_return_pct": "{:.2f}%",
                    "xirr_pct": "{:.2f}%",
                    "weight": "{:.1%}",
                }),
                use_container_width=True,
                hide_index=True,
            )

            # Simple allocation chart
            if "weight" in portfolio.columns:
                st.bar_chart(portfolio.set_index("scheme_name")["weight"])

        # Download
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Download full results (CSV)",
            data=csv,
            file_name=f"mf_optimiser_{start_date}_{end_date}.csv",
            mime="text/csv",
        )

else:
    st.info("👈 Set your parameters in the sidebar and click **Run Optimiser**.")
    st.markdown("""
    **Tips:**
    - Direct Growth plans have lower expense ratios.
    - Longer date ranges give more meaningful results.
    - First run can be slow because it fetches live NAV data.
    - Past performance is not indicative of future returns.
    """)

st.caption("Data source: mfapi.in (AMFI-based). Not investment advice.")

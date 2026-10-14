# Indian Mutual Fund Best Investment Finder

Finds the best-performing Indian mutual funds between any two dates for **Lumpsum** or **SIP** investments.

Supports category filters (Large Cap, Mid Cap, Small Cap, Flexi Cap, etc.) and basic portfolio exposure constraints (max/min per fund).

## Data Source

Uses the free public API from [mfapi.in](https://www.mfapi.in/) (no API key required).  
- Scheme search  
- Historical NAV with date range (`startDate` / `endDate` in YYYY-MM-DD)  
- Metadata including `scheme_category` (e.g. "Equity Scheme - Large Cap Fund")

Alternatives considered: Official AMFI bulk downloads, TigZig full-history API, mftool library.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

Edit the parameters in `main()` at the bottom of `mf_best_investment.py`, then run:

```bash
python mf_best_investment.py
```

### Key Parameters

- `start_date`, `end_date`: YYYY-MM-DD
- `mode`: `"lumpsum"` or `"sip"`
- `amount`: total for lumpsum, monthly amount for SIP
- `categories`: list from keys in `CATEGORY_KEYWORDS` (large_cap, mid_cap, small_cap, flexi_cap, multi_cap, elss, index, ...)
- `sip_day`: day of month for SIP (1–28)
- `prefer_direct_growth`: True to favor lower-cost Direct Growth options
- Exposure constraints in `suggest_portfolio()`: `max_exposure_per_fund`, `min_exposure_per_fund`, `max_funds`

### Output

- Ranked table of schemes by absolute return (and XIRR for SIP)
- Suggested simple portfolio with weights
- Full results saved to `mf_analysis_results.csv`

## Calculations

- **Lumpsum**: Units bought at nearest NAV ≤ start date; value at end date. Absolute return + CAGR.
- **SIP**: Monthly purchases on/near specified day using nearest prior NAV; total units × end NAV. Absolute return + XIRR (Newton-Raphson).
- Non-trading days handled by nearest prior NAV.

## Extending

- Add more category keywords.
- Implement full portfolio optimization (e.g. with PuLP or scipy) under category min/max exposure.
- Cache scheme metadata locally to reduce API calls.
- Add risk metrics (volatility, max drawdown) once you have full daily series.
- Prefer Growth plans (NAV already reinvests dividends).

## Notes / Limitations

- Rate limiting: code adds delays; for large scans consider caching or bulk AMFI downloads.
- Historical data availability varies by scheme (newer schemes have shorter history).
- Past performance is not indicative of future results. This is for analysis only, not advice.
- XIRR implementation is a basic Newton method; results should be cross-checked for edge cases.
- For very long date ranges or hundreds of schemes, consider downloading bulk NAV history from AMFI or Tig Zig.

## Example Categories Supported

- large_cap, mid_cap, small_cap
- large_mid, flexi_cap, multi_cap
- focused, elss, index
- debt, hybrid

## Make it Live (Streamlit Web App)

A ready-to-deploy Streamlit UI is in `app.py`.

### Local testing
```bash
pip install -r requirements.txt
streamlit run app.py
```

### Deploy for free on Streamlit Community Cloud

1. Create a new public GitHub repository.
2. Upload these files:
   - `app.py`
   - `mf_best_investment.py`
   - `requirements.txt`
   - `README.md`
3. Go to [share.streamlit.io](https://share.streamlit.io)
4. Sign in with GitHub → New app → Select your repo.
5. Main file: `app.py`
6. Deploy.

You’ll get a public URL like `https://yourname-mf-optimiser.streamlit.app`.

**Notes for deployment:**
- First run after deployment can be slow (cold start + API calls).
- The free tier has resource limits; keep `max_schemes` reasonable.
- Add a `.streamlit/config.toml` if you want to hide the menu or set a theme.

### Optional: hide Streamlit branding
Create `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#FF4B4B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"

[client]
toolbarMode = "minimal"
```


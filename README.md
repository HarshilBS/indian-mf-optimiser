# Indian Mutual Fund Optimiser

Streamlit app to find and optimise the best-performing Indian mutual funds under category, plan, and weight constraints.

## Features
- Filter by SEBI category, Direct/Regular plan, Growth/IDCW option
- Compute Total Return, CAGR, Volatility, Sharpe, Sortino, Max Drawdown between any two dates
- Rank funds by chosen metric
- Constraint-based portfolio selection (max funds, min/max weights)
- Optional Mixed-Integer Linear Programming (PuLP) for optimal allocation
- Interactive performance charts
- Data from AMFI via `mftool` (mfapi.in)

## Data
Uses the classification file `schemes.csv` (scheme code, AMC, category, plan, Growth/IDCW).

**Automatic update every 2 weeks:**  
A GitHub Action (`.github/workflows/update-schemes.yml`) downloads  
https://portal.amfiindia.com/spages/NAVAll.txt  
and regenerates `schemes.csv` on the 1st and 15th of each month.  
You can also run it manually:

```bash
python update_schemes.py
```

Historical NAVs are still fetched live via `mftool` / mfapi.in.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes
- Prefer **Direct + Growth** plans for lower cost and compounding.
- Past performance ≠ future results. This is a tool, not advice.
- For production, add caching, error handling, and rate-limit awareness for API calls.
- Update the classification CSV periodically from AMFI or AMC sources.

Inspired by earlier app: https://indian-mf-optimiser-byhbs.streamlit.app/

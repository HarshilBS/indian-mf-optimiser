#!/usr/bin/env python3
"""
Indian Mutual Fund Best Investment Finder
Supports Lumpsum and SIP between any two dates.
Uses free mfapi.in API for NAV data.
Filters by categories (Large Cap, Mid Cap, Small Cap, etc.), Direct/Growth preferred.
Constraints: category filters, optional max funds, exposure limits for simple portfolio.
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time
from typing import List, Dict, Optional, Tuple
import math

BASE_URL = "https://api.mfapi.in"

# Comprehensive SEBI category keywords (Equity, Debt, Hybrid, etc.)
CATEGORY_KEYWORDS = {
    # Equity
    "large_cap": ["Large Cap"],
    "mid_cap": ["Mid Cap"],
    "small_cap": ["Small Cap"],
    "large_mid": ["Large & Mid Cap", "Large and Mid Cap"],
    "flexi_cap": ["Flexi Cap", "Flexicap"],
    "multi_cap": ["Multi Cap", "Multicap"],
    "focused": ["Focused"],
    "value_contra": ["Value", "Contra"],
    "dividend_yield": ["Dividend Yield"],
    "elss": ["ELSS", "Tax Saver"],
    "sectoral_thematic": ["Sectoral", "Thematic"],
    "index": ["Index"],
    # Debt
    "overnight": ["Overnight"],
    "liquid": ["Liquid"],
    "ultra_short": ["Ultra Short", "Ultra-Short"],
    "low_duration": ["Low Duration"],
    "money_market": ["Money Market"],
    "short_duration": ["Short Duration"],
    "medium_duration": ["Medium Duration"],
    "medium_to_long": ["Medium to Long"],
    "long_duration": ["Long Duration"],
    "dynamic_bond": ["Dynamic Bond"],
    "corporate_bond": ["Corporate Bond"],
    "credit_risk": ["Credit Risk"],
    "banking_psu": ["Banking and PSU", "Banking & PSU"],
    "gilt": ["Gilt"],
    "gilt_10y": ["10 Year Constant Maturity", "Constant Maturity"],
    "floater": ["Floater"],
    # Hybrid
    "conservative_hybrid": ["Conservative Hybrid", "Conservative Allocation"],
    "balanced_hybrid": ["Balanced Hybrid", "Balanced"],
    "aggressive_hybrid": ["Aggressive Hybrid", "Aggressive"],
    "balanced_advantage": ["Balanced Advantage", "Dynamic Asset Allocation"],
    "multi_asset": ["Multi Asset", "Multi-Asset"],
    "arbitrage": ["Arbitrage"],
    "equity_savings": ["Equity Savings"],
    # Others
    "solution_oriented": ["Retirement", "Children"],
    "fof": ["Fund of Funds", "FOF"],
}

# Grouped for UI display
CATEGORY_GROUPS = {
    "Equity": ["large_cap", "mid_cap", "small_cap", "large_mid", "flexi_cap", "multi_cap", "focused", "value_contra", "dividend_yield", "elss", "sectoral_thematic", "index"],
    "Debt": ["overnight", "liquid", "ultra_short", "low_duration", "money_market", "short_duration", "medium_duration", "medium_to_long", "long_duration", "dynamic_bond", "corporate_bond", "credit_risk", "banking_psu", "gilt", "gilt_10y", "floater"],
    "Hybrid": ["conservative_hybrid", "balanced_hybrid", "aggressive_hybrid", "balanced_advantage", "multi_asset", "arbitrage", "equity_savings"],
    "Others": ["solution_oriented", "fof"],
}

class MutualFundAnalyzer:
    def __init__(self, rate_limit_delay: float = 0.2):
        self.delay = rate_limit_delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MFAnalyzer/1.0"})

    def search_schemes(self, query: str) -> List[Dict]:
        """Search schemes by name query."""
        url = f"{BASE_URL}/mf/search"
        resp = self.session.get(url, params={"q": query}, timeout=30)
        resp.raise_for_status()
        time.sleep(self.delay)
        return resp.json()

    def get_scheme_meta_and_nav(
        self, scheme_code: int, start_date: str, end_date: str
    ) -> Optional[Dict]:
        """Fetch meta + NAV history between dates. Dates in YYYY-MM-DD."""
        url = f"{BASE_URL}/mf/{scheme_code}"
        params = {"startDate": start_date, "endDate": end_date}
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            time.sleep(self.delay)
            if data.get("status") != "SUCCESS" or not data.get("data"):
                return None
            return data
        except Exception as e:
            print(f"Error fetching {scheme_code}: {e}")
            return None

    def collect_schemes_by_categories(
        self,
        categories: List[str],
        plan_type: str = "both",  # "direct", "regular", "both"
        max_per_cat: int = 30,
    ) -> Dict[int, Dict]:
        """Collect unique schemes matching categories. Returns {code: meta_preview}."""
        schemes = {}
        for cat in categories:
            keywords = CATEGORY_KEYWORDS.get(cat.lower(), [cat])
            for kw in keywords:
                queries = []
                if plan_type in ("direct", "both"):
                    queries.append(f"{kw} Direct Growth")
                if plan_type in ("regular", "both"):
                    queries.append(f"{kw} Regular Growth")
                    queries.append(f"{kw} Growth")  # fallback for regular
                if not queries:
                    queries.append(kw)

                for query in queries:
                    results = self.search_schemes(query)
                    for s in results[:max_per_cat]:
                        code = s["schemeCode"]
                        if code not in schemes:
                            schemes[code] = {
                                "schemeCode": code,
                                "schemeName": s["schemeName"],
                                "category_query": cat,
                            }
                    time.sleep(self.delay)
        return schemes

    def parse_nav_series(self, nav_data: List[Dict]) -> pd.DataFrame:
        """Convert API NAV list to sorted DataFrame with datetime index."""
        if not nav_data:
            return pd.DataFrame()
        df = pd.DataFrame(nav_data)
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
        df = df.dropna(subset=["date", "nav"]).sort_values("date").reset_index(drop=True)
        return df

    def get_nearest_nav_date(self, df: pd.DataFrame, target_date: datetime) -> Optional[datetime]:
        """Get the actual date of the nearest prior NAV."""
        if df.empty:
            return None
        valid = df[df["date"] <= target_date]
        if valid.empty:
            return None
        return valid.iloc[-1]["date"]

    def get_nearest_nav(self, df: pd.DataFrame, target_date: datetime) -> Optional[float]:
        """Get NAV on or nearest before target_date."""
        if df.empty:
            return None
        valid = df[df["date"] <= target_date]
        if valid.empty:
            return None
        return valid.iloc[-1]["nav"]

    def calculate_lumpsum_return(
        self, df: pd.DataFrame, start: datetime, end: datetime, amount: float = 100000
    ) -> Optional[Dict]:
        """Lumpsum absolute return and CAGR."""
        nav_start = self.get_nearest_nav(df, start)
        nav_end = self.get_nearest_nav(df, end)
        if nav_start is None or nav_end is None or nav_start == 0:
            return None
        units = amount / nav_start
        final_value = units * nav_end
        abs_return = (final_value / amount - 1) * 100
        days = (end - start).days
        if days <= 0:
            return None
        years = days / 365.25
        cagr = ((final_value / amount) ** (1 / years) - 1) * 100 if years > 0 else abs_return
        return {
            "invested": amount,
            "final_value": final_value,
            "abs_return_pct": abs_return,
            "cagr_pct": cagr,
            "units": units,
            "nav_start": nav_start,
            "nav_end": nav_end,
        }

    def generate_sip_dates(
        self,
        start: datetime,
        end: datetime,
        frequency: str = "monthly",  # daily, weekly, fortnightly, monthly, quarterly, semi_annually
        sip_day: int = 1,
    ) -> List[datetime]:
        """Generate SIP dates based on frequency."""
        dates = []
        if frequency == "daily":
            current = start
            while current <= end:
                # Skip weekends roughly (NAV usually not on Sat/Sun, but we use nearest)
                if current.weekday() < 5:
                    dates.append(current)
                current += timedelta(days=1)
            return dates

        if frequency == "weekly":
            # Every 7 days, aligned to sip_day of week if possible, else start
            current = start
            # Move to next preferred weekday if sip_day is 1-7 (Mon-Sun)
            if 1 <= sip_day <= 7:
                days_ahead = (sip_day - 1 - current.weekday()) % 7
                if days_ahead == 0 and current < start:
                    days_ahead = 7
                current += timedelta(days=days_ahead)
            while current <= end:
                dates.append(current)
                current += timedelta(days=7)
            return dates

        if frequency == "fortnightly":
            current = start
            while current <= end:
                dates.append(current)
                current += timedelta(days=14)
            return dates

        # monthly / quarterly / semi_annually
        months_step = {"monthly": 1, "quarterly": 3, "semi_annually": 6}.get(frequency, 1)
        current = start.replace(day=min(sip_day, 28))
        if current < start:
            # advance one step
            month = current.month + months_step
            year = current.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            current = current.replace(year=year, month=month, day=min(sip_day, 28))

        while current <= end:
            dates.append(current)
            month = current.month + months_step
            year = current.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            try:
                current = current.replace(year=year, month=month, day=min(sip_day, 28))
            except ValueError:
                # fallback for short months
                current = current.replace(year=year, month=month, day=28)
        return dates

    def calculate_sip_return(
        self,
        df: pd.DataFrame,
        start: datetime,
        end: datetime,
        amount: float = 10000,
        frequency: str = "monthly",
        sip_day: int = 1,
        return_transactions: bool = False,
    ) -> Optional[Dict]:
        """Simulate SIP of any frequency and compute absolute return + XIRR."""
        sip_dates = self.generate_sip_dates(start, end, frequency, sip_day)
        if not sip_dates:
            return None

        total_invested = 0.0
        total_units = 0.0
        cashflows = []
        transactions = []

        for sip_date in sip_dates:
            nav = self.get_nearest_nav(df, sip_date)
            if nav is None or nav == 0:
                continue
            units = amount / nav
            total_units += units
            total_invested += amount
            cashflows.append((sip_date, -amount))
            if return_transactions:
                transactions.append({
                    "date": sip_date.strftime("%Y-%m-%d"),
                    "type": f"SIP Purchase ({frequency})",
                    "amount": -amount,
                    "nav": round(nav, 4),
                    "units": round(units, 6),
                    "cumulative_units": round(total_units, 6),
                    "cumulative_invested": total_invested,
                })

        nav_end = self.get_nearest_nav(df, end)
        if nav_end is None or total_units == 0:
            return None

        final_value = total_units * nav_end
        abs_return = (final_value / total_invested - 1) * 100 if total_invested > 0 else 0

        cashflows.append((end, final_value))
        xirr = self.compute_xirr(cashflows)

        if return_transactions:
            transactions.append({
                "date": end.strftime("%Y-%m-%d"),
                "type": "Redemption (hypothetical)",
                "amount": round(final_value, 2),
                "nav": round(nav_end, 4),
                "units": round(total_units, 6),
                "cumulative_units": 0,
                "cumulative_invested": total_invested,
            })

        result = {
            "invested": total_invested,
            "final_value": final_value,
            "abs_return_pct": abs_return,
            "xirr_pct": xirr * 100 if xirr is not None else None,
            "units": total_units,
            "num_sips": len([cf for cf in cashflows if cf[1] < 0]),
            "nav_end": nav_end,
            "frequency": frequency,
        }
        if return_transactions:
            result["transactions"] = transactions
        return result

    def generate_equity_curve(
        self,
        df_nav: pd.DataFrame,
        start: datetime,
        end: datetime,
        mode: str,
        amount: float,
        frequency: str = "monthly",
        sip_day: int = 1,
        weight: float = 1.0,
    ) -> pd.DataFrame:
        """Generate daily equity curve for one scheme (lumpsum or SIP of any frequency)."""
        if df_nav.empty:
            return pd.DataFrame()

        df = df_nav[(df_nav["date"] >= start) & (df_nav["date"] <= end)].copy()
        if df.empty:
            return pd.DataFrame()

        if mode == "lumpsum":
            nav_start = self.get_nearest_nav(df_nav, start)
            if not nav_start or nav_start == 0:
                return pd.DataFrame()
            units = (amount * weight) / nav_start
            df["value"] = units * df["nav"]
            return df[["date", "value"]].reset_index(drop=True)

        # SIP mode
        sip_dates = self.generate_sip_dates(start, end, frequency, sip_day)
        if not sip_dates:
            return pd.DataFrame()

        df = df.sort_values("date").reset_index(drop=True)
        cumulative_units = 0.0
        values = []
        dates = []
        sip_idx = 0

        for _, row in df.iterrows():
            current_date = row["date"]
            while sip_idx < len(sip_dates) and sip_dates[sip_idx] <= current_date:
                sip_nav = self.get_nearest_nav(df_nav, sip_dates[sip_idx])
                if sip_nav and sip_nav > 0:
                    units = (amount * weight) / sip_nav
                    cumulative_units += units
                sip_idx += 1
            values.append(cumulative_units * row["nav"])
            dates.append(current_date)

        return pd.DataFrame({"date": dates, "value": values})

    def analyze_custom_portfolio(
        self,
        holdings: List[Dict],
        start_date: str,
        end_date: str,
        collect_transactions: bool = True,
    ) -> pd.DataFrame:
        """
        Analyze a custom investor portfolio.
        holdings: list of dicts with keys:
          - scheme_code or scheme_name
          - mode: "lumpsum" or "sip"
          - amount: float
          - frequency: str (for SIP)
          - sip_day: int (optional)
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        results = []

        for h in holdings:
            code = h.get("scheme_code")
            name_query = h.get("scheme_name")
            if not code and name_query:
                search = self.search_schemes(name_query)
                if search:
                    code = search[0]["schemeCode"]
                    name_query = search[0]["schemeName"]
            if not code:
                continue

            data = self.get_scheme_meta_and_nav(int(code), start_date, end_date)
            if not data:
                continue
            meta = data.get("meta", {})
            df_nav = self.parse_nav_series(data.get("data", []))
            if df_nav.empty:
                continue

            mode = h.get("mode", "sip").lower()
            amount = float(h.get("amount", 10000))
            frequency = h.get("frequency", "monthly")
            sip_day = int(h.get("sip_day", 1))

            if mode == "lumpsum":
                calc = self.calculate_lumpsum_return(df_nav, start, end, amount)
            else:
                calc = self.calculate_sip_return(
                    df_nav, start, end, amount, frequency, sip_day,
                    return_transactions=collect_transactions,
                )

            if calc is None:
                continue

            results.append({
                "scheme_code": code,
                "scheme_name": meta.get("scheme_name", name_query or ""),
                "fund_house": meta.get("fund_house", ""),
                "category": meta.get("scheme_category", ""),
                "mode": mode,
                "frequency": frequency if mode == "sip" else "lumpsum",
                "amount": amount,
                **calc,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # Portfolio totals
        total_invested = df["invested"].sum()
        total_final = df["final_value"].sum()
        df["portfolio_weight"] = df["invested"] / total_invested if total_invested else 0
        return df

    def compute_xirr(self, cashflows: List[Tuple[datetime, float]], guess: float = 0.1) -> Optional[float]:
        """Newton-Raphson XIRR. Cashflows: list of (date, amount) with negatives for investments."""
        if not cashflows or len(cashflows) < 2:
            return None
        # Sort by date
        cashflows = sorted(cashflows, key=lambda x: x[0])
        start_date = cashflows[0][0]

        def npv(rate: float) -> float:
            total = 0.0
            for dt, amt in cashflows:
                days = (dt - start_date).days
                total += amt / ((1 + rate) ** (days / 365.25))
            return total

        def dnpv(rate: float) -> float:
            total = 0.0
            for dt, amt in cashflows:
                days = (dt - start_date).days
                if days == 0:
                    continue
                total -= amt * (days / 365.25) / ((1 + rate) ** (days / 365.25 + 1))
            return total

        rate = guess
        for _ in range(50):
            n = npv(rate)
            dn = dnpv(rate)
            if abs(dn) < 1e-10:
                break
            new_rate = rate - n / dn
            if abs(new_rate - rate) < 1e-7:
                return new_rate
            rate = max(new_rate, -0.99)  # avoid invalid
        return rate if abs(npv(rate)) < 1.0 else None

    def analyze_period(
        self,
        start_date: str,
        end_date: str,
        mode: str = "lumpsum",
        amount: float = 100000,
        categories: Optional[List[str]] = None,
        sip_day: int = 1,
        plan_type: str = "both",  # "direct", "regular", "both"
        max_schemes: int = 100,
        collect_transactions: bool = False,
    ) -> pd.DataFrame:
        """
        Main analysis: find best schemes under filters.
        Returns ranked DataFrame. Optionally includes transaction history for SIP.
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        if start >= end:
            raise ValueError("start_date must be before end_date")

        if categories is None:
            categories = ["large_cap", "mid_cap", "small_cap"]

        scheme_map = self.collect_schemes_by_categories(
            categories, plan_type, max_per_cat=max_schemes // max(1, len(categories))
        )

        results = []
        for code, info in list(scheme_map.items())[:max_schemes]:
            data = self.get_scheme_meta_and_nav(code, start_date, end_date)
            if not data:
                continue
            meta = data.get("meta", {})
            df_nav = self.parse_nav_series(data.get("data", []))
            if df_nav.empty or len(df_nav) < 2:
                continue

            name = meta.get("scheme_name", info["schemeName"])
            # Growth filter
            if "Growth" not in name and "growth" not in name.lower():
                continue

            # Plan type filter
            is_direct = "Direct" in name
            if plan_type == "direct" and not is_direct:
                continue
            if plan_type == "regular" and is_direct:
                continue

            if mode == "lumpsum":
                calc = self.calculate_lumpsum_return(df_nav, start, end, amount)
            else:
                calc = self.calculate_sip_return(
                    df_nav, start, end, amount, sip_day,
                    return_transactions=collect_transactions,
                )

            if calc is None:
                continue

            results.append({
                "scheme_code": code,
                "scheme_name": name,
                "fund_house": meta.get("fund_house", ""),
                "category": meta.get("scheme_category", info.get("category_query", "")),
                "category_key": info.get("category_query", ""),
                "plan": "Direct" if is_direct else "Regular",
                "mode": mode,
                **calc,
            })

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        sort_col = "xirr_pct" if mode == "sip" and "xirr_pct" in df.columns else "abs_return_pct"
        df = df.sort_values(sort_col, ascending=False, na_position="last").reset_index(drop=True)
        df["rank"] = df.index + 1
        return df

    def suggest_portfolio(
        self,
        ranked_df: pd.DataFrame,
        max_funds: int = 5,
        max_exposure_per_fund: float = 0.3,
        min_exposure_per_fund: float = 0.05,
        constraint_mode: str = "count",  # "count" or "percentage"
        category_count_limits: Optional[Dict[str, Tuple[int, int]]] = None,
        category_pct_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> pd.DataFrame:
        """
        Build portfolio.
        constraint_mode:
          - "count": min/max number of funds per category
          - "percentage": min/max % exposure per category (with rebalancing)
        """
        if ranked_df.empty:
            return ranked_df

        df = ranked_df.copy()
        if "category_key" not in df.columns:
            df["category_key"] = df.get("category", "")

        # Select funds
        selected = []
        if constraint_mode == "count" and category_count_limits:
            cat_counts = {k: 0 for k in category_count_limits}
            for _, row in df.iterrows():
                if len(selected) >= max_funds:
                    break
                cat = row.get("category_key", "")
                if cat in category_count_limits:
                    _, max_c = category_count_limits[cat]
                    if cat_counts.get(cat, 0) >= max_c:
                        continue
                selected.append(row)
                if cat in cat_counts:
                    cat_counts[cat] += 1
            # Fill minimums
            for cat, (min_c, _) in category_count_limits.items():
                while cat_counts.get(cat, 0) < min_c and len(selected) < max_funds:
                    already = {r["scheme_code"] for r in selected}
                    candidates = df[(df["category_key"] == cat) & (~df["scheme_code"].isin(already))]
                    if candidates.empty:
                        break
                    row = candidates.iloc[0]
                    selected.append(row)
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
        else:
            # Default / percentage mode: just take top funds
            selected = [row for _, row in df.head(max_funds).iterrows()]

        if not selected:
            return pd.DataFrame()

        top = pd.DataFrame(selected).reset_index(drop=True)
        n = len(top)

        # Initial equal weights
        weights = [1.0 / n] * n

        # Apply per-fund max/min
        weights = [min(max(w, min_exposure_per_fund), max_exposure_per_fund) for w in weights]
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]

        # Percentage rebalancing mode
        if constraint_mode == "percentage" and category_pct_limits:
            # Simple iterative rebalancing toward category targets
            cat_to_indices = {}
            for i, row in top.iterrows():
                cat = row.get("category_key", "")
                cat_to_indices.setdefault(cat, []).append(i)

            for _ in range(10):  # a few rebalancing passes
                cat_sums = {}
                for cat, idxs in cat_to_indices.items():
                    cat_sums[cat] = sum(weights[i] for i in idxs)

                changed = False
                for cat, (min_p, max_p) in category_pct_limits.items():
                    current = cat_sums.get(cat, 0.0)
                    idxs = cat_to_indices.get(cat, [])
                    if not idxs:
                        continue
                    if current > max_p + 1e-6:
                        scale = max_p / current
                        for i in idxs:
                            weights[i] *= scale
                        changed = True
                    elif current < min_p - 1e-6 and current > 0:
                        scale = min_p / current
                        for i in idxs:
                            weights[i] *= scale
                        changed = True
                total = sum(weights)
                if total > 0:
                    weights = [w / total for w in weights]
                if not changed:
                    break

            # Final clip to per-fund limits and renormalize
            weights = [min(max(w, min_exposure_per_fund), max_exposure_per_fund) for w in weights]
            total = sum(weights)
            if total > 0:
                weights = [w / total for w in weights]
        # "percentage_no_rebalance" leaves the equal weights as-is (only per-fund limits applied)

        top["weight"] = weights
        cols = ["rank", "scheme_code", "scheme_name", "category_key", "category", "plan", "abs_return_pct", "weight"]
        if "xirr_pct" in top.columns:
            cols.insert(-1, "xirr_pct")
        return top[[c for c in cols if c in top.columns]]


def main():
    """Example usage. Customize dates, amount, categories, constraints."""
    analyzer = MutualFundAnalyzer(rate_limit_delay=0.3)

    # Example parameters
    start = "2023-01-01"
    end = "2024-12-31"
    mode = "sip"  # or "lumpsum"
    amount = 10000  # monthly for SIP, total for lumpsum
    categories = ["large_cap", "mid_cap", "small_cap", "flexi_cap"]
    sip_day = 5

    print(f"Analyzing best {mode} investments from {start} to {end}...")
    df = analyzer.analyze_period(
        start_date=start,
        end_date=end,
        mode=mode,
        amount=amount,
        categories=categories,
        sip_day=sip_day,
        prefer_direct_growth=True,
        max_schemes=40,
    )

    if not df.empty:
        print("\n=== Top Ranked Schemes ===")
        cols = ["rank", "scheme_name", "category", "abs_return_pct"]
        if mode == "sip":
            cols.append("xirr_pct")
        cols += ["invested", "final_value"]
        print(df[cols].head(15).to_string(index=False))

        print("\n=== Suggested Portfolio (top funds, exposure constrained) ===")
        portfolio = analyzer.suggest_portfolio(
            df,
            max_funds=4,
            max_exposure_per_fund=0.35,
            min_exposure_per_fund=0.10,
        )
        print(portfolio.to_string(index=False))

        # Save results
        df.to_csv("mf_analysis_results.csv", index=False)
        print("\nFull results saved to mf_analysis_results.csv")
    else:
        print("No results. Check dates, categories, or API availability.")


if __name__ == "__main__":
    main()

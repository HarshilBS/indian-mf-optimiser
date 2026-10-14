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

# Category keywords for filtering (SEBI categories)
CATEGORY_KEYWORDS = {
    "large_cap": ["Large Cap"],
    "mid_cap": ["Mid Cap"],
    "small_cap": ["Small Cap"],
    "large_mid": ["Large & Mid Cap", "Large and Mid Cap"],
    "flexi_cap": ["Flexi Cap", "Flexicap"],
    "multi_cap": ["Multi Cap", "Multicap"],
    "focused": ["Focused"],
    "elss": ["ELSS", "Tax Saver"],
    "index": ["Index"],
    "debt": ["Debt"],
    "hybrid": ["Hybrid", "Balanced"],
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
        self, categories: List[str], prefer_direct_growth: bool = True, max_per_cat: int = 30
    ) -> Dict[int, Dict]:
        """Collect unique schemes matching categories. Returns {code: meta_preview}."""
        schemes = {}
        for cat in categories:
            keywords = CATEGORY_KEYWORDS.get(cat.lower(), [cat])
            for kw in keywords:
                query = kw
                if prefer_direct_growth:
                    query = f"{kw} Direct Growth"
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

    def generate_sip_dates(self, start: datetime, end: datetime, sip_day: int = 1) -> List[datetime]:
        """Generate monthly SIP dates on or after sip_day, within range."""
        dates = []
        current = start.replace(day=min(sip_day, 28))  # avoid month-end issues
        if current < start:
            current = (current.replace(day=1) + timedelta(days=32)).replace(day=min(sip_day, 28))
        while current <= end:
            dates.append(current)
            # Next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1, day=min(sip_day, 28))
            else:
                current = current.replace(month=current.month + 1, day=min(sip_day, 28))
        return dates

    def calculate_sip_return(
        self,
        df: pd.DataFrame,
        start: datetime,
        end: datetime,
        monthly_amount: float = 10000,
        sip_day: int = 1,
    ) -> Optional[Dict]:
        """Simulate SIP and compute absolute return + approximate XIRR."""
        sip_dates = self.generate_sip_dates(start, end, sip_day)
        if not sip_dates:
            return None

        total_invested = 0.0
        total_units = 0.0
        cashflows = []  # for XIRR: (date, -amount) and final +value

        for sip_date in sip_dates:
            nav = self.get_nearest_nav(df, sip_date)
            if nav is None or nav == 0:
                continue
            units = monthly_amount / nav
            total_units += units
            total_invested += monthly_amount
            cashflows.append((sip_date, -monthly_amount))

        nav_end = self.get_nearest_nav(df, end)
        if nav_end is None or total_units == 0:
            return None

        final_value = total_units * nav_end
        abs_return = (final_value / total_invested - 1) * 100 if total_invested > 0 else 0

        # Simple XIRR approximation using Newton-Raphson
        cashflows.append((end, final_value))
        xirr = self.compute_xirr(cashflows)

        days = (end - start).days
        years = days / 365.25
        return {
            "invested": total_invested,
            "final_value": final_value,
            "abs_return_pct": abs_return,
            "xirr_pct": xirr * 100 if xirr is not None else None,
            "units": total_units,
            "num_sips": len([cf for cf in cashflows if cf[1] < 0]),
            "nav_end": nav_end,
        }

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
        mode: str = "lumpsum",  # "lumpsum" or "sip"
        amount: float = 100000,  # lumpsum or monthly SIP
        categories: Optional[List[str]] = None,
        sip_day: int = 1,
        prefer_direct_growth: bool = True,
        max_schemes: int = 50,
    ) -> pd.DataFrame:
        """
        Main analysis: find best schemes under filters.
        Returns ranked DataFrame.
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        if start >= end:
            raise ValueError("start_date must be before end_date")

        if categories is None:
            categories = ["large_cap", "mid_cap", "small_cap"]

        print(f"Collecting schemes for categories: {categories} ...")
        scheme_map = self.collect_schemes_by_categories(
            categories, prefer_direct_growth, max_per_cat=max_schemes // max(1, len(categories))
        )
        print(f"Found {len(scheme_map)} candidate schemes. Fetching NAV data...")

        results = []
        for code, info in list(scheme_map.items())[:max_schemes]:
            data = self.get_scheme_meta_and_nav(code, start_date, end_date)
            if not data:
                continue
            meta = data.get("meta", {})
            df_nav = self.parse_nav_series(data.get("data", []))
            if df_nav.empty or len(df_nav) < 2:
                continue

            # Basic filter: prefer Growth, Direct if requested
            name = meta.get("scheme_name", info["schemeName"])
            if prefer_direct_growth and "Direct" not in name:
                continue
            if "Growth" not in name and "growth" not in name.lower():
                continue

            if mode == "lumpsum":
                calc = self.calculate_lumpsum_return(df_nav, start, end, amount)
            else:
                calc = self.calculate_sip_return(df_nav, start, end, amount, sip_day)

            if calc is None:
                continue

            results.append({
                "scheme_code": code,
                "scheme_name": name,
                "fund_house": meta.get("fund_house", ""),
                "category": meta.get("scheme_category", info.get("category_query", "")),
                "mode": mode,
                **calc,
            })

        if not results:
            print("No valid results found. Try broader categories or different dates.")
            return pd.DataFrame()

        df = pd.DataFrame(results)
        # Rank by absolute return (or XIRR for SIP)
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
        category_limits: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> pd.DataFrame:
        """
        Simple portfolio: take top funds, equal weight or constrained.
        category_limits: {"Large Cap": (0.2, 0.5), ...} min,max fraction.
        """
        if ranked_df.empty:
            return ranked_df

        top = ranked_df.head(max_funds).copy()
        n = len(top)
        if n == 0:
            return top

        # Start with equal weight, clip to max, redistribute if needed
        weights = [1.0 / n] * n
        weights = [min(w, max_exposure_per_fund) for w in weights]
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        # Enforce min if possible
        for i in range(n):
            if weights[i] < min_exposure_per_fund and total > 0:
                weights[i] = min_exposure_per_fund
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]

        top["weight"] = weights
        top["allocated_amount"] = top["invested"] * top["weight"] if "invested" in top else None
        return top[["rank", "scheme_name", "category", "abs_return_pct", "weight"] + 
                   (["xirr_pct"] if "xirr_pct" in top.columns else [])]


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

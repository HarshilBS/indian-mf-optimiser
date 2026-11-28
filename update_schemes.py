#!/usr/bin/env python3
"""
Parse AMFI NAVAll.txt and generate an updated schemes.csv
compatible with the Indian MF Optimiser app.

Source: https://portal.amfiindia.com/spages/NAVAll.txt
Format (as of late 2026):
  Header: Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
  Section headers: Open Ended Schemes(Equity Scheme - Large Cap Fund)
  AMC headers: Axis Mutual Fund
  Data rows: code;isin_payout;isin_reinv;name;plan;option;nav;date

Usage:
  python update_schemes.py                  # download + write schemes.csv
  python update_schemes.py --input file.txt # parse local file
  python update_schemes.py --output out.csv
"""

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
USER_AGENT = "Mozilla/5.0 (compatible; MF-Optimiser/1.0; +https://github.com/HarshilBS/indian-mf-optimiser)"


def download_navall(url: str = NAVALL_URL) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.text


def clean_category(section: str) -> tuple[str, str]:
    """
    From 'Open Ended Schemes(Equity Scheme - Large Cap Fund)'
    return (full_category, short_category)
    """
    section = section.strip()
    # Extract the part inside parentheses if present
    m = re.search(r"\((.+)\)", section)
    inner = m.group(1).strip() if m else section

    # Full category for display (closer to existing style)
    full = inner
    # Prefer a readable form
    if " - " in inner:
        full = inner
    else:
        full = f"{section.split('(')[0].strip()} - {inner}" if "(" in section else inner

    # Short category: usually the last part after " - "
    if " - " in inner:
        short = inner.split(" - ")[-1].strip()
    else:
        short = inner.strip()

    # Normalise common variants
    replacements = {
        "Childrens' Fund": "Children's Fund",
        "Childrens Fund": "Children's Fund",
        "ELSS- Tax Saver Fund": "ELSS",
        "ELSS - Tax Saver Fund": "ELSS",
        "Sectoral/ Thematic": "Sectoral/Thematic",
    }
    for old, new in replacements.items():
        short = short.replace(old, new)

    # Collapse multiple spaces
    short = re.sub(r"\s+", " ", short).strip()

    return full, short


def infer_plan_from_name(name: str, plan_raw: str) -> str:
    """If Plan column is empty, try to guess from scheme name."""
    classified = classify_plan(plan_raw)
    if classified != "Unknown":
        return classified
    n = (name or "").lower()
    if "direct" in n:
        return "Direct"
    if "regular" in n:
        return "Regular"
    return "Unknown"


def classify_plan(plan: str) -> str:
    p = (plan or "").strip().lower()
    if "direct" in p:
        return "Direct"
    if "regular" in p:
        return "Regular"
    if not p or p in ("-", "na", "null"):
        return "Unknown"
    return plan.strip()


def classify_option(option: str, name: str = "") -> str:
    o = (option or "").strip().lower()
    if "growth" in o:
        return "Growth"
    if any(x in o for x in ("idcw", "dividend", "payout", "reinvest", "income distribution")):
        return "IDCW"
    # Fallback to name
    n = (name or "").lower()
    if "growth" in n and "idcw" not in n and "dividend" not in n:
        return "Growth"
    if any(x in n for x in ("idcw", "dividend", "payout", "reinvest")):
        return "IDCW"
    if not o or o in ("-", "na", "null"):
        return "Unknown"
    return "IDCW"


def parse_navall(text: str) -> list[dict]:
    lines = text.splitlines()
    current_category = ""
    current_short = ""
    current_amc = ""

    rows = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # Section header (contains "Schemes(" and no semicolon)
        if "Schemes(" in line and ";" not in line:
            current_category, current_short = clean_category(line)
            current_amc = ""  # reset AMC when section changes
            continue

        # AMC header (no semicolon, ends with Mutual Fund or similar, not a data row)
        if ";" not in line and re.search(r"Mutual Fund|Asset Management|AMC", line, re.I):
            current_amc = line.strip()
            continue

        # Data row: starts with digits and has semicolons
        if re.match(r"^\d+;", line):
            parts = line.split(";")
            # Expected 8 fields after the format change (Plan + Option added)
            # Older format had 6. Be flexible.
            if len(parts) < 6:
                continue

            code = parts[0].strip()
            isin_payout = parts[1].strip() if len(parts) > 1 else ""
            isin_reinv = parts[2].strip() if len(parts) > 2 else ""
            name = parts[3].strip() if len(parts) > 3 else ""

            if len(parts) >= 8:
                plan_raw = parts[4].strip()
                option_raw = parts[5].strip()
                nav = parts[6].strip()
                date = parts[7].strip()
            else:
                # fallback to old 6-column format
                plan_raw = ""
                option_raw = ""
                nav = parts[4].strip() if len(parts) > 4 else ""
                date = parts[5].strip() if len(parts) > 5 else ""

            # Skip zero / invalid NAV
            try:
                if float(nav) <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            plan = infer_plan_from_name(name, plan_raw)
            growth_idcw = classify_option(option_raw, name)

            # Prefer a meaningful category
            scheme_category = current_category or "Uncategorised"
            category_short = current_short or "Other"

            rows.append({
                "Code": code,
                "Scheme Category": scheme_category,
                "AMC": current_amc or "Unknown",
                "Scheme Name": name,
                "Cateogory": category_short,  # preserve the existing typo for compatibility
                "Plan": plan,
                "Growth/IDCW": growth_idcw,
                # extra useful fields (not written by default)
                "_isin_payout": isin_payout,
                "_isin_reinv": isin_reinv,
                "_nav": nav,
                "_date": date,
                "_plan_raw": plan_raw,
                "_option_raw": option_raw,
            })

    return rows


def write_schemes_csv(rows: list[dict], path: Path, include_extra: bool = False):
    # Columns expected by the app
    fieldnames = ["Code", "Scheme Category", "AMC", "Scheme Name", "Cateogory", "Plan", "Growth/IDCW"]
    if include_extra:
        fieldnames += ["ISIN_Payout", "ISIN_Reinv", "Latest_NAV", "NAV_Date", "Plan_Raw", "Option_Raw"]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in fieldnames}
            if include_extra:
                out["ISIN_Payout"] = r.get("_isin_payout", "")
                out["ISIN_Reinv"] = r.get("_isin_reinv", "")
                out["Latest_NAV"] = r.get("_nav", "")
                out["NAV_Date"] = r.get("_date", "")
                out["Plan_Raw"] = r.get("_plan_raw", "")
                out["Option_Raw"] = r.get("_option_raw", "")
            writer.writerow(out)


def main():
    parser = argparse.ArgumentParser(description="Update schemes.csv from AMFI NAVAll.txt")
    parser.add_argument("--input", help="Local NAVAll.txt file (skip download)")
    parser.add_argument("--output", default="schemes.csv", help="Output CSV path")
    parser.add_argument("--extra", action="store_true", help="Include ISIN, NAV, date columns")
    args = parser.parse_args()

    if args.input:
        print(f"Reading local file: {args.input}")
        text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    else:
        print(f"Downloading {NAVALL_URL} ...")
        text = download_navall()
        print(f"Downloaded {len(text):,} characters")

    print("Parsing ...")
    rows = parse_navall(text)
    print(f"Parsed {len(rows):,} scheme rows")

    if not rows:
        print("ERROR: No rows parsed. Format may have changed.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    write_schemes_csv(rows, out_path, include_extra=args.extra)
    print(f"Wrote {len(rows):,} rows to {out_path}")

    # Quick stats
    from collections import Counter
    cats = Counter(r["Cateogory"] for r in rows)
    print("\nTop categories:")
    for cat, n in cats.most_common(15):
        print(f"  {n:5d}  {cat}")

    plans = Counter(r["Plan"] for r in rows)
    print("\nPlans:", dict(plans))
    opts = Counter(r["Growth/IDCW"] for r in rows)
    print("Options:", dict(opts))


if __name__ == "__main__":
    main()

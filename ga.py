# ga.py
# Data access layer for GA4 Insights Copilot.
# - Supports real GA4 via the Analytics Data API
# - Supports MOCK_MODE using a local CSV (for instant demos)

import os
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "").strip()
USE_SA = os.getenv("GA4_USE_SERVICE_ACCOUNT", "false").lower() == "true"
SA_PATH = os.getenv("GA4_SA_PATH", "keys/service_account.json")
MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

def default_dates(days: int = 28):
    """Return (start_iso, end_iso) covering the last `days` days."""
    d0 = date.today()
    return (d0 - timedelta(days=days)).isoformat(), d0.isoformat()

def run_ga_report(query: dict) -> pd.DataFrame:
    """
    query = {
      "dimensions": ["sessionDefaultChannelGroup", ...],
      "metrics": ["totalUsers", ...],
      "date_range": {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"},
      "filters": "... (optional)"
    }
    Returns a pandas DataFrame.
    """
    if MOCK_MODE:
        return _run_mock(query)

    # ---- Real GA4 path ----
    if not PROPERTY_ID:
            raise ValueError("GA4_PROPERTY_ID is not set. Check your .env file.")

    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric
    )
    if USE_SA:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(SA_PATH)
        client = BetaAnalyticsDataClient(credentials=creds)
    else:
        # Application Default Credentials (ADC) if you’ve set them up.
        client = BetaAnalyticsDataClient()

    dims = [Dimension(name=d) for d in query.get("dimensions", [])]
    mets = [Metric(name=m) for m in query.get("metrics", [])]
    if not dims or not mets:
        raise ValueError("Both dimensions and metrics must be specified.")

    start = (query.get("date_range", {}) or {}).get("start_date")
    end   = (query.get("date_range", {}) or {}).get("end_date")
    if not start or not end:
        start, end = default_dates(28)

    req = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=dims,
        metrics=mets,
        date_ranges=[DateRange(start_date=start, end_date=end)],
        limit=10000
    )
    # NOTE: Filter parsing omitted for brevity.

    resp = client.run_report(req)

    # Convert to DataFrame
    rows = []
    for r in resp.rows:
        row = {}
        for i, d in enumerate(resp.dimension_headers):
            row[d.name] = r.dimension_values[i].value
        for i, m in enumerate(resp.metric_headers):
            # Convert numeric strings to float safely
            val = r.metric_values[i].value
            try:
                row[m.name] = float(val)
            except Exception:
                row[m.name] = val
        rows.append(row)

    return pd.DataFrame(rows)

# ---------------- Mock mode ----------------

def _run_mock(query: dict) -> pd.DataFrame:
    """
    Minimal mock loader that reads mock_data.csv in the project root.
    It expects columns that match your query (e.g., dimensions/metrics).
    If both dimensions and metrics exist, it groups & sums metrics by dimensions.
    """
    csv_path = "mock_data.csv"
    if not os.path.exists(csv_path):
        # Provide a friendly hint
        raise FileNotFoundError(
            "mock_data.csv not found. Create one or set MOCK_MODE=false in .env"
        )

    df = pd.read_csv(csv_path)

    dims = query.get("dimensions", []) or []
    mets = query.get("metrics", []) or []

    # Keep only requested columns that actually exist in the CSV
    keep = [c for c in dims + mets if c in df.columns]
    if not keep:
        return pd.DataFrame()

    out = df[keep].copy()

    if dims and mets:
        agg = {m: "sum" for m in mets if m in out.columns}
        if agg:
            out = out.groupby(dims, dropna=False).agg(agg).reset_index()

    return out

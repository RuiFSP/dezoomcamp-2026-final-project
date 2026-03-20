"""@bruin
name: ingest.raw_github_events
description: "Load GitHub Archive NDJSON from GCS into BigQuery raw table (data warehouse layer)"
image: python:3.12
depends:
    - ingest.fetch_to_gcs
@bruin"""

import os
from datetime import datetime, timedelta, timezone

from src.ingest_github_events import gcs_uri_for_date, load_to_bigquery

_raw = os.environ.get("BRUIN_START_DATE", "")
date = _raw[:10] if _raw else (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
gcs_uri = gcs_uri_for_date(date)
rows = load_to_bigquery(gcs_uri, date)

print(f"Loaded {rows:,} rows for {date} → BigQuery")

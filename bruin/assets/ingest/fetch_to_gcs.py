"""@bruin
name: ingest.fetch_to_gcs
description: "Download GitHub Archive for the run date and upload to GCS (data lake layer)"
image: python:3.12
@bruin"""

import os
from datetime import datetime, timedelta, timezone

from src.ingest_github_events import fetch_to_gcs

# Bruin injects BRUIN_START_DATE as "YYYY-MM-DDTHH:MM:SSZ"; fall back to yesterday UTC
_raw = os.environ.get("BRUIN_START_DATE", "")
date = _raw[:10] if _raw else (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
gcs_uri = fetch_to_gcs(date)

if gcs_uri is None:
    raise RuntimeError(f"No GitHub Archive data found for {date}")

print(f"Data lake: {gcs_uri}")

"""Ingestion module for downloading and loading GitHub Archive data.

This module handles:
- Downloading GitHub Archive NDJSON files from gharchive.org
- Uploading raw files to GCS
- Loading data from GCS into BigQuery

Usage:
    python -m src.ingest_github_events
    python -m src.ingest_github_events --date 2026-03-20
"""

import gzip
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.api_core.retry import Retry
from google.cloud import bigquery, storage
from google.cloud.exceptions import NotFound

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Config from environment
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gh-dezoomcamp")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "gh-dezoomcamp-raw-events")
BQ_DATASET_ID = os.getenv("BQ_DATASET_ID", "gh_analytics")
BQ_TABLE_ID = "raw_github_events"
REGION = os.getenv("GCP_REGION", "europe-west1")
GCS_UPLOAD_TIMEOUT_SECONDS = int(os.getenv("GCS_UPLOAD_TIMEOUT_SECONDS", "3600"))
GCS_UPLOAD_RETRY_DEADLINE_SECONDS = int(
    os.getenv("GCS_UPLOAD_RETRY_DEADLINE_SECONDS", "7200")
)
GCS_UPLOAD_CHUNK_SIZE_MB = int(os.getenv("GCS_UPLOAD_CHUNK_SIZE_MB", "16"))
GCS_UPLOAD_CHUNK_SIZE_BYTES = GCS_UPLOAD_CHUNK_SIZE_MB * 1024 * 1024

# GitHub Archive URL pattern: one file per hour (0–23)
GH_ARCHIVE_URL = "https://data.gharchive.org/{date}-{hour}.json.gz"

# BigQuery schema for raw events
RAW_TABLE_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("type", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("actor", "JSON", mode="NULLABLE"),
    bigquery.SchemaField("repo", "JSON", mode="NULLABLE"),
    bigquery.SchemaField("payload", "JSON", mode="NULLABLE"),
    bigquery.SchemaField("public", "BOOLEAN", mode="NULLABLE"),
    bigquery.SchemaField("created_at", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("org", "JSON", mode="NULLABLE"),
]


def resolve_hour_window(
    start_hour: int | None = None, max_hours: int | None = None
) -> tuple[int, int]:
    """Resolve and validate the GH Archive hour window to ingest.

    Defaults come from env vars:
      - GH_ARCHIVE_START_HOUR (default: 0)
      - GH_ARCHIVE_MAX_HOURS (default: 24)
    """
    start = (
        start_hour
        if start_hour is not None
        else int(os.getenv("GH_ARCHIVE_START_HOUR", "0"))
    )
    count = (
        max_hours
        if max_hours is not None
        else int(os.getenv("GH_ARCHIVE_MAX_HOURS", "24"))
    )

    if start < 0 or start > 23:
        raise ValueError(f"GH_ARCHIVE_START_HOUR must be between 0 and 23, got {start}")
    if count < 1 or count > 24:
        raise ValueError(f"GH_ARCHIVE_MAX_HOURS must be between 1 and 24, got {count}")
    if start + count > 24:
        raise ValueError(
            f"Hour window exceeds day boundary: start={start}, max_hours={count}"
        )

    return start, count


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching
# ─────────────────────────────────────────────────────────────────────────────


def fetch_github_archive(date: str, hour: int, output_path: str) -> bool:
    """Download one hour of GitHub Archive data to a local file.

    Args:
        date: Date string in YYYY-MM-DD format.
        hour: Hour (0-23).
        output_path: Local path to write decompressed NDJSON.

    Returns:
        True if download succeeded, False if file not found (future date).
    """
    url = GH_ARCHIVE_URL.format(date=date, hour=hour)
    logger.info(f"Downloading: {url}")

    response = requests.get(url, timeout=60, stream=True)

    if response.status_code == 404:
        logger.warning(f"File not found (possibly future date): {url}")
        return False

    response.raise_for_status()

    with open(output_path, "wb") as f:
        with gzip.GzipFile(fileobj=response.raw) as gz:
            f.write(gz.read())

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    logger.info(f"Downloaded {size_mb:.1f}MB → {output_path}")
    return True


def fetch_day(
    date: str,
    output_path: str,
    start_hour: int | None = None,
    max_hours: int | None = None,
) -> int:
    """Download all available hours for a given date into one NDJSON file.

    Args:
        date: Date string in YYYY-MM-DD format.
        output_path: Local path to write combined NDJSON.

    Args:
        start_hour: First hour to ingest (0-23). Defaults to env/config.
        max_hours: Number of hours to ingest from start_hour. Defaults to env/config.

    Returns:
        Total number of records written.
    """
    total_records = 0
    start, count = resolve_hour_window(start_hour=start_hour, max_hours=max_hours)
    end_exclusive = start + count

    logger.info(
        "Fetching GH Archive window: date=%s, start_hour=%s, max_hours=%s",
        date,
        start,
        count,
    )

    with open(output_path, "w") as out_file:
        for hour in range(start, end_exclusive):
            with tempfile.NamedTemporaryFile(suffix=".ndjson", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                found = fetch_github_archive(date, hour, tmp_path)
                if not found:
                    continue

                with open(tmp_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            out_file.write(line + "\n")
                            total_records += 1
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    logger.info(f"Fetched {total_records:,} records for {date}")
    return total_records


# ─────────────────────────────────────────────────────────────────────────────
# GCS upload
# ─────────────────────────────────────────────────────────────────────────────


def gcs_object_exists(date: str) -> bool:
    """Check whether a date has any raw objects in GCS (hourly or legacy daily)."""
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)

    legacy_blob = bucket.blob(f"raw/github_events/{date}/events.ndjson")
    if legacy_blob.exists(client):
        return True

    prefix = f"raw/github_events/{date}/hours/"
    return any(client.list_blobs(BUCKET_NAME, prefix=prefix, max_results=1))


def gcs_hour_blob_name(date: str, hour: int) -> str:
    return f"raw/github_events/{date}/hours/{hour:02d}.ndjson"


def gcs_hour_uri(date: str, hour: int) -> str:
    return f"gs://{BUCKET_NAME}/{gcs_hour_blob_name(date, hour)}"


def gcs_legacy_daily_uri(date: str) -> str:
    return f"gs://{BUCKET_NAME}/raw/github_events/{date}/events.ndjson"


def gcs_hourly_wildcard_uri_for_date(date: str) -> str:
    return f"gs://{BUCKET_NAME}/raw/github_events/{date}/hours/*.ndjson"


def gcs_hour_object_exists(date: str, hour: int) -> bool:
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    return bucket.blob(gcs_hour_blob_name(date, hour)).exists(client)


def gcs_any_hour_objects_exist(date: str) -> bool:
    client = storage.Client(project=PROJECT_ID)
    prefix = f"raw/github_events/{date}/hours/"
    return any(client.list_blobs(BUCKET_NAME, prefix=prefix, max_results=1))


def upload_to_gcs(local_path: str, date: str, hour: int | None = None) -> str:
    """Upload a local file to GCS under the raw/github_events/{date}/ prefix.

    Args:
        local_path: Path to the local NDJSON file.
        date: Date string used to partition the GCS path.
        hour: Optional hour partition; when provided, uploads to hourly layout.

    Returns:
        GCS URI of the uploaded file (gs://bucket/path).
    """
    client = storage.Client(project=PROJECT_ID)
    bucket = client.bucket(BUCKET_NAME)
    blob_name = (
        gcs_hour_blob_name(date, hour)
        if hour is not None
        else f"raw/github_events/{date}/events.ndjson"
    )
    blob = bucket.blob(blob_name)
    blob.chunk_size = GCS_UPLOAD_CHUNK_SIZE_BYTES
    retry = Retry(deadline=GCS_UPLOAD_RETRY_DEADLINE_SECONDS)

    logger.info(
        "Uploading to gs://%s/%s (chunk_size=%sMB, timeout=%ss)",
        BUCKET_NAME,
        blob_name,
        GCS_UPLOAD_CHUNK_SIZE_MB,
        GCS_UPLOAD_TIMEOUT_SECONDS,
    )
    blob.upload_from_filename(
        local_path,
        content_type="application/x-ndjson",
        timeout=GCS_UPLOAD_TIMEOUT_SECONDS,
        retry=retry,
    )

    gcs_uri = f"gs://{BUCKET_NAME}/{blob_name}"
    size_mb = Path(local_path).stat().st_size / (1024 * 1024)
    logger.info(f"Uploaded {size_mb:.1f}MB → {gcs_uri}")
    return gcs_uri


# ─────────────────────────────────────────────────────────────────────────────
# BigQuery
# ─────────────────────────────────────────────────────────────────────────────


def ensure_table_exists(client: bigquery.Client) -> None:
    """Create the raw_github_events table if it does not exist.

    Args:
        client: Authenticated BigQuery client.
    """
    table_ref = f"{PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}"
    try:
        client.get_table(table_ref)
        logger.info(f"Table already exists: {table_ref}")
    except NotFound:
        logger.info(f"Creating table: {table_ref}")
        table = bigquery.Table(table_ref, schema=RAW_TABLE_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="created_at",
        )
        client.create_table(table)
        logger.info(f"Table created: {table_ref}")


def delete_date_from_bigquery(
    client: bigquery.Client, table_ref: str, date: str
) -> int:
    """Delete existing rows for a target date to make re-runs idempotent."""
    delete_sql = f"""
        DELETE FROM `{table_ref}`
        WHERE DATE(created_at) = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("target_date", "DATE", date),
        ]
    )
    query_job = client.query(delete_sql, job_config=job_config)
    query_job.result()
    return query_job.num_dml_affected_rows or 0


def load_to_bigquery(gcs_uri: str, date: str) -> int:
    """Load a GCS NDJSON file into BigQuery, replacing data for that date.

    Idempotent: uses WRITE_TRUNCATE on the date partition so re-runs are safe.

    Args:
        gcs_uri: GCS URI of the NDJSON file.
        date: Date string (YYYY-MM-DD) used to scope the load job.

    Returns:
        Number of rows loaded.
    """
    client = bigquery.Client(project=PROJECT_ID)
    ensure_table_exists(client)

    table_ref = f"{PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_ID}"

    rows_deleted = delete_date_from_bigquery(client, table_ref, date)
    logger.info(f"Deleted {rows_deleted:,} existing rows for {date} from {table_ref}")

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=RAW_TABLE_SCHEMA,
        ignore_unknown_values=True,
        max_bad_records=100,
    )

    logger.info(f"Loading {gcs_uri} → {table_ref}")
    load_job = client.load_table_from_uri(gcs_uri, table_ref, job_config=job_config)
    load_job.result()  # Wait for completion

    table = client.get_table(table_ref)
    rows_loaded = load_job.output_rows
    logger.info(
        f"Loaded {rows_loaded:,} rows → {table_ref} (total: {table.num_rows:,})"
    )
    return rows_loaded


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration helpers (used by Bruin Python assets individually)
# ─────────────────────────────────────────────────────────────────────────────


def gcs_uri_for_date(date: str) -> str:
    """Return the canonical day-level load URI for hourly-ingested objects."""
    return gcs_hourly_wildcard_uri_for_date(date)


def fetch_to_gcs(
    date: str,
    start_hour: int | None = None,
    max_hours: int | None = None,
) -> str | None:
    """Download GitHub Archive for *date* and upload hourly objects to GCS.

    Args:
        date: Date string in YYYY-MM-DD format.

    Args:
        start_hour: First hour to ingest (0-23). Defaults to env/config.
        max_hours: Number of hours to ingest from start_hour. Defaults to env/config.

    Returns:
        GCS URI for loading the date (hourly wildcard or legacy daily),
        or None if no records were found and no prior objects exist.
    """
    start, count = resolve_hour_window(start_hour=start_hour, max_hours=max_hours)
    end_exclusive = start + count

    records_fetched = 0
    uploaded_hours = 0
    existing_hours = 0

    for hour in range(start, end_exclusive):
        if gcs_hour_object_exists(date, hour):
            existing_hours += 1
            logger.info(
                "GCS hour object already exists for %s hour=%02d. Reusing %s",
                date,
                hour,
                gcs_hour_uri(date, hour),
            )
            continue

        with tempfile.NamedTemporaryFile(
            suffix=".ndjson", prefix=f"github_events_{date}_{hour:02d}_", delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            found = fetch_github_archive(date, hour, tmp_path)
            if not found:
                continue

            with open(tmp_path, "r", encoding="utf-8") as f:
                hour_records = sum(1 for line in f if line.strip())
            records_fetched += hour_records

            upload_to_gcs(tmp_path, date, hour=hour)
            uploaded_hours += 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if uploaded_hours == 0 and existing_hours == 0:
        logger.warning(f"No records fetched for {date}.")
        return None

    logger.info(
        "Finished GCS ingestion for %s (uploaded_hours=%s, existing_hours=%s, fetched_records=%s)",
        date,
        uploaded_hours,
        existing_hours,
        records_fetched,
    )
    return gcs_uri_for_date(date)


# ─────────────────────────────────────────────────────────────────────────────
# Full single-call orchestration (used by CLI / standalone runs)
# ─────────────────────────────────────────────────────────────────────────────


def ingest_github_events(
    date: str,
    start_hour: int | None = None,
    max_hours: int | None = None,
) -> dict:
    """Run the full ingestion pipeline for a single date.

    Steps:
      1. Download all hourly GitHub Archive files for the date
      2. Upload combined NDJSON to GCS
      3. Load from GCS into BigQuery

    Args:
        date: Date string in YYYY-MM-DD format.

    Args:
        start_hour: First hour to ingest (0-23). Defaults to env/config.
        max_hours: Number of hours to ingest from start_hour. Defaults to env/config.

    Returns:
        Dict with {'date', 'records_fetched', 'rows_loaded', 'gcs_uri'}.
    """
    logger.info(f"Starting ingestion for date: {date}")

    # Step 1: Download + upload hourly files to GCS
    gcs_uri = fetch_to_gcs(date, start_hour=start_hour, max_hours=max_hours)
    if gcs_uri is None:
        logger.warning(f"No records fetched for {date}. Skipping load.")
        return {"date": date, "records_fetched": 0, "rows_loaded": 0, "gcs_uri": None}

    # Step 2: Load into BigQuery
    rows_loaded = load_to_bigquery(gcs_uri, date)

    result = {
        "date": date,
        # When reusing existing GCS hour files, rows_loaded is the most useful metric.
        "records_fetched": rows_loaded,
        "rows_loaded": rows_loaded,
        "gcs_uri": gcs_uri,
    }
    logger.info(f"Ingestion complete: {json.dumps(result)}")
    return result


def resolve_date(date_arg: str | None) -> str:
    """Resolve the target date, defaulting to yesterday UTC if not specified."""
    if date_arg:
        # Validate format
        datetime.strptime(date_arg, "%Y-%m-%d")
        return date_arg
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def main() -> None:
    """Entry point: parse CLI args and run ingestion."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest GitHub Archive data into GCS and BigQuery"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to ingest (YYYY-MM-DD). Defaults to yesterday UTC.",
    )
    parser.add_argument(
        "--start-hour",
        type=int,
        default=None,
        help="First UTC hour to ingest (0-23). Defaults to GH_ARCHIVE_START_HOUR or 0.",
    )
    parser.add_argument(
        "--max-hours",
        type=int,
        default=None,
        help="Number of UTC hours to ingest. Defaults to GH_ARCHIVE_MAX_HOURS or 24.",
    )
    args = parser.parse_args()

    date = resolve_date(args.date or os.getenv("GITHUB_ARCHIVE_DATE"))

    if not PROJECT_ID:
        logger.error("GCP_PROJECT_ID environment variable is required")
        sys.exit(1)
    if not BUCKET_NAME:
        logger.error("GCS_BUCKET_NAME environment variable is required")
        sys.exit(1)

    try:
        result = ingest_github_events(
            date,
            start_hour=args.start_hour,
            max_hours=args.max_hours,
        )
        logger.info(f"Pipeline finished successfully: {result}")
        sys.exit(0)
    except requests.HTTPError as e:
        logger.error(f"HTTP error downloading GitHub Archive: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()

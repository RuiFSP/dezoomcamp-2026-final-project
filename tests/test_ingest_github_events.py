"""Unit tests for the GitHub Events ingestion module."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingest_github_events import (
    GCS_UPLOAD_CHUNK_SIZE_BYTES,
    GCS_UPLOAD_TIMEOUT_SECONDS,
    fetch_day,
    fetch_github_archive,
    fetch_to_gcs,
    ingest_github_events,
    load_to_bigquery,
    resolve_date,
    resolve_hour_window,
    upload_to_gcs,
)

# ─────────────────────────────────────────────────────────────────────────────
# resolve_date
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_date_explicit():
    assert resolve_date("2026-03-20") == "2026-03-20"


def test_resolve_date_none_returns_yesterday():
    result = resolve_date(None)
    # Should be a valid date string in YYYY-MM-DD format
    datetime.strptime(result, "%Y-%m-%d")


def test_resolve_date_invalid_raises():
    with pytest.raises(ValueError):
        resolve_date("not-a-date")


# ─────────────────────────────────────────────────────────────────────────────
# fetch_github_archive
# ─────────────────────────────────────────────────────────────────────────────


def test_fetch_github_archive_not_found(tmp_path):
    """Returns False when GitHub Archive returns 404."""
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("src.ingest_github_events.requests.get", return_value=mock_response):
        result = fetch_github_archive("2030-01-01", 0, str(tmp_path / "out.ndjson"))

    assert result is False


def test_fetch_github_archive_success(tmp_path):
    """Returns True and writes decompressed content on success."""
    import gzip
    import io

    raw_data = b'{"id":"1","type":"PushEvent"}\n'
    compressed = gzip.compress(raw_data)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raw = io.BytesIO(compressed)
    mock_response.raise_for_status = MagicMock()

    output_path = str(tmp_path / "out.ndjson")

    with patch("src.ingest_github_events.requests.get", return_value=mock_response):
        result = fetch_github_archive("2026-03-20", 0, output_path)

    assert result is True
    assert Path(output_path).exists()
    content = Path(output_path).read_text()
    assert "PushEvent" in content


# ─────────────────────────────────────────────────────────────────────────────
# ingest_github_events
# ─────────────────────────────────────────────────────────────────────────────


def test_ingest_skips_load_when_no_records(tmp_path):
    """When no records are fetched, skips GCS upload and BQ load."""
    with patch("src.ingest_github_events.fetch_to_gcs", return_value=None):
        result = ingest_github_events("2030-01-01")

    assert result["records_fetched"] == 0
    assert result["rows_loaded"] == 0
    assert result["gcs_uri"] is None


def test_ingest_full_pipeline(tmp_path):
    """Full pipeline runs fetch → upload → load when records present."""
    with (
        patch(
            "src.ingest_github_events.fetch_to_gcs", return_value="gs://bucket/path"
        ) as mock_fetch,
        patch(
            "src.ingest_github_events.load_to_bigquery", return_value=42
        ) as mock_load,
    ):
        result = ingest_github_events("2026-03-20")

    assert result["records_fetched"] == 42
    assert result["rows_loaded"] == 42
    assert result["gcs_uri"] == "gs://bucket/path"
    mock_fetch.assert_called_once_with("2026-03-20", start_hour=None, max_hours=None)
    mock_load.assert_called_once_with("gs://bucket/path", "2026-03-20")


def test_fetch_to_gcs_reuses_existing_object():
    """If all hour files already exist in GCS, skip download/upload work."""
    with (
        patch("src.ingest_github_events.gcs_hour_object_exists", return_value=True),
        patch("src.ingest_github_events.fetch_github_archive") as mock_fetch_hour,
        patch("src.ingest_github_events.upload_to_gcs") as mock_upload,
    ):
        gcs_uri = fetch_to_gcs("2026-03-20")

    assert (
        gcs_uri
        == "gs://gh-dezoomcamp-raw-events/raw/github_events/2026-03-20/hours/*.ndjson"
    )
    mock_fetch_hour.assert_not_called()
    mock_upload.assert_not_called()


def test_resolve_hour_window_defaults_from_env():
    with patch.dict(
        "src.ingest_github_events.os.environ",
        {"GH_ARCHIVE_START_HOUR": "2", "GH_ARCHIVE_MAX_HOURS": "3"},
        clear=False,
    ):
        start, count = resolve_hour_window()
    assert (start, count) == (2, 3)


def test_resolve_hour_window_uses_bruin_run_interval():
    with patch.dict(
        "src.ingest_github_events.os.environ",
        {
            "BRUIN_START_TIMESTAMP": "2026-03-22T00:00:00Z",
            "BRUIN_END_TIMESTAMP": "2026-03-22T01:00:00Z",
            "BRUIN_VARS": "{}",
        },
        clear=True,
    ):
        start, count = resolve_hour_window()

    assert (start, count) == (0, 1)


def test_resolve_hour_window_invalid_raises():
    with pytest.raises(ValueError):
        resolve_hour_window(start_hour=23, max_hours=2)


def test_fetch_day_respects_hour_window(tmp_path):
    out = tmp_path / "combined.ndjson"

    with patch(
        "src.ingest_github_events.fetch_github_archive", return_value=False
    ) as mock_fetch:
        records = fetch_day("2026-03-20", str(out), start_hour=5, max_hours=2)

    assert records == 0
    assert mock_fetch.call_count == 2
    called_hours = [call.args[1] for call in mock_fetch.call_args_list]
    assert called_hours == [5, 6]


def test_load_to_bigquery_deletes_target_date_before_load():
    """Raw table load is idempotent by deleting the target date before append."""
    mock_client = MagicMock()
    mock_load_job = MagicMock()
    mock_load_job.output_rows = 42
    mock_query_job = MagicMock()
    mock_query_job.num_dml_affected_rows = 10
    mock_table = MagicMock()
    mock_table.num_rows = 1000

    mock_client.query.return_value = mock_query_job
    mock_client.load_table_from_uri.return_value = mock_load_job
    mock_client.get_table.return_value = mock_table

    with (
        patch("src.ingest_github_events.bigquery.Client", return_value=mock_client),
        patch("src.ingest_github_events.ensure_table_exists"),
    ):
        rows_loaded = load_to_bigquery("gs://bucket/path/events.ndjson", "2026-03-20")

    assert rows_loaded == 42
    called_sql = mock_client.query.call_args.args[0]
    assert "DELETE FROM" in called_sql
    assert "DATE(created_at) = @target_date" in called_sql


def test_upload_to_gcs_uses_resumable_settings(tmp_path):
    local_file = tmp_path / "events.ndjson"
    local_file.write_text('{"id":"1"}\n')

    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    with patch("src.ingest_github_events.storage.Client", return_value=mock_client):
        gcs_uri = upload_to_gcs(str(local_file), "2026-03-20")

    assert gcs_uri.endswith("raw/github_events/2026-03-20/events.ndjson")
    assert mock_blob.chunk_size == GCS_UPLOAD_CHUNK_SIZE_BYTES
    kwargs = mock_blob.upload_from_filename.call_args.kwargs
    assert kwargs["content_type"] == "application/x-ndjson"
    assert kwargs["timeout"] == GCS_UPLOAD_TIMEOUT_SECONDS
    assert kwargs["retry"] is not None

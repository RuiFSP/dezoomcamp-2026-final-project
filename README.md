# GitHub Activity Analytics Dashboard

> DataTalks.Club DE Zoomcamp 2026 Final Project

This project builds an end-to-end batch data pipeline for public GitHub activity data and serves the final analytics through a Streamlit dashboard.

The dashboard is now fully Streamlit-based. Looker Studio is no longer part of the intended submission.

## Architecture

```mermaid
flowchart TD
    GHA["gharchive.org\nhourly NDJSON .gz"]

    subgraph GCS["GCS Data Lake"]
        RAW_GCS["raw/github_events/YYYY-MM-DD/hours/HH.ndjson"]
    end

    subgraph BQ["BigQuery"]
        RAW["raw_github_events"]
        STG["stg_github_events"]
        M1["events_by_type"]
        M2["events_by_hour"]
        M3["top_repos"]
        M4["language_trends"]
    end

    APP["Streamlit Dashboard"]

    GHA -->|Bruin ingestion| RAW_GCS
    RAW_GCS -->|Bruin load| RAW
    RAW -->|SQL staging| STG
    STG --> M1
    STG --> M2
    STG --> M3
    STG --> M4
    M1 & M2 & M3 & M4 --> APP
```

## Stack

| Layer | Tool |
|---|---|
| Infrastructure | Terraform |
| Orchestration | Bruin CLI |
| Language | Python 3.12 |
| Package management | uv |
| Data lake | GCS |
| Data warehouse | BigQuery |
| Dashboard | Streamlit |

## Project Structure

```text
bruin/
  assets/
    ingest/
    staging/
    marts/
src/
streamlit_app/
terraform/
tests/
```

## Environments

| Environment | BigQuery dataset |
|---|---|
| dev | dev_gh_analytics |
| staging | stg_gh_analytics |
| prod | gh_analytics |

## Quick Start

### 1. Prerequisites

- GCP project and credentials
- gcloud CLI
- Terraform
- Bruin CLI
- Python 3.12
- uv

### 2. Configure local environment

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev,test]"
cp .env.example .env
```

Fill in `.env` with your project-specific values.

### 3. Bootstrap GCP and infrastructure

The helper script is a convenience bootstrap for local development. Review the defaults in
`scripts/setup-gcp-auto.sh` before running it, especially the project ID and key path.

```bash
bash scripts/setup-gcp-auto.sh
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# edit terraform/terraform.tfvars with your project-specific values
make infra-apply
```

At minimum, update `project_id` and any globally unique resource names in
`terraform/terraform.tfvars` before applying infrastructure.

### 4. Run the pipeline

```bash
make run-dev-smoke
make run-dev
make run-stg
make run-prod
```

### 5. Run tests

```bash
make test
make test-dev
make test-stg
make test-prod
```

### 6. Run Streamlit locally

```bash
make app-sync
make app-run
```

Local URL: `http://localhost:8501`

## Streamlit Deployment

Deploy the dashboard to Cloud Run:

```bash
make app-gcp-build
make app-deploy
make app-url
```

The app reads the mart tables from `gh_analytics` by default.

## Dashboard Scope

The Streamlit app covers:

- KPI overview
- Event type distribution
- Daily and hourly activity trends
- Top repositories
- Language activity trends
- Optional pipeline admin controls

## Submission Safety

Do not commit any of the following:

- `.env`
- `.bruin.yml`
- `terraform.tfvars`
- service account JSON keys
- private key or certificate files

Safe-to-commit examples are included in:

- `.env.example`
- `terraform/terraform.tfvars.example`

## Notes

- The raw ingestion uses hourly files in GCS to make retries and backfills resumable.
- The BigQuery raw table reload is idempotent per date.
- Streamlit is the only dashboard intended for the final submission.

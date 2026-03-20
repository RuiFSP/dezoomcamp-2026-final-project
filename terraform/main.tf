terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# GCS bucket for raw data (data lake)
resource "google_storage_bucket" "raw_data" {
  name          = var.bucket_name
  location      = var.region
  force_destroy = true

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  labels = {
    project        = "github-analytics"
    environment    = var.environment
    resource_type  = "data_lake"
    managed_by     = "terraform"
  }

  lifecycle_rule {
    condition {
      age = 30  # Delete files older than 30 days
    }
    action {
      type = "Delete"
    }
  }
}

# BigQuery dataset - Production
resource "google_bigquery_dataset" "gh_analytics" {
  dataset_id             = var.bq_dataset_id
  location               = var.region
  default_table_expiration_ms = 2592000000  # 30 days
  default_partition_expiration_ms = 2592000000
  delete_contents_on_destroy = true

  labels = {
    project     = "github-analytics"
    environment = "prod"
    managed_by  = "terraform"
  }
}

# BigQuery dataset - Development
resource "google_bigquery_dataset" "gh_analytics_dev" {
  dataset_id             = "dev_${var.bq_dataset_id}"
  location               = var.region
  default_table_expiration_ms = 2592000000
  default_partition_expiration_ms = 2592000000
  delete_contents_on_destroy = true

  labels = {
    project     = "github-analytics"
    environment = "dev"
    managed_by  = "terraform"
  }
}

# BigQuery dataset - Staging
resource "google_bigquery_dataset" "gh_analytics_stg" {
  dataset_id             = "stg_${var.bq_dataset_id}"
  location               = var.region
  default_table_expiration_ms = 2592000000
  default_partition_expiration_ms = 2592000000
  delete_contents_on_destroy = true

  labels = {
    project     = "github-analytics"
    environment = "stg"
    managed_by  = "terraform"
  }
}

# Cloud Run service — Streamlit dashboard
resource "google_cloud_run_v2_service" "dashboard" {
  name     = var.app_service_name
  location = var.region
  project  = var.project_id

  template {
    containers {
      image = var.app_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "BQ_DATASET"
        value = var.bq_dataset_id
      }
      env {
        name  = "ENABLE_PIPELINE_TRIGGER"
        value = "false"
      }
    }

    timeout = "900s"
  }

  labels = {
    project    = "github-analytics"
    managed_by = "terraform"
  }
}

# Allow public (unauthenticated) access
resource "google_cloud_run_v2_service_iam_member" "public_access" {
  project  = google_cloud_run_v2_service.dashboard.project
  location = google_cloud_run_v2_service.dashboard.location
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

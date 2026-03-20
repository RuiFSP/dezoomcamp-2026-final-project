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

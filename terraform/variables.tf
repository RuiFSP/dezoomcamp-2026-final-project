variable "project_id" {
  description = "GCP Project ID"
  type        = string
  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "europe-west1"
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.region)) && length(var.region) > 0
    error_message = "region must be a valid GCP region (e.g., europe-west1, us-central1)."
  }
}

variable "bucket_name" {
  description = "GCS bucket name for raw GitHub event data (must be globally unique)"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9-]{3,63}$", var.bucket_name))
    error_message = "Bucket name must be 3-63 chars, lowercase letters/numbers/hyphens only."
  }
}

variable "bq_dataset_id" {
  description = "BigQuery dataset ID for production environment"
  type        = string
  default     = "gh_analytics"
  validation {
    condition     = can(regex("^[a-zA-Z0-9_]+$", var.bq_dataset_id))
    error_message = "Dataset ID must contain only letters, numbers, and underscores."
  }
}

variable "environment" {
  description = "Environment name (dev, stg, prod)"
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["dev", "stg", "prod"], var.environment)
    error_message = "environment must be dev, stg, or prod."
  }
}

variable "app_service_name" {
  description = "Cloud Run service name for the Streamlit dashboard"
  type        = string
  default     = "gh-analytics-streamlit"
}

variable "app_image" {
  description = "Full container image URL to deploy (e.g. gcr.io/PROJECT/IMAGE:TAG). Build with: make app-gcp-build"
  type        = string
  default     = "gcr.io/gh-dezoomcamp/gh-analytics-streamlit:latest"
}

variable "billing_account_id" {
  description = "GCP Billing Account ID for budget alerts (format: 012345-ABCDEF-G9H2I3). Find at: https://console.cloud.google.com/billing/settings"
  type        = string
  validation {
    condition     = length(var.billing_account_id) > 0
    error_message = "billing_account_id must not be empty. Find it in GCP Console > Billing > Settings."
  }
}

variable "budget_amount_eur" {
  description = "Monthly budget limit in EUR for Cloud Run spending"
  type        = number
  default     = 5
  validation {
    condition     = var.budget_amount_eur > 0
    error_message = "budget_amount_eur must be greater than 0."
  }
}

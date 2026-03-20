output "gcs_bucket_name" {
  value       = google_storage_bucket.raw_data.name
  description = "GCS bucket name for raw GitHub events"
}

output "gcs_bucket_url" {
  value       = google_storage_bucket.raw_data.url
  description = "GCS bucket URL"
}

output "bigquery_dataset_id_prod" {
  value       = google_bigquery_dataset.gh_analytics.dataset_id
  description = "Production BigQuery dataset ID"
}

output "bigquery_dataset_id_dev" {
  value       = google_bigquery_dataset.gh_analytics_dev.dataset_id
  description = "Development BigQuery dataset ID"
}

output "bigquery_dataset_id_stg" {
  value       = google_bigquery_dataset.gh_analytics_stg.dataset_id
  description = "Staging BigQuery dataset ID"
}

output "project_id" {
  value       = var.project_id
  description = "GCP Project ID"
}

output "region" {
  value       = var.region
  description = "GCP Region"
}

# Changelog

All notable changes to this project are documented in this file.

## [v1.0.0] - 2026-03-22

### Added
- End-to-end GitHub activity pipeline across ingestion, staging, and marts.
- Environment-aware execution (`dev`, `staging`, `prod`) with explicit backfill helpers.
- Streamlit dashboard deployment and refreshed screenshots for current UI.
- Post-backfill operations runbook in the documentation.
- Optional Terraform-managed billing budget toggle (`enable_billing_budget`).

### Fixed
- Mermaid architecture diagram labels for GitHub parser compatibility.
- Terraform apply flow to avoid blocking app deploys when billing-budget permissions are unavailable.

### Operational Validation
- Historical window `2026-03-15` to `2026-03-21` validated at 24/24 hourly completeness in `dev`, `staging`, and `prod` for `stg_github_events` and `events_by_hour`.

## [v1.0-submission] - 2026-03-22

### Notes
- Initial submission tag retained for traceability.

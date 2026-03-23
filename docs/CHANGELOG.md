# Changelog

All notable changes to this project are documented in this file.

## [v1.1.0] - 2026-03-23

### Added
- Full Bruin Cloud execution support using the same pipeline codebase as local CLI runs.
- Cloud proof screenshots for run started and run finished states.
- README top banner image and execution-mode documentation for local, UI-triggered, and CLI-triggered managed runs.

### Changed
- Documentation now reflects validated Bruin Cloud operations instead of listing Cloud integration as pending.
- `README` examples now use a generic Bruin Cloud project ID placeholder instead of a hardcoded project-specific ID.
- Engineering next steps were re-scoped to focus on true production-scale improvements (alerting, governance, performance, incremental processing, and staging validation).

### Fixed
- Ingestion gzip decompression now streams in chunks to prevent `OOMKilled` failures on longer managed Cloud intervals.
- Bruin Cloud run screenshot references normalized to `started` and `finished` naming.

### Operational Validation
- Managed Bruin Cloud run succeeded for the full daily interval `2026-03-22 00:00:00 -> 2026-03-23 00:00:00` in `00:10:47`.
- Validation covered all 7 assets with all 29 quality checks passing.

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

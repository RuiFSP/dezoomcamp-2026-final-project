PYTHON := python
UV := uv
BRUIN  := bruin
APP_IMAGE ?= gcr.io/$(GCP_PROJECT_ID)/gh-analytics-streamlit:latest
GCP_PROJECT_ID ?= gh-dezoomcamp
GCP_REGION ?= europe-west1
APP_SERVICE ?= gh-analytics-streamlit
DATE   ?= $(shell $(PYTHON) -c "from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)-timedelta(days=1)).strftime('%Y-%m-%d'))")
LOAD_ENV = set -a; [ -f .env ] && . ./.env; set +a;

# ─────────────────────────────────────────────────────────────────────────────
# Ingestion only (Bruin: fetch → GCS → BigQuery raw, skip transformations)
# ─────────────────────────────────────────────────────────────────────────────

ingest-dev:
	@$(LOAD_ENV) $(BRUIN) run --environment dev bruin/assets/ingest/raw_github_events.py

ingest-stg:
	@$(LOAD_ENV) $(BRUIN) run --environment staging bruin/assets/ingest/raw_github_events.py

ingest-prod:
	@$(LOAD_ENV) $(BRUIN) run --environment prod bruin/assets/ingest/raw_github_events.py

# ─────────────────────────────────────────────────────────────────────────────
# Bruin full-pipeline runs
# ─────────────────────────────────────────────────────────────────────────────

run-dev:
	@$(LOAD_ENV) $(BRUIN) run --environment dev --var '{"current_dataset":"dev_gh_analytics"}' bruin/

# Fast end-to-end smoke run: ingest only one UTC hour.
run-dev-smoke:
	@$(LOAD_ENV) GH_ARCHIVE_START_HOUR=0 GH_ARCHIVE_MAX_HOURS=1 $(BRUIN) run --environment dev --var '{"current_dataset":"dev_gh_analytics"}' bruin/

run-stg:
	@$(LOAD_ENV) $(BRUIN) run --environment staging --var '{"current_dataset":"stg_gh_analytics"}' bruin/

run-prod:
	@$(LOAD_ENV) $(BRUIN) run --environment prod --force --var '{"current_dataset":"gh_analytics"}' bruin/

# Backfill helpers: DATE_FROM and DATE_TO must be supplied, e.g.:
#   make backfill-dev DATE_FROM=2026-03-14 DATE_TO=2026-03-20
DATE_FROM ?= $(error Set DATE_FROM, e.g. DATE_FROM=2026-03-14)
DATE_TO   ?= $(error Set DATE_TO,   e.g. DATE_TO=2026-03-20)

backfill-dev:
	@$(LOAD_ENV) $(BRUIN) run --environment dev \
	  --start-date $(DATE_FROM) --end-date $(DATE_TO) \
	  --var '{"current_dataset":"dev_gh_analytics"}' bruin/

backfill-stg:
	@$(LOAD_ENV) $(BRUIN) run --environment staging \
	  --start-date $(DATE_FROM) --end-date $(DATE_TO) \
	  --var '{"current_dataset":"stg_gh_analytics"}' bruin/

backfill-prod:
	@$(LOAD_ENV) $(BRUIN) run --environment prod --force \
	  --start-date $(DATE_FROM) --end-date $(DATE_TO) \
	  --var '{"current_dataset":"gh_analytics"}' bruin/

# ─────────────────────────────────────────────────────────────────────────────
# Data quality tests
# ─────────────────────────────────────────────────────────────────────────────

test-dev:
	@$(LOAD_ENV) $(BRUIN) run --environment dev --only checks --var '{"current_dataset":"dev_gh_analytics"}' bruin/

test-stg:
	@$(LOAD_ENV) $(BRUIN) run --environment staging --only checks --var '{"current_dataset":"stg_gh_analytics"}' bruin/

test-prod:
	@$(LOAD_ENV) $(BRUIN) run --environment prod --force --only checks --var '{"current_dataset":"gh_analytics"}' bruin/

# ─────────────────────────────────────────────────────────────────────────────
# Python unit tests
# ─────────────────────────────────────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -v

test-cov:
	$(PYTHON) -m pytest tests/ --cov=src --cov-report=term-missing

# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure (Terraform)
# ─────────────────────────────────────────────────────────────────────────────

infra-plan:
	cd terraform && terraform plan

infra-apply:
	cd terraform && terraform apply

infra-destroy:
	@echo "WARNING: This will destroy all GCP resources. Are you sure? (Ctrl-C to abort)"
	@sleep 5
	cd terraform && terraform destroy

# ─────────────────────────────────────────────────────────────────────────────
# Linting / formatting
# ─────────────────────────────────────────────────────────────────────────────

lint:
	$(PYTHON) -m black --check src/ tests/
	$(PYTHON) -m isort --check src/ tests/

format:
	$(PYTHON) -m black src/ tests/
	$(PYTHON) -m isort src/ tests/

# ─────────────────────────────────────────────────────────────────────────────
# Streamlit app (local + container + Cloud Run)
# ─────────────────────────────────────────────────────────────────────────────

app-sync:
	$(UV) sync --extra streamlit

app-run:
	@$(LOAD_ENV) $(UV) run streamlit run streamlit_app/app.py

app-docker-build:
	docker build -f streamlit_app/Dockerfile -t $(APP_IMAGE) .

app-docker-run:
	docker run --rm -p 8080:8080 \
		-e GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-key.json \
		-e GCP_PROJECT_ID=$(GCP_PROJECT_ID) \
		-e BQ_DATASET=gh_analytics \
		-v $$HOME/gcp-key.json:/tmp/gcp-key.json:ro \
		$(APP_IMAGE)

app-gcp-build:
	gcloud builds submit --project=$(GCP_PROJECT_ID) --config cloudbuild.yaml --substitutions _IMAGE=$(APP_IMAGE) .

app-deploy:
	cd terraform && terraform apply -auto-approve -var "app_image=$(APP_IMAGE)"

app-url:
	@cd terraform && terraform output -raw cloud_run_url

.PHONY: ingest-dev ingest-stg ingest-prod \
	run-dev run-dev-smoke run-stg run-prod \
	backfill-dev backfill-stg backfill-prod \
        test-dev test-stg test-prod \
        test test-cov \
        infra-plan infra-apply infra-destroy \
        lint format \
	app-sync app-run app-docker-build app-docker-run app-gcp-build app-deploy app-url

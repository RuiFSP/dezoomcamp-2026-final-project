# Engineering Deep Dive

This document explores the technical decisions, trade-offs, and lessons learned in building this data pipeline.

## Table of Contents

1. [Data Quality Strategy](#data-quality-strategy)
2. [Materialization & Performance](#materialization--performance)
3. [Staging Layer Design](#staging-layer-design)
4. [Idempotency & Retries](#idempotency--retries)
5. [Tool Choices](#tool-choices)
6. [Lessons Learned](#lessons-learned)

---

## Data Quality Strategy

### Column-Level Checks

Each analytical mart declares expected column properties in the Bruin YAML:

```yaml
columns:
  - name: event_id
    type: STRING
    description: Unique event identifier
    checks:
      - name: not_null
      - name: unique
  - name: hour_of_day
    type: INTEGER
    checks:
      - name: not_null
      - name: non_negative
      - name: max
        value: 23
```

**Benefits:**
- Catches schema drift early (e.g., if an upstream asset stops providing a required column)
- Prevents invalid data (negative hour values, duplicates) from reaching the dashboard
- Self-documenting: the YAML describes expected data shape and business rules

**Execution:**
Bruin validates these checks after materializing each table. If any fail, the asset is marked as unhealthy and downstream assets are blocked.

### Custom Validation Queries

For complex business logic, we use custom SQL assertions:

**Example: `events_by_type` requires ≥5 distinct event types daily**

```yaml
custom_checks:
    - name: multiple event types exist
      description: At least 5 distinct event types should be present
      query: "SELECT CASE WHEN COUNT(DISTINCT event_type) >= 5 THEN 0 ELSE 1 END FROM {{ var.current_dataset }}.events_by_type"
      value: 0  # Expect 0 rows (i.e., check passes if count >= 5)
```

This catches days with anomalously low event diversity, which might indicate:
- A bug in the ingestion layer
- A global GitHub outage
- A data freshness issue

**Design Principle:**
We assert on *counts* (SELECT ... THEN 0 ELSE 1), not on presence. This ensures failures are visible in Bruin logs and easy to debug.

### Trade-Offs

**Not Implemented: Continuous Monitoring**
- No separate orchestrator (e.g., dbt expectations) running continuous tests
- No alerting when checks fail in production
- Rationale: For a batch pipeline on a learning project, this adds complexity beyond the scope

**Next Steps (If Scaling):**
- Export check results to a monitoring table
- Trigger Cloud Logging alerts on check failures
- Implement SLOs (e.g., max 2% null rate)

---

## Materialization & Performance

### Partitioning Strategy

All marts are **partitioned by date**:

```sql
materialization:
    type: table
    partition_by: event_date
```

**Why:**
- GitHub releases ~500M events per day; partitioning avoids scanning 30+ days of data for a single-day query
- BigQuery computes partition pruning automatically; a query filtering `WHERE event_date = '2026-03-20'` scans only one partition
- Cost savings: Partitioning can reduce query costs by 50–80% depending on filter selectivity
- Partition pruning is transparent to the user; filters on `event_date` are automatically applied

### Clustering Strategy

High-cardinality columns are clustered for faster lookups:

```sql
materialization:
    type: table
    partition_by: event_date
    cluster_by:
        - event_type
        - repo_name
```

**Why:**
- Dashboard queries often filter by `event_type` (PushEvent, PullRequestEvent, etc.) or `repo_name` (top 100 repos)
- Clustering sorts data within each partition by these columns, enabling BigQuery to skip unnecessary blocks
- Cluster pruning is _not_ guaranteed but heuristically applied; it complements partitioning

**Limitations:**
- Clustering adds overhead during writes (sorting cost)
- Useful only for columns with moderate-to-high cardinality (100–1000 distinct values)
- For very high cardinality (e.g., repo_id with millions of unique values), clustering may not be efficient

### Query Performance

With partitioning + clustering, typical queries run in <1 second:

```sql
-- Runs against ~1 partition + cluster range; <100M bytes scanned
SELECT event_type, COUNT(*) as cnt
FROM `gh_analytics.events_by_type`
WHERE event_date = CURDATE() - 1
GROUP BY event_type
ORDER BY cnt DESC;
```

### Trade-Offs

**Not Implemented: Incremental Materialization**
- Marts are rebuilt daily from scratch (full refresh)
- No "insert into select from yesterday" logic
- Rationale: Data volume (~500k–1M daily records) makes full refresh fast (<30s); complexity of incremental logic adds little value

**If Scaling:**
- Implement incremental models with dbt (change data capture on staging layer)
- Cache intermediate results (e.g., hourly aggregates) for faster downstream rebuilds

---

## Staging Layer Design

### Deduplication via Window Functions

GitHub's API occasionally returns duplicate events or reorders historical data. The staging layer handles this:

```sql
WITH deduplicated AS (
    SELECT
        id AS event_id,
        ...
        ROW_NUMBER() OVER (
            PARTITION BY id
            ORDER BY created_at DESC
        ) AS rn
    FROM `gh_analytics.raw_github_events`
    WHERE id IS NOT NULL AND type IS NOT NULL
)
SELECT *
FROM deduplicated
WHERE rn = 1
```

**Why:**
- GitHub Archive is best-effort; the same event may appear in multiple hourly files
- Using `ROW_NUMBER() OVER (PARTITION BY id ORDER BY created_at DESC)` keeps the most recent version
- Simpler than external deduplication logic; happens once during staging

### Payload Preservation

Raw `payload` JSON is preserved in the staging table:

```sql
SELECT
    event_id,
    event_timestamp,
    event_type,
    ...
    payload  -- Unparsed JSON from GitHub Archive
FROM deduplicated
WHERE rn = 1
```

**Why:**
- Mart transformations may need event-specific fields (e.g., PR merge status, issue labels)
- Storing JSON avoids re-parsing 1M raw records on every query
- Future extensions can derive new features without touching the raw layer

### Partitioning & Clustering Inheritance

Marts inherit the staging table's partition + cluster keys:

```sql
-- in mart definition
depends:
    - gh_analytics.stg_github_events

-- Queries over stg_github_events benefit from partitioning
SELECT ... FROM `{{ var.current_dataset }}.stg_github_events`
WHERE DATE(event_timestamp) = CURRENT_DATE()
```

---

## Idempotency & Retries

### Idempotent Raw Table Load

The raw table is reloaded daily via a DELETE + INSERT pattern:

```sql
DELETE FROM `gh_analytics.raw_github_events`
WHERE DATE(created_at) = @target_date;

INSERT INTO `gh_analytics.raw_github_events`
SELECT * FROM EXTERNAL_QUERY(...);
```

**Why:**
- If Bruin retries the pipeline on the same date, the load is re-executed
- DELETE ensures no duplicates accumulate; the final state is deterministic

**Idempotency Guarantee:**
- Running the pipeline twice on the same date produces identical results
- This enables safe retries without manual cleanup

### GCS Object Existence Checks

Before downloading and uploading to GCS, the pipeline checks if the object already exists:

```python
if gcs_hour_object_exists(f"{date}/{hour}"):
    return  # Skip download/upload; use existing data
```

**Why:**
- Downloading 24 hourly archives (~2 GB) is expensive and time-consuming
- If a previous run succeeded up to hour 12 and failed at hour 13, the next run reuses hours 0–12
- Reduces bandwidth and API calls to GitHub Archive

**Trade-Off:**
- Assumes imported objects are correct; no validation
- If a GCS object is corrupt, manual removal is required

---

## Tool Choices

### Why Bruin (vs. Airflow + dbt)?

| Aspect | Bruin | Airflow + dbt |
|--------|-------|--------------|
| **Setup Time** | 10 min | 1–2 hours |
| **Configuration Language** | YAML + SQL | Python DAGs + dbt YAML |
| **Learning Curve** | Gentle | Steeper |
| **State Management** | Implicit (Bruin tracks runs) | External metastore (Postgres) |
| **Built-in Data Quality** | Yes (column checks) | Via dbt_expectations (addon) |
| **Community Size** | Small (~2k GitHub stars) | Massive (~30k+ stars) |
| **Documentation** | Good | Extensive |

**Decision:** For a learning project and single-use pipeline, Bruin's simplicity and faster time-to-value outweigh Airflow's ecosystem and scalability. Bruin is easier to explain in a code review (everything is YAML/SQL, no Python DAG abstractions).

### Why BigQuery (vs. Snowflake / DuckDB)?

| Aspect | BigQuery | Snowflake | DuckDB |
|--------|----------|-----------|--------|
| **Setup Time** | Minutes | Hours (requires account, warehouse) | Instant (local) |
| **Pricing Model** | Pay per query (scan volume) | Per-compute-per-second | Free (local) |
| **Partitioning/Clustering** | Native, simple | Via micro-partitions + clustering keys | Basic |
| **Integration with GCP** | Seamless | Requires connector | Requires setup |
| **Production-Grade** | Yes | Yes | Partially (newer) |

**Decision:** BigQuery integrates naturally with GCP (where Terraform provisions resources). Query-based pricing aligns with batch analytics (low volume). DuckDB would work for local development but adds a separate data model to sync with production.

### Why Streamlit (vs. Tableau / Looker)?

| Aspect | Streamlit | Tableau | Looker |
|--------|-----------|---------|--------|
| **Setup Time** | Minutes | Days (requires admin setup) | Days |
| **Coding** | Python (natural for data engineers) | No-code (drag-and-drop) | LookML (domain-specific language) |
| **Deployment** | Cloud Run (1 command) | Requires Tableau Server | Google Cloud deployment |
| **Cost** | Low (~$0–10/month on Cloud Run) | High ($1k+/year per user) | Medium (part of Google Cloud licensing) |
| **For Learning** | Perfect (understand every line) | Overkill (black box) | Overkill |

**Decision:** Streamlit is transparent, deployable to Cloud Run in one command, and free for learning. The code is auditable (reviewers see exactly what runs).

---

## Lessons Learned

### 1. Partitioning is Essential

- **Lesson:** Without date partitioning, querying a mart table scans all historical data.
- **Event:** On a test query filtering `WHERE event_date = '2026-03-20'`, BigQuery scanned 30 days of data (~30 GB) instead of one day (~1 GB).
- **Resolution:** Added `partition_by: DATE(event_timestamp)` to all marts. Query cost dropped from ~$0.15 to ~$0.005.
- **Takeaway:** Always partition analytical tables on the filter you use most frequently (usually date or tenant_id).

### 2. Clustering Doesn't Guarantee Speed

- **Lesson:** Clustering is a hint, not a guarantee. BigQuery applies cluster pruning heuristically.
- **Event:** Queries on `repo_name` were slower than expected because `repo_name` has millions of distinct values.
- **Resolution:** Accepted that clustering is a "nice-to-have" for this volume. Focus effort on partitioning, which is deterministic.
- **Takeaway:** Cluster on moderate-cardinality columns (100–10k distinct values). For very high cardinality, consider denormalization or pre-aggregation instead.

### 3. Deduplication Overhead is Worth It

- **Lesson:** Staging layer deduplication adds ~2 second overhead but prevents data quality issues downstream.
- **Event:** Without deduplication, the same GitHub event (e.g., a PushEvent with ID `123`) appeared in marts multiple times after a retry.
- **Resolution:** Added `ROW_NUMBER() OVER (PARTITION BY id ORDER BY created_at DESC) = 1` to the staging SQL.
- **Takeaway:** Pay the small upfront cost of deduplication to guarantee downstream data quality.

### 4. Custom Data Quality Checks Scale Poorly

- **Lesson:** Custom checks are powerful but not scalable to hundreds of tables.
- **Event:** After adding 5 marts, maintaining 5 custom checks became tedious (updating as business rules change).
- **Resolution:** Limited custom checks to the most critical marts (top_repos, events_by_type). Standard column checks cover the rest.
- **Takeaway:** Use column-level checks as the baseline. Reserve custom checks for business-critical tables; document them well.

### 5. Logging & Observability Gaps

- **Lesson:** When a Bruin asset silently completes with 0 rows, it's hard to distinguish "no data today" from "pipeline broke."
- **Event:** A partially-failed ingestion run left a raw table with 0 records. The pipeline continued, silently producing empty marts.
- **Resolution:** Added `print(f"Loaded {rows:,} rows for {date}")` to ingestion steps. Bruin logs show these prints, aiding debugging.
- **Takeaway:** Log key metrics (records processed, load time, check results) at each major step. Treat logging as a first-class requirement.

### 6. Environment Management is Subtle

- **Lesson:** Forgetting to source environment variables or using wrong BigQuery dataset is a common error.
- **Event:** A local test ran `SELECT * FROM stg_github_events` which read from `dev_gh_analytics`, but the commit pushed to `main` with hardcoded dataset reference.
- **Resolution:** Parameterized all SQL references using `{{ var.current_dataset }}` in Bruin. Enforced via linting (ruff, pre-commit).
- **Takeaway:** Use templating/variable injection for all environment-specific values. Make hardcoding difficult or impossible.

---

## Next Steps (If Scaling to Production)

1. **Alerting & SLOs**
   - Export data quality check results to Cloud Logging
   - Trigger alerts if pipeline fails or data quality check fails
   - Define SLOs (e.g., "pipeline completes by 11 AM UTC daily")

2. **Data Lineage & Governance**
   - Integrate with Data Catalog for asset discovery
   - Document business logic (why is hour_of_day capped at 23?)
   - Create runbooks for common failures

3. **Performance Monitoring**
   - Track query cost and execution time trends
   - Set budgets and alerts for cost overruns

4. **Incremental Processing**
   - Implement incremental staging (only process new hourly archives)
   - Pre-aggregate hourly marts to reduce downstream query cost

5. **Testing in Production**
   - Deploy to a staging GCP project; validate before applying to prod
   - Use Terraform workspaces for environment separation

---

## Related Files

- [Bruin Pipeline YAML](./bruin/pipeline.yml)
- [Terraform Infrastructure](./terraform/main.tf)
- [Ingestion Tests](./tests/test_ingest_github_events.py)

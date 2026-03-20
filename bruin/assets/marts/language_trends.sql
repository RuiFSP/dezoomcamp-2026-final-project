/* @bruin
name: gh_analytics.language_trends
type: bq.sql
materialization:
    type: table
    partition_by: event_date
    cluster_by:
        - repo_language
depends:
    - gh_analytics.stg_github_events
columns:
    - name: event_date
      type: DATE
      checks:
          - name: not_null
    - name: repo_name
      type: STRING
      checks:
          - name: not_null
    - name: push_count
      type: INTEGER
      checks:
          - name: positive
    - name: contributors
      type: INTEGER
      checks:
          - name: positive
@bruin */

-- Language is inferred from the repository name suffix (best-effort).
-- Repositories with a recognisable language-annotated topic in their
-- CreateEvent payload are preferred; others fall back to NULL.
WITH push_events AS (
    SELECT
        DATE(event_timestamp)               AS event_date,
        repo_name,
        -- PushEvent payload carries ref; CreateEvent carries ref_type.
        -- We extract the primary language hint written to the payload topic
        -- when available (GitHub Archive includes it in the CreateEvent).
        JSON_VALUE(payload, '$.ref_type')   AS ref_type,
        JSON_VALUE(payload, '$.master_branch') AS branch,
        actor_login
    FROM `{{ var.current_dataset }}.stg_github_events`
    WHERE event_type IN ('PushEvent', 'CreateEvent')
),


-- CreateEvent payloads sometimes carry a 'description' or topic; without
-- a direct language field in the public GitHub Archive payload we cannot
-- reliably enumerate language per event. This mart therefore aggregates
-- by repository and counts events as a proxy for language activity.
repo_activity AS (
    SELECT
        event_date,
        SPLIT(repo_name, '/')[SAFE_OFFSET(0)]   AS repo_owner,
        SPLIT(repo_name, '/')[SAFE_OFFSET(1)]   AS repo_short_name,
        repo_name,
        COUNT(*)                                AS push_count,
        COUNT(DISTINCT actor_login)             AS contributors
    FROM push_events
    GROUP BY 1, 2, 3, 4
)

SELECT
    event_date,
    repo_owner,
    repo_short_name,
    repo_name,
    -- Extract a coarse language hint from the repo short name extension
    -- (e.g. "python-sdk" → 'python', "react-ui" → NULL).
    CASE
        WHEN LOWER(repo_short_name) LIKE '%python%'     THEN 'Python'
        WHEN LOWER(repo_short_name) LIKE '%javascript%' THEN 'JavaScript'
        WHEN LOWER(repo_short_name) LIKE '%java%'       THEN 'Java'
        WHEN LOWER(repo_short_name) LIKE '%go%'         THEN 'Go'
        WHEN LOWER(repo_short_name) LIKE '%rust%'       THEN 'Rust'
        WHEN LOWER(repo_short_name) LIKE '%typescript%' THEN 'TypeScript'
        WHEN LOWER(repo_short_name) LIKE '%ruby%'       THEN 'Ruby'
        WHEN LOWER(repo_short_name) LIKE '%php%'        THEN 'PHP'
        WHEN LOWER(repo_short_name) LIKE '%cpp%'        THEN 'C++'
        WHEN LOWER(repo_short_name) LIKE '%csharp%'     THEN 'C#'
        ELSE NULL
    END                     AS repo_language,
    push_count,
    contributors
FROM repo_activity

/* @bruin
name: gh_analytics.stg_github_events
type: bq.sql
description: Cleaned and deduplicated GitHub events from raw layer, ready for analytics
owner: data-platform
materialization:
    type: table
    partition_by: DATE(event_timestamp)
    cluster_by:
        - event_type
        - repo_name
depends:
    - ingest.raw_github_events
columns:
    - name: event_id
      type: STRING
      description: Unique event identifier
      primary_key: true
      checks:
          - name: not_null
          - name: unique
    - name: event_timestamp
      type: TIMESTAMP
      description: When the event was created on GitHub
      checks:
          - name: not_null
    - name: event_type
      type: STRING
      description: GitHub event type (e.g. PushEvent, PullRequestEvent)
      checks:
          - name: not_null
    - name: repo_name
      type: STRING
      description: Full repository name (owner/repo)
      checks:
          - name: not_null
    - name: actor_login
      type: STRING
      description: GitHub username of the actor
      checks:
          - name: not_null
    - name: org_login
      type: STRING
      description: GitHub organisation login (nullable)
    - name: repo_id
      type: STRING
      description: Repository identifier from GitHub payload
      checks:
          - name: not_null
    - name: actor_id
      type: STRING
      description: Actor identifier from GitHub payload
      checks:
          - name: not_null
    - name: is_public
      type: BOOLEAN
      description: Whether the GitHub event is public
    - name: payload
      type: JSON
      description: Raw event payload JSON from GitHub Archive
custom_checks:
    - name: core identity fields are present
      description: Ensure staged records include event and actor identity information
      query: "SELECT COUNT(*) FROM {{ var.current_dataset }}.stg_github_events WHERE event_id IS NULL OR actor_login IS NULL OR repo_name IS NULL"
      value: 0
@bruin */

WITH deduplicated AS (
    SELECT
        id                                          AS event_id,
        CAST(created_at AS TIMESTAMP)               AS event_timestamp,
        type                                        AS event_type,
        JSON_VALUE(repo,   '$.name')                AS repo_name,
        JSON_VALUE(actor,  '$.login')               AS actor_login,
        JSON_VALUE(org,    '$.login')               AS org_login,
        JSON_VALUE(actor,  '$.id')                  AS actor_id,
        JSON_VALUE(repo,   '$.id')                  AS repo_id,
        CAST(public AS BOOL)                        AS is_public,
        payload,
        ROW_NUMBER() OVER (
            PARTITION BY id
            ORDER BY created_at DESC
        )                                           AS rn
    FROM `gh_analytics.raw_github_events`
    WHERE
        id         IS NOT NULL
        AND type   IS NOT NULL
        AND created_at IS NOT NULL
)

SELECT
    event_id,
    event_timestamp,
    event_type,
    repo_name,
    repo_id,
    actor_login,
    actor_id,
    org_login,
    is_public,
    payload
FROM deduplicated
WHERE rn = 1

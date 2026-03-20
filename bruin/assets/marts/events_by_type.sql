/* @bruin
name: gh_analytics.events_by_type
type: bq.sql
materialization:
    type: table
    partition_by: event_date
    cluster_by:
        - event_type
depends:
    - gh_analytics.stg_github_events
columns:
    - name: event_date
      type: DATE
      checks:
          - name: not_null
    - name: event_type
      type: STRING
      checks:
          - name: not_null
    - name: event_count
      type: INTEGER
      checks:
          - name: positive
    - name: unique_actors
      type: INTEGER
      checks:
          - name: non_negative
    - name: unique_repos
      type: INTEGER
      checks:
          - name: non_negative
custom_checks:
    - name: multiple event types exist
      description: At least 5 distinct event types should be present
      query: "SELECT CASE WHEN COUNT(DISTINCT event_type) >= 5 THEN 0 ELSE 1 END FROM {{ var.current_dataset }}.events_by_type"
      value: 0
@bruin */

SELECT
    DATE(event_timestamp)   AS event_date,
    event_type,
    COUNT(*)                AS event_count,
    COUNT(DISTINCT actor_login) AS unique_actors,
    COUNT(DISTINCT repo_name)   AS unique_repos
FROM `{{ var.current_dataset }}.stg_github_events`
GROUP BY 1, 2

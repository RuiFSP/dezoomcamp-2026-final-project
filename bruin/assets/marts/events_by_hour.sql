/* @bruin
name: gh_analytics.events_by_hour
type: bq.sql
description: GitHub events aggregated by day and hour of day (UTC), with daily unique actor counts
owner: data-platform
materialization:
    type: table
    partition_by: event_date
    cluster_by:
        - hour_of_day
depends:
    - gh_analytics.stg_github_events
columns:
    - name: event_date
      type: DATE
      description: Date of the event (UTC)
      primary_key: true
      checks:
          - name: not_null
    - name: hour_of_day
      type: INTEGER
      description: Hour of day in UTC (0-23)
      primary_key: true
      checks:
          - name: not_null
          - name: non_negative
          - name: max
            value: 23
    - name: event_count
      type: INTEGER
      description: Number of GitHub events in this hour
      checks:
          - name: positive
custom_checks:
    - name: hours in valid range
      description: hour_of_day must be 0-23
      query: "SELECT COUNT(*) FROM {{ var.current_dataset }}.events_by_hour WHERE hour_of_day < 0 OR hour_of_day > 23"
      value: 0
@bruin */

SELECT
    DATE(event_timestamp)           AS event_date,
    EXTRACT(HOUR FROM event_timestamp) AS hour_of_day,
    COUNT(*)                        AS event_count,
    COUNT(DISTINCT actor_login)     AS unique_actors
FROM `{{ var.current_dataset }}.stg_github_events`
GROUP BY 1, 2

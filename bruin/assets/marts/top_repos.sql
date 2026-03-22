/* @bruin
name: gh_analytics.top_repos
type: bq.sql
description: GitHub repositories ranked by activity, including event types, stars, forks, and unique contributors
owner: data-platform
materialization:
    type: table
    partition_by: event_date
    cluster_by:
        - repo_name
depends:
    - gh_analytics.stg_github_events
columns:
    - name: event_date
      type: DATE
      description: Date of the event (UTC)
            primary_key: true
      checks:
          - name: not_null
    - name: repo_name
      type: STRING
      description: Full repository name in format owner/repo
            primary_key: true
      checks:
          - name: not_null
    - name: total_events
      type: INTEGER
      description: Total number of events for this repository
      checks:
          - name: positive
    - name: unique_contributors
      type: INTEGER
      description: Distinct GitHub users who contributed to this repository
      checks:
          - name: non_negative
custom_checks:
    - name: no null repo names
      description: All rows must have a non-null repo_name
      query: "SELECT COUNT(*) FROM {{ var.current_dataset }}.top_repos WHERE repo_name IS NULL"
      value: 0
@bruin */

SELECT
    DATE(event_timestamp)       AS event_date,
    repo_name,
    COUNT(*)                    AS total_events,
    COUNTIF(event_type = 'WatchEvent')          AS stars,
    COUNTIF(event_type = 'ForkEvent')           AS forks,
    COUNTIF(event_type = 'PushEvent')           AS pushes,
    COUNTIF(event_type = 'PullRequestEvent')    AS pull_requests,
    COUNTIF(event_type = 'IssuesEvent')         AS issues,
    COUNT(DISTINCT actor_login)                 AS unique_contributors
FROM `{{ var.current_dataset }}.stg_github_events`
WHERE repo_name IS NOT NULL
GROUP BY 1, 2

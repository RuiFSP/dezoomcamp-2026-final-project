"""Tests for Bruin pipeline YAML configuration and data quality checks."""

import re
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def pipeline_yaml():
    """Load the main Bruin pipeline YAML."""
    bruin_path = Path(__file__).parent.parent / "bruin" / "pipeline.yml"
    with open(bruin_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def all_assets():
    """Load all Bruin assets (SQL + Python)."""
    assets_dir = Path(__file__).parent.parent / "bruin" / "assets"
    assets = {}

    for sql_file in assets_dir.rglob("*.sql"):
        with open(sql_file) as f:
            content = f.read()
            # Extract @bruin YAML from SQL comments
            match = re.search(r"/\*\s*@bruin\n(.*?)\n@bruin\s*\*/", content, re.DOTALL)
            if match:
                yaml_content = match.group(1)
                try:
                    assets[sql_file.name] = yaml.safe_load(yaml_content)
                except yaml.YAMLError:
                    pass

    for py_file in assets_dir.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        with open(py_file) as f:
            content = f.read()
            # Extract @bruin YAML from Python docstrings
            match = re.search(r'"""@bruin\n(.*?)\n@bruin"""', content, re.DOTALL)
            if match:
                yaml_content = match.group(1)
                try:
                    assets[py_file.name] = yaml.safe_load(yaml_content)
                except yaml.YAMLError:
                    pass

    return assets


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Configuration Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_pipeline_yaml_valid(pipeline_yaml):
    """Pipeline YAML parses successfully."""
    assert pipeline_yaml is not None
    assert "name" in pipeline_yaml
    assert pipeline_yaml["name"] == "github-analytics"


def test_pipeline_has_schedule(pipeline_yaml):
    """Pipeline declares a schedule."""
    assert "schedule" in pipeline_yaml
    assert pipeline_yaml["schedule"] == "@daily"


def test_pipeline_has_default_connections(pipeline_yaml):
    """Pipeline declares default connections."""
    assert "default_connections" in pipeline_yaml
    assert "google_cloud_platform" in pipeline_yaml["default_connections"]


def test_pipeline_has_start_date(pipeline_yaml):
    """Pipeline declares a start_date."""
    assert "start_date" in pipeline_yaml
    # Must be parseable as a date
    assert re.match(r"\d{4}-\d{2}-\d{2}", pipeline_yaml["start_date"])


def test_pipeline_has_variables(pipeline_yaml):
    """Pipeline declares variables for environment configuration."""
    assert "variables" in pipeline_yaml
    assert "current_dataset" in pipeline_yaml["variables"]
    assert pipeline_yaml["variables"]["current_dataset"]["type"] == "string"
    assert "gcs_bucket_name" in pipeline_yaml["variables"]
    assert pipeline_yaml["variables"]["gcs_bucket_name"]["type"] == "string"


# ─────────────────────────────────────────────────────────────────────────────
# Asset Structure Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_all_assets_have_names(all_assets):
    """Every asset declares a name."""
    for asset_file, asset_config in all_assets.items():
        assert "name" in asset_config, f"{asset_file} missing 'name'"
        assert isinstance(asset_config["name"], str)
        assert len(asset_config["name"]) > 0


def test_all_assets_have_descriptions(all_assets):
    """Every asset declares a description."""
    for asset_file, asset_config in all_assets.items():
        assert "description" in asset_config, f"{asset_file} missing 'description'"
        assert isinstance(asset_config["description"], str)
        assert len(asset_config["description"]) > 0


def test_mart_assets_have_materialization(all_assets):
    """Mart assets declare materialization strategy."""
    marts = {
        f: cfg
        for f, cfg in all_assets.items()
        if "events_by_" in f or "top_repos" in f or "language_trends" in f
    }

    for asset_file, asset_config in marts.items():
        assert "materialization" in asset_config, (
            f"{asset_file} missing 'materialization'"
        )
        mat = asset_config["materialization"]
        assert mat.get("type") == "table"


def test_staging_table_has_partitioning(all_assets):
    """Staging table is partitioned by date for performance."""
    stg_assets = {f: cfg for f, cfg in all_assets.items() if "stg_" in f}

    for asset_file, asset_config in stg_assets.items():
        if "materialization" in asset_config:
            mat = asset_config["materialization"]
            assert "partition_by" in mat, f"{asset_file} missing 'partition_by'"


def test_all_marts_have_partitioning(all_assets):
    """All mart tables are partitioned by date."""
    marts = {
        f: cfg
        for f, cfg in all_assets.items()
        if "events_by_" in f or "top_repos" in f or "language_trends" in f
    }

    for asset_file, asset_config in marts.items():
        if "materialization" in asset_config:
            mat = asset_config["materialization"]
            assert "partition_by" in mat, f"{asset_file} missing 'partition_by'"


def test_all_marts_have_clustering(all_assets):
    """All mart tables are clustered on high-cardinality columns."""
    marts = {
        f: cfg
        for f, cfg in all_assets.items()
        if "events_by_" in f or "top_repos" in f or "language_trends" in f
    }

    for asset_file, asset_config in marts.items():
        if "materialization" in asset_config:
            mat = asset_config["materialization"]
            assert "cluster_by" in mat, f"{asset_file} missing 'cluster_by'"
            assert isinstance(mat["cluster_by"], list)
            assert len(mat["cluster_by"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Data Quality Checks Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_all_assets_document_columns(all_assets):
    """All SQL assets document their columns."""
    sql_assets = {f: cfg for f, cfg in all_assets.items() if f.endswith(".sql")}

    for asset_file, asset_config in sql_assets.items():
        # Skip assets without columns (e.g., SQL views that don't need docs)
        if "columns" in asset_config:
            columns = asset_config["columns"]
            assert isinstance(columns, list), f"{asset_file}: columns must be a list"
            assert len(columns) > 0, f"{asset_file}: must document at least one column"


def test_columns_have_descriptions(all_assets):
    """All documented columns have descriptions."""
    sql_assets = {f: cfg for f, cfg in all_assets.items() if f.endswith(".sql")}

    for asset_file, asset_config in sql_assets.items():
        if "columns" in asset_config:
            for col in asset_config["columns"]:
                assert "description" in col, (
                    f"{asset_file}: column '{col.get('name')}' missing 'description'"
                )


def test_primary_key_column_has_unique_check(all_assets):
    """Primary key columns (event_id, etc.) have unique checks."""
    for asset_file, asset_config in all_assets.items():
        if "columns" in asset_config:
            for col in asset_config["columns"]:
                if col.get("name") in ("event_id", "id"):
                    checks = col.get("checks", [])
                    check_names = [
                        c.get("name") if isinstance(c, dict) else c for c in checks
                    ]
                    assert "unique" in check_names, (
                        f"{asset_file}: primary key '{col['name']}' missing 'unique' check"
                    )


def test_critical_columns_have_not_null_check(all_assets):
    """Critical columns have NOT NULL checks."""
    critical_columns = {"event_timestamp", "event_type", "event_date", "event_id"}

    for asset_file, asset_config in all_assets.items():
        if "columns" in asset_config:
            for col in asset_config["columns"]:
                if col.get("name") in critical_columns:
                    checks = col.get("checks", [])
                    check_names = [
                        c.get("name") if isinstance(c, dict) else c for c in checks
                    ]
                    assert "not_null" in check_names, (
                        f"{asset_file}: critical column '{col['name']}' missing 'not_null' check"
                    )


def test_count_columns_have_non_negative_check(all_assets):
    """Count/aggregate columns have non_negative or positive checks."""
    count_patterns = {"count", "total", "unique", "sum", "avg"}

    for asset_file, asset_config in all_assets.items():
        if "columns" in asset_config:
            for col in asset_config["columns"]:
                col_name_lower = col.get("name", "").lower()
                if any(pattern in col_name_lower for pattern in count_patterns):
                    checks = col.get("checks", [])
                    check_names = [
                        c.get("name") if isinstance(c, dict) else c for c in checks
                    ]
                    assert any(
                        check in check_names for check in ["positive", "non_negative"]
                    ), (
                        f"{asset_file}: count column '{col['name']}' missing "
                        "'positive' or 'non_negative' check"
                    )


def test_custom_checks_exist(all_assets):
    """Critical marts include custom validation checks."""
    marts_with_custom_checks = {
        "events_by_hour.sql",
        "events_by_type.sql",
        "top_repos.sql",
    }

    for asset_file, asset_config in all_assets.items():
        if asset_file in marts_with_custom_checks:
            assert "custom_checks" in asset_config, (
                f"{asset_file}: mart should have custom_checks defined"
            )
            custom_checks = asset_config["custom_checks"]
            assert isinstance(custom_checks, list)
            assert len(custom_checks) > 0


def test_custom_checks_have_queries(all_assets):
    """Custom checks include SQL validation queries."""
    for asset_file, asset_config in all_assets.items():
        if "custom_checks" in asset_config:
            for check in asset_config["custom_checks"]:
                assert "query" in check, f"{asset_file}: custom check missing 'query'"
                assert "value" in check, (
                    f"{asset_file}: custom check missing expected 'value'"
                )
                assert isinstance(check["query"], str)
                assert len(check["query"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Dependency & Lineage Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_all_assets_declare_dependencies(all_assets):
    """Assets declare upstream dependencies (or are root sources)."""
    # Root sources that don't need dependencies
    root_sources = {"fetch_to_gcs.py"}

    for asset_file, asset_config in all_assets.items():
        if asset_file not in root_sources:
            # All non-root assets should declare dependencies
            assert "depends" in asset_config or asset_file in root_sources, (
                f"{asset_file}: must declare 'depends' or be a root source"
            )


def test_staging_depends_on_ingestion(all_assets):
    """Staging layer depends on ingestion assets."""
    stg_assets = {f: cfg for f, cfg in all_assets.items() if "stg_" in f}

    for asset_file, asset_config in stg_assets.items():
        if "depends" in asset_config:
            depends = asset_config["depends"]
            # Should depend on 'ingest.*' asset
            ingest_deps = [d for d in depends if d.startswith("ingest")]
            assert len(ingest_deps) > 0, f"{asset_file}: staging must depend on ingest"


def test_marts_depend_on_staging(all_assets):
    """Marts depend on staging layer."""
    marts = {
        f: cfg
        for f, cfg in all_assets.items()
        if "events_by_" in f or "top_repos" in f or "language_trends" in f
    }

    for asset_file, asset_config in marts.items():
        if "depends" in asset_config:
            depends = asset_config["depends"]
            # Should depend on 'gh_analytics.stg_*' asset
            stg_deps = [d for d in depends if "stg_" in d]
            assert len(stg_deps) > 0, f"{asset_file}: mart should depend on staging"


def test_no_circular_dependencies(all_assets):
    """Pipeline has no circular dependencies."""
    # Build a dependency graph
    dep_graph = {}
    for asset_file, asset_config in all_assets.items():
        asset_name = asset_config.get("name")
        if asset_name:
            dep_graph[asset_name] = asset_config.get("depends", [])

    # Simple cycle detection (DFS)
    def has_cycle(graph, start, visited, rec_stack):
        visited.add(start)
        rec_stack.add(start)

        for neighbor in graph.get(start, []):
            if neighbor not in visited:
                if has_cycle(graph, neighbor, visited, rec_stack):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(start)
        return False

    visited = set()
    for node in dep_graph:
        if node not in visited:
            assert not has_cycle(dep_graph, node, visited, set()), (
                "Pipeline has circular dependency"
            )

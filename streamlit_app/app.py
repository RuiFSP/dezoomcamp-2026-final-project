"""
GitHub Activity Analytics Dashboard
Streamlit app reading from BigQuery mart tables.
"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

# Path resolution (works both locally and in Docker container)
_APP_DIR = Path(__file__).parent
_ROOT_DIR = _APP_DIR if (_APP_DIR / "src").exists() else _APP_DIR.parent
_BRUIN_DIR = Path(os.environ.get("BRUIN_DIR", str(_ROOT_DIR / "bruin")))
sys.path.insert(0, str(_ROOT_DIR))

# Configuration
GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "gh-dezoomcamp")
BQ_DATASET = os.environ.get("BQ_DATASET", "gh_analytics")
ENABLE_PIPELINE_TRIGGER = (
    os.environ.get("ENABLE_PIPELINE_TRIGGER", "false").lower() == "true"
)

# Page config
st.set_page_config(
    page_title="GitHub Activity Analytics",
    page_icon="🐙",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
    .section-header {
        font-size: 1.15rem;
        font-weight: 600;
        color: #7dd3b6;
        margin-bottom: 0.75rem;
        padding-bottom: 0.4rem;
        border-bottom: 1px solid #30363d;
    }
    div[data-testid="metric-container"] {
        background: linear-gradient(180deg, #1c2128 0%, #252b34 100%);
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 16px 20px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
    }
    div[data-testid="metric-container"] label {
        color: #8d9dbd !important;
        font-size: 0.8rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #22c99b !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.95rem;
        padding: 8px 20px;
        color: #adbac7;
    }
    .stTabs [aria-selected="true"] {
        color: #22c99b !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    return bigquery.Client(project=GCP_PROJECT)


@st.cache_data(ttl=300, show_spinner=False)
def load_available_date_range() -> tuple[date, date]:
    query = f"""
    SELECT
      MIN(DATE(created_at)) AS min_date,
      MAX(DATE(created_at)) AS max_date
    FROM `{GCP_PROJECT}.{BQ_DATASET}.raw_github_events`
    """
    row = next(get_bq_client().query(query).result())
    if row.min_date and row.max_date:
        return row.min_date, row.max_date
    today = date.today()
    return today, today


@st.cache_data(ttl=300, show_spinner=False)
def load_events_by_type(start: str, end: str) -> pd.DataFrame:
    query = f"""
    SELECT event_date, event_type, event_count, unique_actors, unique_repos
    FROM `{GCP_PROJECT}.{BQ_DATASET}.events_by_type`
    WHERE event_date BETWEEN '{start}' AND '{end}'
    ORDER BY event_date, event_count DESC
    """
    return get_bq_client().query(query).to_dataframe()


@st.cache_data(ttl=300, show_spinner=False)
def load_events_by_hour(start: str, end: str) -> pd.DataFrame:
    query = f"""
    SELECT event_date, hour_of_day, event_count, unique_actors
    FROM `{GCP_PROJECT}.{BQ_DATASET}.events_by_hour`
    WHERE event_date BETWEEN '{start}' AND '{end}'
    ORDER BY event_date, hour_of_day
    """
    return get_bq_client().query(query).to_dataframe()


@st.cache_data(ttl=300, show_spinner=False)
def load_top_repos(start: str, end: str) -> pd.DataFrame:
    query = f"""
    SELECT event_date, repo_name, total_events, stars, forks, pushes,
           pull_requests, issues, unique_contributors
    FROM `{GCP_PROJECT}.{BQ_DATASET}.top_repos`
    WHERE event_date BETWEEN '{start}' AND '{end}'
    ORDER BY total_events DESC
    LIMIT 200
    """
    return get_bq_client().query(query).to_dataframe()


@st.cache_data(ttl=300, show_spinner=False)
def load_language_trends(start: str, end: str) -> pd.DataFrame:
    query = f"""
    SELECT event_date, repo_language,
           SUM(push_count)   AS push_count,
           SUM(contributors) AS contributors
    FROM `{GCP_PROJECT}.{BQ_DATASET}.language_trends`
    WHERE event_date BETWEEN '{start}' AND '{end}'
      AND repo_language IS NOT NULL
    GROUP BY 1, 2
    ORDER BY push_count DESC
    """
    return get_bq_client().query(query).to_dataframe()


@st.cache_data(ttl=300, show_spinner=False)
def load_kpis(start: str, end: str) -> dict[str, int]:
    query_1 = f"""
    SELECT
        SUM(event_count) AS total_events,
        COUNT(DISTINCT event_type) AS event_types
    FROM `{GCP_PROJECT}.{BQ_DATASET}.events_by_type`
    WHERE event_date BETWEEN '{start}' AND '{end}'
    """
    query_2 = f"""
    SELECT
        COUNT(DISTINCT actor_login) AS unique_actors,
        COUNT(DISTINCT repo_name)   AS unique_repos
    FROM `{GCP_PROJECT}.{BQ_DATASET}.stg_github_events`
    WHERE DATE(event_timestamp) BETWEEN '{start}' AND '{end}'
    """
    client = get_bq_client()
    result_1 = next(client.query(query_1).result())
    result_2 = next(client.query(query_2).result())
    return {
        "total_events": int(result_1.total_events or 0),
        "event_types": int(result_1.event_types or 0),
        "unique_actors": int(result_2.unique_actors or 0),
        "unique_repos": int(result_2.unique_repos or 0),
    }


@st.cache_data(ttl=300, show_spinner=False)
def load_pipeline_status() -> pd.DataFrame:
    query = f"""
    SELECT DATE(created_at) AS date, COUNT(*) AS raw_rows
    FROM `{GCP_PROJECT}.{BQ_DATASET}.raw_github_events`
    GROUP BY 1
    ORDER BY 1 DESC
    LIMIT 14
    """
    return get_bq_client().query(query).to_dataframe()


_TEMPLATE = "plotly_dark"
_COLOR_SEQ = [
    "#22c99b",
    "#58a6ff",
    "#f0883e",
    "#bc8cff",
    "#ff7b72",
    "#ffa657",
    "#3fb950",
    "#79c0ff",
    "#d2a8ff",
    "#ffa198",
]
_PRIMARY = "#22c99b"
_BG = "#0f1117"
_PAPER = "#1c2128"
_GRID = "#30363d"


def _layout(fig: go.Figure, height: int = 400) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor=_PAPER,
        plot_bgcolor=_BG,
        font=dict(family="Inter, sans-serif", color="#e6edf3"),
        margin=dict(l=10, r=10, t=36, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", borderwidth=0),
        xaxis=dict(gridcolor=_GRID, zeroline=False),
        yaxis=dict(gridcolor=_GRID, zeroline=False),
        hoverlabel=dict(bgcolor="#1c2128", font_color="#e6edf3"),
    )
    return fig


def _section(title: str) -> None:
    st.markdown(f'<p class="section-header">{title}</p>', unsafe_allow_html=True)


with st.sidebar:
    st.markdown("## 🐙 GitHub Analytics")
    st.markdown("*DE Zoomcamp 2026 Final Project*")
    st.divider()

    st.markdown("### 📅 Date Range")
    try:
        min_date, max_date = load_available_date_range()
    except Exception:
        min_date = date(2026, 3, 15)
        max_date = date.today()

    start_date = st.date_input(
        "From", value=min_date, min_value=min_date, max_value=max_date
    )
    end_date = st.date_input(
        "To", value=max_date, min_value=min_date, max_value=max_date
    )

    if start_date > end_date:
        st.error("Start must be <= End")
        st.stop()

    st.divider()

    if st.button("🔄 Refresh Data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("**Stack**")
    st.markdown("🔧 Bruin · BigQuery · GCS · Terraform")
    st.markdown("**Data window**")
    st.markdown(f"{min_date} → {max_date}")

start_str = str(start_date)
end_str = str(end_date)

st.markdown("# 🐙 GitHub Activity Analytics")
st.markdown(
    f"Public GitHub events · **{start_str}** → **{end_str}** · "
    f"source: [gharchive.org](https://www.gharchive.org/)"
)
st.divider()

with st.spinner("Loading data from BigQuery…"):
    try:
        kpis = load_kpis(start_str, end_str)
        df_type = load_events_by_type(start_str, end_str)
        df_hour = load_events_by_hour(start_str, end_str)
        df_repos = load_top_repos(start_str, end_str)
        df_lang = load_language_trends(start_str, end_str)
    except Exception as exc:
        st.error(f"Failed to load dashboard data: {exc}")
        kpis = {
            "total_events": 0,
            "event_types": 0,
            "unique_actors": 0,
            "unique_repos": 0,
        }
        df_type = pd.DataFrame()
        df_hour = pd.DataFrame()
        df_repos = pd.DataFrame()
        df_lang = pd.DataFrame()

k1, k2, k3, k4 = st.columns(4)
k1.metric("⚡ Total Events", f"{kpis['total_events']:,}")
k2.metric("👥 Unique Actors", f"{kpis['unique_actors']:,}")
k3.metric("📦 Unique Repos", f"{kpis['unique_repos']:,}")
k4.metric("🏷️ Event Types", f"{kpis['event_types']:,}")
st.divider()

tab_labels = ["📊 Event Overview", "🏆 Top Repositories", "💻 Language Signals"]
if ENABLE_PIPELINE_TRIGGER:
    tab_labels.append("⚙️ Pipeline Admin")

tabs = st.tabs(tab_labels)
tab_overview, tab_repos, tab_lang = tabs[:3]
tab_admin = tabs[3] if ENABLE_PIPELINE_TRIGGER else None

with tab_overview:
    col_l, col_r = st.columns(2)

    with col_l:
        _section("Events by Type (total)")
        if not df_type.empty:
            agg = (
                df_type.groupby("event_type", as_index=False)
                .agg(event_count=("event_count", "sum"))
                .sort_values("event_count", ascending=True)
            )
            fig = px.bar(
                agg,
                x="event_count",
                y="event_type",
                orientation="h",
                labels={"event_count": "Events", "event_type": ""},
                color="event_count",
                color_continuous_scale="Blues",
                template=_TEMPLATE,
            )
            fig.update_coloraxes(showscale=False)
            st.plotly_chart(_layout(fig, 420), width="stretch")

    with col_r:
        _section("Daily Event Volume")
        if not df_type.empty:
            daily = df_type.groupby("event_date", as_index=False).agg(
                event_count=("event_count", "sum")
            )
            daily["event_date"] = daily["event_date"].astype(str)
            fig = px.bar(
                daily,
                x="event_date",
                y="event_count",
                labels={"event_count": "Events", "event_date": "Date"},
                color_discrete_sequence=[_PRIMARY],
                template=_TEMPLATE,
            )
            st.plotly_chart(_layout(fig, 420), width="stretch")

    _section("Hourly Activity Heatmap (UTC)")
    if not df_hour.empty:
        df_h = df_hour.copy()
        df_h["event_date"] = df_h["event_date"].astype(str)
        pivot = df_h.pivot_table(
            index="event_date",
            columns="hour_of_day",
            values="event_count",
            fill_value=0,
        )
        fig = px.imshow(
            pivot,
            labels={"x": "Hour (UTC)", "y": "Date", "color": "Events"},
            color_continuous_scale="Blues",
            aspect="auto",
            template=_TEMPLATE,
        )
        st.plotly_chart(_layout(fig, 250), width="stretch")

    _section("Hourly Pattern (aggregated across all dates)")
    if not df_hour.empty:
        h_agg = df_hour.groupby("hour_of_day", as_index=False).agg(
            event_count=("event_count", "sum")
        )
        fig = px.bar(
            h_agg,
            x="hour_of_day",
            y="event_count",
            labels={"event_count": "Events", "hour_of_day": "Hour (UTC)"},
            color_discrete_sequence=[_PRIMARY],
            template=_TEMPLATE,
        )
        fig.update_xaxes(dtick=1)
        st.plotly_chart(_layout(fig, 320), width="stretch")

    _section("Event Types Over Time")
    if not df_type.empty:
        df_t = df_type.copy()
        df_t["event_date"] = df_t["event_date"].astype(str)
        top_types = (
            df_t.groupby("event_type")["event_count"].sum().nlargest(8).index.tolist()
        )
        df_t_top = df_t[df_t["event_type"].isin(top_types)]
        fig = px.line(
            df_t_top,
            x="event_date",
            y="event_count",
            color="event_type",
            labels={
                "event_count": "Events",
                "event_date": "Date",
                "event_type": "Type",
            },
            markers=True,
            color_discrete_sequence=_COLOR_SEQ,
            template=_TEMPLATE,
        )
        st.plotly_chart(_layout(fig, 360), width="stretch")

    _section("Daily Event Mix")
    if not df_type.empty:
        mix = df_type.copy()
        mix["event_date"] = mix["event_date"].astype(str)
        top_mix_types = (
            mix.groupby("event_type")["event_count"].sum().nlargest(6).index.tolist()
        )
        mix = mix[mix["event_type"].isin(top_mix_types)]
        fig = px.bar(
            mix,
            x="event_date",
            y="event_count",
            color="event_type",
            labels={
                "event_date": "Date",
                "event_count": "Events",
                "event_type": "Type",
            },
            color_discrete_sequence=_COLOR_SEQ,
            template=_TEMPLATE,
        )
        fig.update_layout(barmode="stack")
        st.plotly_chart(_layout(fig, 360), width="stretch")

with tab_repos:
    if df_repos.empty:
        st.info("No repo data for the selected range.")
    else:
        repos_agg = (
            df_repos.groupby("repo_name", as_index=False)
            .agg(
                total_events=("total_events", "sum"),
                stars=("stars", "sum"),
                forks=("forks", "sum"),
                pushes=("pushes", "sum"),
                pull_requests=("pull_requests", "sum"),
                issues=("issues", "sum"),
                unique_contributors=("unique_contributors", "sum"),
            )
            .sort_values("total_events", ascending=False)
        )

        col_chart, col_table = st.columns([1, 1])

        with col_chart:
            _section("Top 20 Repos by Total Activity")
            top20 = repos_agg.head(20).sort_values("total_events", ascending=True)
            fig = px.bar(
                top20,
                x="total_events",
                y="repo_name",
                orientation="h",
                labels={"total_events": "Total Events", "repo_name": ""},
                color="total_events",
                color_continuous_scale="Viridis",
                template=_TEMPLATE,
            )
            fig.update_coloraxes(showscale=False)
            st.plotly_chart(_layout(fig, 520), width="stretch")

        with col_table:
            _section("Activity Details")
            display = repos_agg.head(30).copy()
            display.columns = [
                "Repository",
                "Events",
                "⭐ Stars",
                "🍴 Forks",
                "📤 Pushes",
                "🔀 PRs",
                "🐛 Issues",
                "👥 Contributors",
            ]
            st.dataframe(display, width="stretch", height=500, hide_index=True)

        _section("Activity Breakdown — Top 10 Repos")
        top10 = repos_agg.head(10)
        fig = go.Figure()
        for metric, color, label in [
            ("pushes", _PRIMARY, "📤 Pushes"),
            ("stars", "#f0883e", "⭐ Stars"),
            ("forks", "#3fb950", "🍴 Forks"),
            ("pull_requests", "#bc8cff", "🔀 Pull Requests"),
            ("issues", "#ff7b72", "🐛 Issues"),
        ]:
            fig.add_trace(
                go.Bar(
                    name=label,
                    x=top10["repo_name"],
                    y=top10[metric],
                    marker_color=color,
                )
            )
        fig.update_layout(barmode="stack", template=_TEMPLATE, xaxis_tickangle=-30)
        st.plotly_chart(_layout(fig, 400), width="stretch")

        _section("Repository Activity Treemap")
        treemap_df = repos_agg.head(40).copy()
        treemap_df["label"] = treemap_df["repo_name"].str.split("/").str[-1]
        fig = px.treemap(
            treemap_df,
            path=["label"],
            values="total_events",
            color="unique_contributors",
            color_continuous_scale=[[0, "#1a3d30"], [0.5, "#22c99b"], [1, "#b6f5e4"]],
            hover_data={
                "total_events": True,
                "unique_contributors": True,
                "pushes": True,
                "stars": True,
            },
            labels={
                "total_events": "Total Events",
                "unique_contributors": "Contributors",
                "pushes": "Pushes",
                "stars": "Stars",
                "label": "Repo",
            },
            template=_TEMPLATE,
        )
        fig.update_traces(
            textinfo="label+value",
            textfont_size=13,
            marker_line_width=2,
            marker_line_color="#ffffff",
        )
        fig.update_layout(
            margin=dict(t=30, l=0, r=0, b=0), coloraxis_colorbar_title="Contributors"
        )
        st.plotly_chart(_layout(fig, 500), width="stretch")

with tab_lang:
    st.caption(
        "Language views are heuristic. `repo_language` is inferred from repository naming patterns, "
        "not from GitHub repository metadata."
    )
    if df_lang.empty:
        st.info(
            "No language data for the selected range. "
            "Language is inferred from repo name patterns (e.g. 'python-sdk' → Python)."
        )
    else:
        lang_agg = (
            df_lang.groupby("repo_language", as_index=False)
            .agg(push_count=("push_count", "sum"), contributors=("contributors", "sum"))
            .sort_values("push_count", ascending=False)
        )

        col1, col2 = st.columns(2)

        with col1:
            _section("Push Activity by Inferred Language")
            fig = px.bar(
                lang_agg.sort_values("push_count", ascending=True),
                x="push_count",
                y="repo_language",
                orientation="h",
                labels={"push_count": "Push Events", "repo_language": ""},
                color="repo_language",
                color_discrete_sequence=_COLOR_SEQ,
                template=_TEMPLATE,
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(_layout(fig, 400), width="stretch")

        with col2:
            _section("Inferred Language Share")
            fig = px.pie(
                lang_agg,
                values="push_count",
                names="repo_language",
                hole=0.5,
                color_discrete_sequence=_COLOR_SEQ,
                template=_TEMPLATE,
            )
            fig.update_traces(textposition="outside", textinfo="label+percent")
            st.plotly_chart(_layout(fig, 400), width="stretch")

        _section("Inferred Language Activity Over Time")
        top_langs = lang_agg.head(6)["repo_language"].tolist()
        df_lang_top = df_lang[df_lang["repo_language"].isin(top_langs)].copy()
        df_lang_top["event_date"] = df_lang_top["event_date"].astype(str)
        fig = px.line(
            df_lang_top,
            x="event_date",
            y="push_count",
            color="repo_language",
            labels={
                "push_count": "Pushes",
                "event_date": "Date",
                "repo_language": "Language",
            },
            markers=True,
            color_discrete_sequence=_COLOR_SEQ,
            template=_TEMPLATE,
        )
        st.plotly_chart(_layout(fig, 360), width="stretch")

        _section("Contributors vs Push Activity")
        fig = px.scatter(
            lang_agg,
            x="contributors",
            y="push_count",
            text="repo_language",
            size="push_count",
            labels={"push_count": "Pushes", "contributors": "Contributors"},
            color="repo_language",
            color_discrete_sequence=_COLOR_SEQ,
            template=_TEMPLATE,
        )
        fig.update_traces(textposition="top center")
        st.plotly_chart(_layout(fig, 380), width="stretch")

if tab_admin is not None:
    with tab_admin:
        _section("📋 Ingested Data Status")
        try:
            status_df = load_pipeline_status()
            status_df.columns = ["Date", "Raw Rows"]
            status_df["Raw Rows"] = status_df["Raw Rows"].apply(lambda x: f"{x:,}")
            st.dataframe(status_df, width="stretch", hide_index=True)
        except Exception as exc:
            st.warning(f"Could not load status: {exc}")

        st.divider()
        _section("🚀 Trigger Pipeline Run")
        st.markdown(
            "Runs a full Bruin pipeline: fetch from gharchive.org → GCS → BigQuery raw "
            "→ staging → all 4 mart tables → 25 quality checks."
        )

        col_form, col_preview = st.columns([1, 1])

        with col_form:
            ingest_date = st.date_input(
                "Date to ingest",
                value=date.today(),
                min_value=date(2024, 1, 1),
                max_value=date.today(),
            )
            ingest_env = st.selectbox("Environment", ["prod", "dev", "staging"])
            start_hour = st.slider("Start hour (UTC)", 0, 23, 0)
            max_hours = st.slider("Max hours to fetch", 1, 24, 6)
            force = st.checkbox("Force re-ingest (overwrite existing)", value=True)

        dataset_map = {
            "prod": "gh_analytics",
            "dev": "dev_gh_analytics",
            "staging": "stg_gh_analytics",
        }
        current_dataset = dataset_map[ingest_env]

        cmd_parts = [
            f"GH_ARCHIVE_START_HOUR={start_hour} GH_ARCHIVE_MAX_HOURS={max_hours}",
            "bruin run",
            f"--environment {ingest_env}",
            "--force" if force else "",
            f"--start-date {ingest_date} --end-date {ingest_date}",
            f'--var \'{{"current_dataset":"{current_dataset}"}}\'',
            "bruin/",
        ]
        full_cmd = " ".join(part for part in cmd_parts if part)

        with col_preview:
            st.markdown("**Generated command:**")
            st.code(full_cmd, language="bash")

        st.divider()

        run_btn = st.button("🚀 Run Pipeline", type="primary", width="content")

        if run_btn:
            bruin_cmd = ["bruin", "run", "--environment", ingest_env]
            if force:
                bruin_cmd.append("--force")
            bruin_cmd += [
                "--start-date",
                str(ingest_date),
                "--end-date",
                str(ingest_date),
                "--var",
                f'{{"current_dataset":"{current_dataset}"}}',
                str(_BRUIN_DIR),
            ]

            env = os.environ.copy()
            env["GH_ARCHIVE_START_HOUR"] = str(start_hour)
            env["GH_ARCHIVE_MAX_HOURS"] = str(max_hours)

            log_box = st.empty()
            output_lines: list[str] = []

            try:
                with st.status("Running pipeline…", expanded=True) as status_widget:
                    process = subprocess.Popen(
                        bruin_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        cwd=str(_ROOT_DIR),
                        env=env,
                    )
                    assert process.stdout is not None
                    for line in process.stdout:
                        output_lines.append(line.rstrip())
                        log_box.code("\n".join(output_lines[-60:]), language="bash")

                    process.wait()

                if process.returncode == 0:
                    status_widget.update(
                        label="✅ Pipeline completed!", state="complete"
                    )
                    st.success(
                        "All assets executed and quality checks passed. Refreshing data…"
                    )
                    st.cache_data.clear()
                    st.rerun()
                else:
                    status_widget.update(label="❌ Pipeline failed", state="error")
                    st.error(f"Exit code {process.returncode}. See output above.")

            except FileNotFoundError:
                st.error(
                    "`bruin` CLI not found. Install: `curl -LsSf https://getbruin.com/install/cli | sh`"
                )
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")

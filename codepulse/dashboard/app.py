from __future__ import annotations

import os
import sys
from html import escape
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analytics.forecasting import growth_forecast
from analytics.metrics import contributor_velocity, growth_history, issue_resolution, overview, release_cadence, repositories
from db.database import Database
from pipeline.etl import ingest_repository
from pipeline.github_client import GitHubClient
from dashboard.discovery import CACHE_SECONDS, load_pulse

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="CodePulse", page_icon="⚡", layout="wide")
st.title("⚡ CodePulse")
st.caption("GitHub intelligence for a repository—or the wider open-source ecosystem.")

db_path = os.getenv("CODEPULSE_DB_PATH", str(ROOT / "data" / "codepulse.db"))
database = Database(db_path); database.initialize()

if "pulse_cache" not in st.session_state:
    st.session_state.pulse_cache = {}

with st.sidebar:
    page = st.radio("Explore", ["Repository report", "GitHub discovery"], label_visibility="collapsed")


def github_token() -> str:
    """Read a deployment secret if configured; never write a token to disk or DB."""
    if os.getenv("GITHUB_TOKEN"):
        return os.getenv("GITHUB_TOKEN", "")
    try:
        return st.secrets.get("GITHUB_TOKEN", "")
    except FileNotFoundError:
        return ""


def render_repository_report() -> None:
    with st.sidebar:
        st.divider(); st.header("Repository")
        name = st.text_input("GitHub repository", placeholder="owner/repository")
        if st.button("Fetch latest data", type="primary", disabled=not name):
            try:
                with st.spinner("Fetching GitHub data…"):
                    result = ingest_repository(name.strip(), database, GitHubClient(github_token()))
                st.success(f"Updated: {result['commits']} commits, {result['issues']} issues")
            except Exception as error:
                st.error(f"Could not fetch {name}: {error}")

    with database.connect() as conn:
        choices = repositories(conn)
    if choices.empty:
        st.info("Enter a public GitHub repository in the sidebar and select **Fetch latest data** to begin.")
        return
    selected = st.sidebar.selectbox("Loaded repository", choices["full_name"].tolist())
    repo_id = int(choices.loc[choices.full_name == selected, "id"].iloc[0])
    end_date = date.today(); start_date = st.sidebar.date_input("Date range", value=(end_date - timedelta(days=90), end_date), max_value=end_date)
    start, end = start_date if isinstance(start_date, tuple) else (end_date - timedelta(days=90), end_date)

    with database.connect() as conn:
        summary = overview(conn, repo_id)
        velocity = contributor_velocity(conn, repo_id, start, end)
        resolution = issue_resolution(conn, repo_id, start, end)
        releases = release_cadence(conn, repo_id, start, end)
        growth = growth_history(conn, repo_id, start, end)

    st.subheader(selected)
    metrics = st.columns(4)
    for column, label, key in zip(metrics, ["Stars", "Forks", "Open issues", "Contributors"], ["stars", "forks", "open_issues", "contributors"]): column.metric(label, f"{summary.get(key) or 0:,}")

    left, right = st.columns(2)
    with left:
        st.subheader("Contributor velocity")
        st.plotly_chart(px.bar(velocity, x="period", y="events", color="contributor", pattern_shape="activity", barmode="stack") if not velocity.empty else go.Figure().add_annotation(text="No activity data in range", showarrow=False), use_container_width=True)
    with right:
        st.subheader("Issue resolution time")
        st.plotly_chart(px.line(resolution, x="period", y="resolution_days", markers=True, labels={"resolution_days": "Days"}) if not resolution.empty else go.Figure().add_annotation(text="No closed issues in range", showarrow=False), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Release cadence")
        st.plotly_chart(px.scatter(releases, x="period", y="days_since_previous", hover_name="tag_name", labels={"days_since_previous": "Days since previous release"}) if not releases.empty else go.Figure().add_annotation(text="No releases in range", showarrow=False), use_container_width=True)
    with right:
        st.subheader("Growth projection")
        projection = growth_forecast(growth)
        chart = go.Figure()
        if not projection.empty:
            chart.add_scatter(x=projection.period, y=projection.stars, name="Observed stars", mode="lines+markers")
            chart.add_scatter(x=projection.period, y=projection.forecast, name="30-day forecast", mode="lines", line={"dash": "dash"})
        else: chart.add_annotation(text="Collect at least two daily snapshots to forecast growth", showarrow=False)
        st.plotly_chart(chart, use_container_width=True)


def relative_created(value: str) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(value.replace("Z", "+00:00"))).total_seconds()))
    if seconds < 3600: return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400: return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def render_discovery() -> None:
    st.subheader("Fresh GitHub discovery")
    st.caption("Discover new public repositories without entering any repository name.")
    with st.sidebar:
        st.divider(); st.header("Discovery filters")
        # A form makes rapid option clicks cheap: no scans queue until Run pulse is pressed.
        with st.form("discovery_filters"):
            view = st.radio("Group by", ["Language", "Topic"], horizontal=True)
            label = st.radio("Created in", ["Last 24 hours", "Last 7 days", "Last 30 days"], horizontal=True)
            typed_token = st.text_input("Optional GitHub token", type="password", help="Held only in this browser session and sent only to api.github.com.")
            run = st.form_submit_button("Run GitHub pulse", type="primary")
        st.caption("Unauthenticated scans stay below 10 GitHub Search requests/min; a token raises this to 30/min.")
    if not run:
        st.info("Choose a grouping and time window, then select **Run GitHub pulse**. Results are cached in this session for four minutes.")
        return
    days = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30}[label]
    token = typed_token.strip() or github_token()
    try:
        with st.status("Scanning GitHub carefully…", expanded=True) as progress:
            progress.write("Using a two-request worker pool with conservative rate pacing.")
            pulse = load_pulse(view, days, token, st.session_state.pulse_cache)
            progress.update(label="GitHub pulse complete", state="complete", expanded=False)
    except Exception as error:
        st.error(f"GitHub discovery could not complete: {error}")
        return
    rows = []
    for item in pulse:
        current, previous, bucket = item["current"], item["previous"], item["bucket"]
        rows.append({"bucket": bucket.name, "repositories": current["total_count"], "previous": previous["total_count"], "delta": current["total_count"] - previous["total_count"], "color": bucket.color})
    st.caption(f"{view} totals are compared with the immediately preceding {days}-day window. Cache lifetime: {CACHE_SECONDS // 60} minutes.")
    chart = go.Figure()
    for row in rows:
        chart.add_bar(name=row["bucket"], x=[row["bucket"]], y=[row["repositories"]], marker_color=row["color"], hovertemplate=f"{row['bucket']}<br>%{{y:,}} new repos<extra></extra>")
    chart.update_layout(showlegend=False, height=360, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="New repositories", xaxis_title="")
    st.plotly_chart(chart, use_container_width=True)
    columns = st.columns(3)
    for index, row in enumerate(rows):
        columns[index % 3].metric(row["bucket"], f"{row['repositories']:,}", delta=f"{row['delta']:+,} vs prior window")
    st.subheader("Fresh finds")
    seen: dict[int, tuple[dict, str, str]] = {}
    for item in pulse:
        for repo in item["current"]["items"]:
            seen.setdefault(repo["id"], (repo, item["bucket"].name, item["bucket"].color))
    for repo, bucket, color in sorted(seen.values(), key=lambda entry: entry[0]["stargazers_count"], reverse=True)[:12]:
        name, description = escape(repo["full_name"]), escape(repo.get("description") or "No description yet.")
        language, url = escape(repo.get("language") or bucket), escape(repo["html_url"], quote=True)
        st.markdown(f"<div style='border-left:5px solid {color}; padding:0.4rem 0 0.4rem 0.8rem; margin:.45rem 0'><a href='{url}' target='_blank' style='color:{color}; font-weight:700'>{name} ↗</a> <span style='color:#8b8b95'> · created {relative_created(repo['created_at'])} · ★ {repo['stargazers_count']:,}</span><br><span style='color:#9a9aa3'>{description}</span><br><code>{language}</code></div>", unsafe_allow_html=True)


if page == "Repository report":
    render_repository_report()
else:
    render_discovery()

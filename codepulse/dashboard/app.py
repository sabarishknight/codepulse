from __future__ import annotations

import os
import sys
from datetime import date, timedelta
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

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="CodePulse", page_icon="⚡", layout="wide")
st.title("⚡ CodePulse")
st.caption("Real-time GitHub intelligence for open-source projects")

db_path = os.getenv("CODEPULSE_DB_PATH", str(ROOT / "data" / "codepulse.db"))
database = Database(db_path); database.initialize()

with st.sidebar:
    st.header("Repository")
    name = st.text_input("GitHub repository", placeholder="owner/repository")
    if st.button("Fetch latest data", type="primary", disabled=not name):
        try:
            with st.spinner("Fetching GitHub data…"):
                result = ingest_repository(name.strip(), database, GitHubClient(os.getenv("GITHUB_TOKEN")))
            st.success(f"Updated: {result['commits']} commits, {result['issues']} issues")
        except Exception as error:
            st.error(f"Could not fetch {name}: {error}")

with database.connect() as conn:
    choices = repositories(conn)
if choices.empty:
    st.info("Enter a public GitHub repository in the sidebar and select **Fetch latest data** to begin.")
    st.stop()
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

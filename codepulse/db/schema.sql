PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS repositories (
  id INTEGER PRIMARY KEY,
  full_name TEXT UNIQUE NOT NULL,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  html_url TEXT,
  default_branch TEXT,
  created_at TEXT,
  updated_at TEXT,
  fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contributors (
  id INTEGER PRIMARY KEY,
  login TEXT UNIQUE NOT NULL,
  avatar_url TEXT,
  html_url TEXT
);

CREATE TABLE IF NOT EXISTS commits (
  sha TEXT PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  contributor_id INTEGER REFERENCES contributors(id),
  authored_at TEXT NOT NULL,
  message TEXT,
  url TEXT
);

CREATE TABLE IF NOT EXISTS issues (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  author_id INTEGER REFERENCES contributors(id),
  number INTEGER NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  closed_at TEXT,
  updated_at TEXT,
  comments INTEGER DEFAULT 0,
  html_url TEXT,
  UNIQUE(repository_id, number)
);

CREATE TABLE IF NOT EXISTS pull_requests (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  author_id INTEGER REFERENCES contributors(id),
  number INTEGER NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL,
  closed_at TEXT,
  merged_at TEXT,
  updated_at TEXT,
  additions INTEGER,
  deletions INTEGER,
  changed_files INTEGER,
  html_url TEXT,
  UNIQUE(repository_id, number)
);

CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  tag_name TEXT NOT NULL,
  name TEXT,
  published_at TEXT,
  created_at TEXT NOT NULL,
  prerelease INTEGER NOT NULL DEFAULT 0,
  html_url TEXT,
  UNIQUE(repository_id, tag_name)
);

-- Point-in-time snapshots make historical growth available after the first run.
CREATE TABLE IF NOT EXISTS repository_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL,
  stars INTEGER NOT NULL,
  forks INTEGER NOT NULL,
  open_issues INTEGER NOT NULL,
  UNIQUE(repository_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_commits_repo_date ON commits(repository_id, authored_at);
CREATE INDEX IF NOT EXISTS idx_issues_repo_date ON issues(repository_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prs_repo_date ON pull_requests(repository_id, created_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_repo_date ON repository_snapshots(repository_id, captured_at);

CREATE VIEW IF NOT EXISTS contributor_velocity AS
SELECT activity.repository_id, activity.contributor_id, u.login, activity.week,
       SUM(activity.commits) AS commits, SUM(activity.pull_requests) AS pull_requests
FROM (
  SELECT repository_id, contributor_id, strftime('%Y-%W', authored_at) AS week,
         COUNT(*) AS commits, 0 AS pull_requests
  FROM commits GROUP BY repository_id, contributor_id, week
  UNION ALL
  SELECT repository_id, author_id, strftime('%Y-%W', created_at) AS week,
         0 AS commits, COUNT(*) AS pull_requests
  FROM pull_requests GROUP BY repository_id, author_id, week
) activity LEFT JOIN contributors u ON u.id = activity.contributor_id
GROUP BY activity.repository_id, activity.contributor_id, u.login, activity.week;

CREATE VIEW IF NOT EXISTS issue_resolution_time AS
SELECT repository_id, id AS issue_id,
       julianday(closed_at) - julianday(created_at) AS resolution_days
FROM issues WHERE closed_at IS NOT NULL;

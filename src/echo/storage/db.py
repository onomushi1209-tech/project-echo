"""SQLite connection management and schema initialization.

All SQL in Echo lives under ``echo.storage`` -- see repository.py for
queries. This module only owns the schema and connection helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_sequences (
    vertical TEXT NOT NULL,
    seq_date TEXT NOT NULL,
    last_seq INTEGER NOT NULL,
    PRIMARY KEY (vertical, seq_date)
);

CREATE TABLE IF NOT EXISTS trends (
    trend_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL UNIQUE,
    vertical TEXT NOT NULL,
    topic TEXT NOT NULL,
    keywords_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    velocity REAL NOT NULL,
    novelty REAL NOT NULL,
    relevance REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS research (
    research_id TEXT PRIMARY KEY,
    trend_id TEXT NOT NULL REFERENCES trends (trend_id),
    trace_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    key_facts_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    source_quality REAL NOT NULL,
    conflicting_information INTEGER NOT NULL,
    confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    score_id TEXT PRIMARY KEY,
    trend_id TEXT NOT NULL REFERENCES trends (trend_id),
    trace_id TEXT NOT NULL,
    attention_score REAL NOT NULL,
    relevance_score REAL NOT NULL,
    novelty_score REAL NOT NULL,
    timeliness_score REAL NOT NULL,
    source_score REAL NOT NULL,
    monetization_score REAL NOT NULL,
    risk_score REAL NOT NULL,
    final_score REAL NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    trend_id TEXT NOT NULL REFERENCES trends (trend_id),
    trace_id TEXT NOT NULL,
    vertical TEXT NOT NULL,
    content_type TEXT NOT NULL,
    hook TEXT NOT NULL,
    body TEXT NOT NULL,
    cta TEXT,
    sources_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    generated_at TEXT NOT NULL,
    compliance_risk_score REAL NOT NULL DEFAULT 0,
    compliance_flags_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL UNIQUE REFERENCES drafts (draft_id),
    trace_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    review_reason TEXT,
    reviewer_note TEXT,
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS published_posts (
    post_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES drafts (draft_id),
    trace_id TEXT NOT NULL,
    x_post_id TEXT NOT NULL,
    published_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS performance (
    snapshot_id TEXT PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES published_posts (post_id),
    trace_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    impressions INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    reposts INTEGER NOT NULL DEFAULT 0,
    bookmarks INTEGER NOT NULL DEFAULT 0,
    profile_visits INTEGER NOT NULL DEFAULT 0,
    followers_gained INTEGER NOT NULL DEFAULT 0,
    link_clicks INTEGER NOT NULL DEFAULT 0
);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane defaults. Caller is responsible for closing it."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create the database file and all tables if they do not already exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()

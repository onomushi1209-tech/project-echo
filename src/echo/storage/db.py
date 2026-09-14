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
    relevance REAL NOT NULL,
    freshness REAL NOT NULL DEFAULT 0.5,
    source_quality REAL NOT NULL DEFAULT 0.5,
    source_count INTEGER NOT NULL DEFAULT 1,
    cross_source_confirmation REAL NOT NULL DEFAULT 0.0
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
    confidence REAL NOT NULL,
    source_assessments_json TEXT NOT NULL DEFAULT '[]',
    primary_source_present INTEGER NOT NULL DEFAULT 0,
    independent_source_count INTEGER NOT NULL DEFAULT 0,
    research_status TEXT NOT NULL DEFAULT 'ready',
    researched_at TEXT
);

-- STEP 3: Research Intelligence ---------------------------------------------

CREATE TABLE IF NOT EXISTS research_claims (
    claim_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research (research_id),
    text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    supporting_source_ids_json TEXT NOT NULL,
    contradicting_source_ids_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_evidence (
    evidence_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research (research_id),
    source_item_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    is_primary_source INTEGER NOT NULL,
    reliability_tier TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_conflicts (
    conflict_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research (research_id),
    claim_id TEXT,
    evidence_id_a TEXT NOT NULL,
    evidence_id_b TEXT NOT NULL,
    source_key_a TEXT NOT NULL,
    source_key_b TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    severity TEXT NOT NULL
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

-- STEP 2: Source & Trend Intelligence -------------------------------------

CREATE TABLE IF NOT EXISTS source_items (
    source_item_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    vertical TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    source_name TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    content TEXT NOT NULL,
    language TEXT NOT NULL,
    UNIQUE (canonical_url)
);

CREATE TABLE IF NOT EXISTS source_fetch_runs (
    run_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    vertical TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    items_fetched INTEGER NOT NULL DEFAULT 0,
    items_normalized INTEGER NOT NULL DEFAULT 0,
    items_age_filtered INTEGER NOT NULL DEFAULT 0,
    items_item_limit_filtered INTEGER NOT NULL DEFAULT 0,
    items_deduplicated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_failures (
    failure_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    vertical TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    error_type TEXT NOT NULL,
    message TEXT NOT NULL
);
"""

# Columns added after a table's initial release. Applied by
# _migrate_schema() via `ALTER TABLE ... ADD COLUMN`, guarded by checking
# PRAGMA table_info() first -- SQLite has no `ADD COLUMN IF NOT EXISTS`,
# so idempotency is enforced here in Python rather than in SQL. This lets
# a database created by an older version of this schema upgrade in place;
# a fresh database already gets these columns from CREATE TABLE above, so
# the loop below is a no-op for it. One entry per table; never drops or
# renames anything.
_ADDITIVE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "trends": (
        ("freshness", "REAL NOT NULL DEFAULT 0.5"),
        ("source_quality", "REAL NOT NULL DEFAULT 0.5"),
        ("source_count", "INTEGER NOT NULL DEFAULT 1"),
        ("cross_source_confirmation", "REAL NOT NULL DEFAULT 0.0"),
    ),
    # Pre-Commit Hardening: source ingestion upper bounds observability.
    "source_fetch_runs": (
        ("items_age_filtered", "INTEGER NOT NULL DEFAULT 0"),
        ("items_item_limit_filtered", "INTEGER NOT NULL DEFAULT 0"),
    ),
    # STEP 3: Research Intelligence -- scalar rollups added directly to
    # `research`; claims/evidence/conflicts get their own tables (above).
    "research": (
        ("source_assessments_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("primary_source_present", "INTEGER NOT NULL DEFAULT 0"),
        ("independent_source_count", "INTEGER NOT NULL DEFAULT 0"),
        ("research_status", "TEXT NOT NULL DEFAULT 'ready'"),
        ("researched_at", "TEXT"),
    ),
}


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sane defaults. Caller is responsible for closing it."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Create the database file and all tables if they do not already exist.

    Idempotent: safe to call on an already-initialized database (STEP 1 or
    STEP 2 schema) -- CREATE TABLE IF NOT EXISTS leaves existing tables
    untouched, and _migrate_schema only adds columns that are missing.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Additive, idempotent column migrations for databases created by an
    older version of this schema (e.g. a STEP 1 database being upgraded to
    STEP 2, or a pre-hardening STEP 2 database). Never drops or renames
    anything."""
    for table_name, columns in _ADDITIVE_COLUMNS.items():
        existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
        for column_name, column_ddl in columns:
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")

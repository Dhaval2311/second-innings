"""SQLite database schema for Second Innings."""
from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT    NOT NULL,
    company      TEXT    NOT NULL,
    role         TEXT    NOT NULL,
    source_url   TEXT    NOT NULL UNIQUE,
    location     TEXT    DEFAULT '',
    experience   TEXT    DEFAULT '',
    posted       TEXT    DEFAULT '',
    openings     TEXT    DEFAULT '',
    applicants   TEXT    DEFAULT '',
    work_mode    TEXT    DEFAULT '',
    apply_type   TEXT    DEFAULT 'unknown'
                         CHECK(apply_type IN ('easy_apply','company_site','unknown')),
    status       TEXT    DEFAULT 'new',
    score        INTEGER DEFAULT 0,
    ai_score     INTEGER,
    jd_text      TEXT    DEFAULT '',
    cover_letter TEXT    DEFAULT '',
    core_match   TEXT    DEFAULT '',
    bonus_match  TEXT    DEFAULT '',
    duplicate_of TEXT    DEFAULT '',
    notes        TEXT    DEFAULT '',
    next_action  TEXT    DEFAULT '',
    applied_date TEXT    DEFAULT '',
    search_label TEXT    DEFAULT '',
    external_url        TEXT DEFAULT '',
    contact_name        TEXT DEFAULT '',
    contact_email       TEXT DEFAULT '',
    contact_profile_url TEXT DEFAULT '',
    scraped_at   TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at   TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS screening_answers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT    NOT NULL UNIQUE,
    answer      TEXT    NOT NULL,
    source      TEXT    DEFAULT 'user'
                        CHECK(source IN ('rule','ai','user','learned')),
    confidence  REAL    DEFAULT 1.0,
    created_at  TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    updated_at  TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS pending_inputs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    question    TEXT    NOT NULL,
    context     TEXT    DEFAULT '',
    status      TEXT    DEFAULT 'waiting'
                        CHECK(status IN ('waiting','answered','skipped')),
    answer      TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    answered_at TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS content_drafts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    type       TEXT    NOT NULL
                       CHECK(type IN ('cover_letter','cold_email','linkedin_dm')),
    content    TEXT    NOT NULL,
    created_at TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT    NOT NULL,
    label            TEXT    DEFAULT '',
    jobs_found       INTEGER DEFAULT 0,
    jobs_new         INTEGER DEFAULT 0,
    jobs_duplicate   INTEGER DEFAULT 0,
    run_at           TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
    duration_seconds REAL    DEFAULT 0
);

-- Indices
CREATE INDEX IF NOT EXISTS idx_jobs_status      ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_source      ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_apply_type  ON jobs(apply_type);
CREATE INDEX IF NOT EXISTS idx_jobs_score       ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped_at  ON jobs(scraped_at);
CREATE INDEX IF NOT EXISTS idx_pending_status   ON pending_inputs(status);
"""

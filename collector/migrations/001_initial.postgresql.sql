-- PostgreSQL schema version 1. Apply once to an empty collector database.
-- Store also bootstraps these same SQLAlchemy tables for local SQLite tests.
BEGIN;
CREATE TABLE collector_schema_versions (version INTEGER PRIMARY KEY);
INSERT INTO collector_schema_versions VALUES (1);
CREATE TABLE collector_keys (key VARCHAR(64) PRIMARY KEY);
CREATE TABLE collector_jobs (
  job_id VARCHAR(36) PRIMARY KEY,
  key VARCHAR(64) NOT NULL,
  video_id VARCHAR(64) NOT NULL,
  options JSON NOT NULL,
  state VARCHAR(24) NOT NULL,
  created_at DOUBLE PRECISION NOT NULL,
  updated_at DOUBLE PRECISION NOT NULL,
  collected_at DOUBLE PRECISION,
  pause_reason VARCHAR,
  result JSON
);
CREATE INDEX ix_collector_jobs_key ON collector_jobs (key);
CREATE INDEX ix_collector_jobs_video_id ON collector_jobs (video_id);
CREATE INDEX ix_collector_jobs_state ON collector_jobs (state);
CREATE TABLE collector_raw_responses (
  job_id VARCHAR(36), sha256 VARCHAR(64), path VARCHAR NOT NULL,
  size INTEGER NOT NULL, PRIMARY KEY (job_id, sha256)
);
CREATE TABLE collector_snapshots (
  job_id VARCHAR(36) PRIMARY KEY, video_id VARCHAR(64) NOT NULL,
  collected_at DOUBLE PRECISION NOT NULL, metrics JSON NOT NULL
);
COMMIT;

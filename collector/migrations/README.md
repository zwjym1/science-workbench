# Collector schema version 1

`001_initial.postgresql.sql` is the initial PostgreSQL migration. Apply once to an empty database with `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f collector/migrations/001_initial.postgresql.sql` (use a libpq PostgreSQL URL, not the SQLAlchemy `+psycopg` form).

`Store` bootstraps the equivalent version-1 SQLAlchemy schema for SQLite and PostgreSQL. Production SQLAlchemy URLs use `postgresql+psycopg://...`. Future schema changes require another explicit migration; `create_all` does not migrate existing columns.

Every job retains its immutable completion result, and each completion records metrics in `collector_snapshots`. `finish` updates job state, raw indexes, and the snapshot in one database transaction. Raw files are written beforehand with SHA256 content addresses, fsync, and no-replace atomic publication; a failed database transaction can leave an unreferenced raw file, but cannot erase evidence. Raw descriptors contain relative paths/hash/size, never the original body. `finish` accepts descriptors in `result.raw_responses` and metrics in `result.metrics`.

Call `recover_interrupted()` only at exclusive worker startup after obtaining the worker/profile process lock. It marks unfinished work `interrupted`; it never retries. Explicit `resume` is needed. Any paused job stops new claims across this Douyin source (already submitted jobs remain queued). `pause(job_id, reason, result=...)` atomically preserves available partial results and their raw indexes. A paused job additionally requires `conditions_changed=True`, and keeps its original pause reason. Submissions (including refresh or changed options) cannot bypass an existing paused/interrupted job for the video. Cache TTL defaults to 3600 seconds and can be configured with `store.cache_ttl_seconds`; cache entries include collection timestamp and age. Options are part of the cache key.

Validation: SQLite state-machine/concurrency tests are automated. PostgreSQL integration and server restart recovery have not been executed by this implementation task; SQL delivery is not a claim of PostgreSQL runtime verification.


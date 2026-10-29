-- Local synthetic SQLite storage, not a production PostgreSQL migration.
CREATE TABLE IF NOT EXISTS eligibility_assessments (
    assessment_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'PRELIMINARY_REQUIREMENTS_SATISFIED',
        'PRELIMINARY_REQUIREMENTS_NOT_SATISFIED',
        'ADDITIONAL_INFORMATION_REQUIRED', 'MANUAL_REVIEW_REQUIRED'
    )),
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS eligibility_assessments_application
    ON eligibility_assessments(application_id, assessed_at);
CREATE TABLE IF NOT EXISTS eligibility_runs (
    actor_id TEXT NOT NULL,
    key_sha256 TEXT NOT NULL CHECK (length(key_sha256) = 64),
    request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint) = 64),
    assessment_id TEXT NOT NULL UNIQUE REFERENCES eligibility_assessments(assessment_id),
    PRIMARY KEY (actor_id, key_sha256)
);
CREATE TABLE IF NOT EXISTS eligibility_audit (
    event_id TEXT PRIMARY KEY,
    assessment_id TEXT UNIQUE REFERENCES eligibility_assessments(assessment_id),
    application_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS eligibility_assessment_immutable
    BEFORE UPDATE ON eligibility_assessments
    BEGIN SELECT RAISE(ABORT, 'Assessment snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS eligibility_audit_immutable
    BEFORE UPDATE ON eligibility_audit
    BEGIN SELECT RAISE(ABORT, 'Audit events are immutable'); END;
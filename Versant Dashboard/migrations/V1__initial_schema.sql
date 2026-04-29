-- =============================================================================
-- Brainbase Operations Dashboard — Initial Schema
-- Run order: this file is auto-executed by Docker on first container start,
-- or run manually: psql brainbase_dashboard < migrations/V1__initial_schema.sql
-- =============================================================================

-- WORKERS
CREATE TABLE IF NOT EXISTS workers (
    worker_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    lob_name    TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ,
    pulled_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- DEPLOYMENTS
CREATE TABLE IF NOT EXISTS deployments (
    deployment_id TEXT PRIMARY KEY,
    worker_id     TEXT NOT NULL REFERENCES workers(worker_id),
    name          TEXT NOT NULL,
    environment   TEXT NOT NULL CHECK (environment IN ('prod','test','dev')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    pulled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deployments_worker ON deployments(worker_id);
CREATE INDEX IF NOT EXISTS idx_deployments_env    ON deployments(worker_id, environment);

-- VOICE ANALYSIS SNAPSHOTS
CREATE TABLE IF NOT EXISTS voice_analysis_snapshots (
    id                     SERIAL PRIMARY KEY,
    worker_id              TEXT NOT NULL REFERENCES workers(worker_id),
    deployment_ids         TEXT[],
    period_start           TIMESTAMPTZ NOT NULL,
    period_end             TIMESTAMPTZ NOT NULL,
    granularity            TEXT NOT NULL CHECK (granularity IN ('daily','weekly','monthly','yearly')),
    total_calls            INTEGER NOT NULL DEFAULT 0,
    total_minutes          NUMERIC(14,4) NOT NULL DEFAULT 0,
    total_transfers        INTEGER NOT NULL DEFAULT 0,
    total_transfer_minutes NUMERIC(14,4) NOT NULL DEFAULT 0,
    average_call_duration  NUMERIC(10,2),
    pulled_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE NULLS NOT DISTINCT (worker_id, period_start, period_end, granularity, deployment_ids)
);
CREATE INDEX IF NOT EXISTS idx_vas_worker_period ON voice_analysis_snapshots(worker_id, period_start DESC);

-- CALL LOGS
CREATE TABLE IF NOT EXISTS call_logs (
    log_id              TEXT PRIMARY KEY,
    worker_id           TEXT NOT NULL REFERENCES workers(worker_id),
    deployment_id       TEXT REFERENCES deployments(deployment_id),
    session_id          TEXT,
    external_call_id    TEXT,
    direction           TEXT,
    from_number         TEXT,
    to_number           TEXT,
    start_time          TIMESTAMPTZ,
    end_time            TIMESTAMPTZ,
    duration_seconds    INTEGER,
    status              TEXT,
    disposition         TEXT,
    tee_time            TIMESTAMPTZ,
    confirmation_number TEXT,
    caller_verified     BOOLEAN,
    response_latency_ms INTEGER,
    transcription       TEXT,
    recording_url       TEXT,
    transfer_count      INTEGER DEFAULT 0,
    raw_data            JSONB,
    pulled_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_call_logs_worker_time ON call_logs(worker_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_call_logs_deployment  ON call_logs(deployment_id, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_call_logs_disposition ON call_logs(worker_id, disposition);
CREATE INDEX IF NOT EXISTS idx_call_logs_start       ON call_logs(start_time DESC);

-- RUNTIME ERRORS
CREATE TABLE IF NOT EXISTS runtime_errors (
    error_id      TEXT PRIMARY KEY,
    worker_id     TEXT NOT NULL REFERENCES workers(worker_id),
    deployment_id TEXT REFERENCES deployments(deployment_id),
    error_type    TEXT,
    service       TEXT,
    severity      TEXT,
    message       TEXT,
    resolved      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ,
    raw_data      JSONB,
    pulled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_runtime_errors_worker     ON runtime_errors(worker_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_errors_deployment ON runtime_errors(deployment_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runtime_errors_severity   ON runtime_errors(worker_id, severity, created_at DESC);

-- ECHO SCORECARDS
CREATE TABLE IF NOT EXISTS echo_scorecards (
    scorecard_id  TEXT PRIMARY KEY,
    worker_id     TEXT REFERENCES workers(worker_id),
    name          TEXT,
    overall_score NUMERIC(5,2),
    run_time      TIMESTAMPTZ,
    details       JSONB,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    pulled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- PLATFORM INCIDENTS
CREATE TABLE IF NOT EXISTS platform_incidents (
    id             SERIAL PRIMARY KEY,
    incident_start TIMESTAMPTZ NOT NULL,
    incident_end   TIMESTAMPTZ,
    description    TEXT,
    severity       TEXT,
    source         TEXT NOT NULL DEFAULT 'status.brainbase.co',
    pulled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- BILLING CONFIG
CREATE TABLE IF NOT EXISTS billing_config (
    id              SERIAL PRIMARY KEY,
    worker_id       TEXT NOT NULL REFERENCES workers(worker_id),
    tier_name       TEXT NOT NULL,
    min_minutes     NUMERIC(14,2) NOT NULL,
    max_minutes     NUMERIC(14,2),
    rate_per_minute NUMERIC(10,6) NOT NULL,
    overage_rate    NUMERIC(10,6),
    echo_surcharge  NUMERIC(10,2) NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'USD',
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    billing_timezone TEXT NOT NULL DEFAULT 'America/New_York'
);

-- KPI GOALS
CREATE TABLE IF NOT EXISTS kpi_goals (
    id              SERIAL PRIMARY KEY,
    worker_id       TEXT NOT NULL REFERENCES workers(worker_id),
    kpi_key         TEXT NOT NULL,
    kpi_name        TEXT NOT NULL,
    kpi_description TEXT,
    goal_operator   TEXT NOT NULL CHECK (goal_operator IN ('gte','lte','eq')),
    goal_value      NUMERIC(10,4) NOT NULL,
    goal_unit       TEXT DEFAULT '%',
    effective_from  DATE NOT NULL,
    effective_to    DATE
);
CREATE INDEX IF NOT EXISTS idx_kpi_goals_worker ON kpi_goals(worker_id);

-- SLA CONFIG
CREATE TABLE IF NOT EXISTS sla_config (
    id                 SERIAL PRIMARY KEY,
    worker_id          TEXT NOT NULL REFERENCES workers(worker_id),
    deployment_id      TEXT REFERENCES deployments(deployment_id),
    sla_target_pct     NUMERIC(6,3) NOT NULL,
    penalty_per_hour   NUMERIC(10,2) NOT NULL DEFAULT 0,
    measurement_window TEXT NOT NULL DEFAULT 'monthly',
    effective_from     DATE NOT NULL,
    effective_to       DATE
);

-- PIPELINE RUNS
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            SERIAL PRIMARY KEY,
    source_name   TEXT NOT NULL,
    worker_id     TEXT,
    started_at    TIMESTAMPTZ NOT NULL,
    completed_at  TIMESTAMPTZ,
    row_count     INTEGER,
    status        TEXT NOT NULL CHECK (status IN ('success','failure','running')),
    error_message TEXT,
    retry_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source ON pipeline_runs(source_name, completed_at DESC);

-- ALERT RULES
CREATE TABLE IF NOT EXISTS alert_rules (
    id         SERIAL PRIMARY KEY,
    worker_id  TEXT REFERENCES workers(worker_id),
    alert_type TEXT NOT NULL,
    threshold  NUMERIC(10,4),
    channel    TEXT NOT NULL,
    target     TEXT NOT NULL,
    is_active  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

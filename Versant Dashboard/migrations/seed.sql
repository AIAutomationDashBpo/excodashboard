-- =============================================================================
-- Seed Data
-- Replace VERSANT_WORKER_ID and BARTACO_WORKER_ID with real IDs from the API
-- after running pull_workers.py for the first time.
-- =============================================================================

-- ── Versant KPI Goals ────────────────────────────────────────────────────────
INSERT INTO kpi_goals (worker_id, kpi_key, kpi_name, kpi_description,
    goal_operator, goal_value, goal_unit, effective_from)
VALUES
    ('VERSANT_WORKER_ID', 'no_pii_leaks',  'No PII Leaks',
     'Bot must not reveal caller info unless caller has been validated.',
     'gte', 100.0, '%', '2026-01-01'),
    ('VERSANT_WORKER_ID', 'accuracy',      'Accuracy & Performance',
     'Bot correctly understands requests and selects the right intent.',
     'gte', 95.0,  '%', '2026-01-01'),
    ('VERSANT_WORKER_ID', 'response_time', 'Response Time',
     'Time for bot to provide first and subsequent responses.',
     'lte', 2000.0,'ms','2026-01-01'),
    ('VERSANT_WORKER_ID', 'success_rate',  'Success Rate',
     'Conversations completed without human intervention.',
     'gte', 85.0,  '%', '2026-01-01'),
    ('VERSANT_WORKER_ID', 'booking_rate',  'Booking Conversion Rate',
     'Percentage of inbound calls that result in a confirmed booking.',
     'gte', 52.0,  '%', '2026-01-01')
ON CONFLICT DO NOTHING;

-- ── Versant SLA ───────────────────────────────────────────────────────────────
INSERT INTO sla_config (worker_id, sla_target_pct, penalty_per_hour, measurement_window, effective_from)
VALUES ('VERSANT_WORKER_ID', 99.5, 250.00, 'monthly', '2026-01-01')
ON CONFLICT DO NOTHING;

-- ── Versant Billing Tiers ────────────────────────────────────────────────────
-- Adjust these to match the real contract.
INSERT INTO billing_config
    (worker_id, tier_name, min_minutes, max_minutes, rate_per_minute,
     overage_rate, echo_surcharge, effective_from)
VALUES
    ('VERSANT_WORKER_ID', 'Base Tier',   0,     40000, 0.004500, 0.006000, 1820.00, '2026-01-01'),
    ('VERSANT_WORKER_ID', 'Growth Tier', 40001, 80000, 0.003800, 0.005200, 1820.00, '2026-01-01'),
    ('VERSANT_WORKER_ID', 'Scale Tier',  80001, NULL,  0.003000, 0.004500, 1820.00, '2026-01-01')
ON CONFLICT DO NOTHING;

-- ── Bartaco KPI Goals ────────────────────────────────────────────────────────
INSERT INTO kpi_goals (worker_id, kpi_key, kpi_name, kpi_description,
    goal_operator, goal_value, goal_unit, effective_from)
VALUES
    ('BARTACO_WORKER_ID', 'success_rate', 'Success Rate',
     'Conversations completed without human intervention.',
     'gte', 85.0, '%', '2026-01-01'),
    ('BARTACO_WORKER_ID', 'response_time', 'Response Time',
     'Time for bot to provide first and subsequent responses.',
     'lte', 2000.0, 'ms', '2026-01-01')
ON CONFLICT DO NOTHING;

-- ── Bartaco SLA ───────────────────────────────────────────────────────────────
INSERT INTO sla_config (worker_id, sla_target_pct, penalty_per_hour, measurement_window, effective_from)
VALUES ('BARTACO_WORKER_ID', 99.5, 250.00, 'monthly', '2026-01-01')
ON CONFLICT DO NOTHING;

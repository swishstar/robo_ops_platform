-- Robo Reliance Inner Loop Platform — relational schema bootstrap
-- Source: docs/system_spec.md §3 Relational Schema Blueprint

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- State progression indicator for technician visits
CREATE TYPE visit_status AS ENUM (
    'initiated',
    'active',
    'pending_approval',
    'completed',
    'failed'
);

-- 1. Visit Metadata Records
CREATE TABLE visits (
    visit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slack_channel_id VARCHAR(100),
    google_space_id VARCHAR(255) UNIQUE,
    location_string TEXT NOT NULL,
    metadata_poc JSONB NOT NULL,
    current_state visit_status NOT NULL DEFAULT 'initiated',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_visits_current_state ON visits (current_state);
CREATE INDEX idx_visits_slack_channel_id ON visits (slack_channel_id);

-- 2. Labor Tracking Ledger
CREATE TABLE labor_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    visit_id UUID REFERENCES visits(visit_id) ON DELETE CASCADE,
    technician_identity VARCHAR(255) NOT NULL,
    clock_in TIMESTAMP WITH TIME ZONE,
    clock_out TIMESTAMP WITH TIME ZONE,
    extracted_findings TEXT,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_labor_logs_visit_id ON labor_logs (visit_id);

-- 3. Financial Transaction Ledger
CREATE TABLE financial_ledgers (
    ledger_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    visit_id UUID REFERENCES visits(visit_id) ON DELETE CASCADE,
    calculated_hours NUMERIC(6, 2),
    invoice_cents INT NOT NULL,
    payout_cents INT NOT NULL,
    approval_state VARCHAR(50) NOT NULL DEFAULT 'pending_review',
    qbo_invoice_reference VARCHAR(100),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_financial_ledgers_visit_id ON financial_ledgers (visit_id);
CREATE INDEX idx_financial_ledgers_approval_state ON financial_ledgers (approval_state);

-- 4. Immutable Administrative Audit Log
CREATE TABLE immutable_audit_trail (
    audit_id BIGSERIAL PRIMARY KEY,
    visit_id UUID,
    execution_context VARCHAR(100) NOT NULL,
    input_payload JSONB,
    output_receipt JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_immutable_audit_trail_visit_id ON immutable_audit_trail (visit_id);
CREATE INDEX idx_immutable_audit_trail_execution_context ON immutable_audit_trail (execution_context);

-- Finance approval tokens for human-in-the-loop callbacks (Phase 3 gateway)
CREATE TABLE finance_approval_tokens (
    token_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ledger_id UUID NOT NULL REFERENCES financial_ledgers(ledger_id) ON DELETE CASCADE,
    visit_id UUID NOT NULL REFERENCES visits(visit_id) ON DELETE CASCADE,
    approval_token VARCHAR(128) NOT NULL UNIQUE,
    consumed BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_finance_approval_tokens_token ON finance_approval_tokens (approval_token);

-- Platform configuration registry (MCP toggles, billing defaults, HITL policy)
CREATE TABLE platform_configs (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO platform_configs (config_key, config_value) VALUES
(
    'finance',
    '{"approval_token_ttl_hours": 72, "require_operator_identity": true}'::jsonb
),
(
    'quickbooks',
    '{"enabled": true, "customer_reference_default": "RR-GENERAL-CUSTOMER"}'::jsonb
),
(
    'linkedin',
    '{"post_enabled": true, "summary_prefix": "Robo Reliance Field Ops:"}'::jsonb
);

-- Keep visits.updated_at current on row changes
CREATE OR REPLACE FUNCTION set_visits_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_visits_updated_at
    BEFORE UPDATE ON visits
    FOR EACH ROW
    EXECUTE PROCEDURE set_visits_updated_at();

CREATE OR REPLACE FUNCTION set_financial_ledgers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_financial_ledgers_updated_at
    BEFORE UPDATE ON financial_ledgers
    FOR EACH ROW
    EXECUTE PROCEDURE set_financial_ledgers_updated_at();

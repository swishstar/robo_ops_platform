-- Migration: platform configuration registry (Phase 3)
CREATE TABLE IF NOT EXISTS platform_configs (
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
)
ON CONFLICT (config_key) DO NOTHING;

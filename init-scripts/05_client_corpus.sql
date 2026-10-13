-- Multi-client SOP corpus routing (G5e)
-- client_id on visits selects which Vertex AI Search SOP engine to query.

ALTER TABLE visits
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_visits_client_id ON visits (client_id);

-- Registry of clients + per-client SOP serving endpoints.
-- Keys under "endpoints" map client_id → Discovery Engine servingConfig URL.
-- Missing client falls back to the shared SOP_SEARCH_ENDPOINT env var.
INSERT INTO platform_configs (config_key, config_value) VALUES
(
    'clients',
    '{
      "default_client_id": "chef",
      "clients": [
        {"id": "chef", "display_name": "Chef"},
        {"id": "roboreliance", "display_name": "Robo Reliance (internal)"}
      ]
    }'::jsonb
),
(
    'client_sop_endpoints',
    '{
      "chef": "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/sop-chef/servingConfigs/default_search",
      "roboreliance": "https://discoveryengine.googleapis.com/v1/projects/robo-reliance-ops/locations/global/collections/default_collection/engines/sop-library-search/servingConfigs/default_search"
    }'::jsonb
)
ON CONFLICT (config_key) DO UPDATE
SET config_value = EXCLUDED.config_value,
    updated_at = CURRENT_TIMESTAMP;

-- Chat ingestion cursors and ad-hoc channel bindings (UI Strategy Phase 2/3)

CREATE TABLE IF NOT EXISTS channel_ingestion_cursors (
    channel_type VARCHAR(20) NOT NULL CHECK (channel_type IN ('google_chat', 'slack')),
    channel_id VARCHAR(255) NOT NULL,
    visit_id UUID REFERENCES visits(visit_id),
    last_message_time TIMESTAMP WITH TIME ZONE,
    last_message_name VARCHAR(512),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_type, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_ingestion_visit_id
    ON channel_ingestion_cursors (visit_id);

CREATE TABLE IF NOT EXISTS space_visit_bindings (
    google_space_id VARCHAR(255) PRIMARY KEY,
    visit_id UUID NOT NULL REFERENCES visits(visit_id),
    bound_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS slack_channel_visit_bindings (
    slack_channel_id VARCHAR(100) PRIMARY KEY,
    visit_id UUID NOT NULL REFERENCES visits(visit_id),
    bound_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Web chat session metadata (no message content stored — stateless turns)
CREATE TABLE IF NOT EXISTS web_chat_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_identity VARCHAR(255) NOT NULL,
    visit_id UUID REFERENCES visits(visit_id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_web_chat_sessions_user
    ON web_chat_sessions (user_identity);

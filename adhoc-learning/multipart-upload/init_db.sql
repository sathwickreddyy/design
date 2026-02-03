-- Upload Sessions Table
-- Tracks metadata for each multipart upload session with checksum verification

CREATE TABLE IF NOT EXISTS upload_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    filename VARCHAR(512) NOT NULL,
    file_size BIGINT NOT NULL,
    chunk_size INTEGER NOT NULL,
    total_parts INTEGER NOT NULL,
    completed_parts INTEGER[] DEFAULT '{}',
    
    -- Checksum fields for integrity verification
    file_hash VARCHAR(64),                    -- SHA256 of full file (hex string)
    hash_algorithm VARCHAR(20) DEFAULT 'SHA256',
    part_hashes JSONB DEFAULT '{}',           -- {"1": "md5_hex", "2": "md5_hex", ...}
    
    status VARCHAR(20) DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Index for querying by status (useful for cleanup jobs)
CREATE INDEX IF NOT EXISTS idx_upload_sessions_status ON upload_sessions(status);

-- Index for querying by created_at (useful for finding old sessions)
CREATE INDEX IF NOT EXISTS idx_upload_sessions_created_at ON upload_sessions(created_at);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_upload_sessions_updated_at 
    BEFORE UPDATE ON upload_sessions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- LabMemory schema (seekdb / OceanBase MySQL mode)
CREATE TABLE IF NOT EXISTS papers (
  id VARCHAR(32) PRIMARY KEY,
  arxiv_id VARCHAR(32) NOT NULL,
  title TEXT NOT NULL,
  authors TEXT,
  published DATE,
  abstract TEXT,
  summary_zh TEXT,
  keywords_zh VARCHAR(512),
  tags VARCHAR(255),
  pdf_path VARCHAR(512),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
  id VARCHAR(64) PRIMARY KEY,
  title TEXT NOT NULL,
  kind VARCHAR(32),
  project VARCHAR(64),
  note_date DATE,
  content TEXT NOT NULL,
  tags VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  source_type VARCHAR(16) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  source_title VARCHAR(512),
  source_url VARCHAR(512),
  chunk_index INT NOT NULL,
  section VARCHAR(255),
  page INT,
  year INT,
  tags VARCHAR(255),
  content TEXT NOT NULL,
  search_text TEXT NOT NULL,
  keywords VARCHAR(512),
  embedding VECTOR(384),
  FULLTEXT INDEX ft_chunks(search_text, keywords),
  VECTOR INDEX vidx_chunks(embedding) WITH (distance=L2, type=hnsw),
  INDEX idx_chunk_source(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS queries (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  question TEXT NOT NULL,
  filters_json TEXT,
  trace_json TEXT,
  latency_ms INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conflicts (
  id VARCHAR(64) PRIMARY KEY,
  paper_id VARCHAR(32) NOT NULL,
  memory_artifact_id VARCHAR(128) NOT NULL,
  memory_revision INT,
  memory_text TEXT,
  reason TEXT,
  status VARCHAR(16) DEFAULT 'open',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_conflict_status(status)
);

-- Append-only: every version of every desk record, written as psd-agents writes Firestore. Readers take each record's
-- latest version through the v_desk_* views.
CREATE TABLE IF NOT EXISTS desk_records (
  collection STRING NOT NULL,
  record_id STRING NOT NULL,
  written_at TIMESTAMP NOT NULL,
  record JSON
)
PARTITION BY DATE(written_at)
CLUSTER BY collection, record_id;

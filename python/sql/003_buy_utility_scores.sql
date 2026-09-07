ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_version INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_score INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS buy_band TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_confidence DOUBLE PRECISION NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_low INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_interval_high INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS score_factors JSONB NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS factor_evidence JSONB NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_concern TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS verification_reason TEXT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_position INT NULL;
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS rank_confidence TEXT NULL;
ALTER TABLE scored_listings ALTER COLUMN deal_score DROP NOT NULL;
ALTER TABLE scored_listings ALTER COLUMN value_band DROP NOT NULL;
ALTER TABLE scored_listings ALTER COLUMN hunt_fit DROP NOT NULL;
ALTER TABLE scored_listings ALTER COLUMN scam_risk DROP NOT NULL;

CREATE INDEX IF NOT EXISTS scored_listings_v2_rank_idx
  ON scored_listings (score_version, rank_position)
  WHERE score_version = 2;

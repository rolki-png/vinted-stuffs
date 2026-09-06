CREATE TABLE IF NOT EXISTS scored_listings (
  item_id BIGINT NOT NULL,
  hunt_name TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  price DECIMAL NULL,
  currency TEXT NOT NULL DEFAULT 'RON',
  brand TEXT NULL,
  size TEXT NULL,
  condition TEXT NULL,
  url TEXT NULL,
  favourite_count INT NULL,
  seller_id BIGINT NULL,
  seller_login TEXT NULL,
  seller_country TEXT NULL,
  deal_score INT NULL,
  value_band TEXT NULL,
  hunt_fit BOOL NULL,
  scam_risk TEXT NULL,
  reason TEXT NOT NULL DEFAULT '',
  has_score BOOL NOT NULL DEFAULT false,
  scored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL DEFAULT 'search',
  PRIMARY KEY (item_id, hunt_name)
);

CREATE INDEX IF NOT EXISTS scored_listings_seller_id_idx
  ON scored_listings (seller_id);

CREATE INDEX IF NOT EXISTS scored_listings_scored_at_idx
  ON scored_listings (scored_at DESC);

-- Existing clusters: add has_score / relax NOT NULL on score columns
ALTER TABLE scored_listings ADD COLUMN IF NOT EXISTS has_score BOOL NOT NULL DEFAULT false;

-- runs once on database init

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- needs `shared_preload_libraries` from addendum.conf; only the view is
-- unusable before that reload, creating it is harmless
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

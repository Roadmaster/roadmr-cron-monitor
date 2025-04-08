-- DROP TABLE IF EXISTS monitor;
CREATE TABLE IF NOT EXISTS monitor (
id INTEGER PRIMARY KEY,
name TEXT NOT NULL,
slug TEXT NOT NULL,
frequency INTEGER NOT NULL,
expires_at INTEGER NOT NULL,
 api_key TEXT NOT NULL,
last_check TEXT
)

create index if not exists idx_apikey_slug on monitor(api_key, slug);
create index if not exists idx_expires_at on monitor(expires_at);

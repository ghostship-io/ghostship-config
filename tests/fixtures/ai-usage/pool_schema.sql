-- The schema of the free inference pool's durable job ledger.
--
-- Only the columns the usage reader needs are declared here. The pool's
-- own ledger holds the same tables with the same names; the reader never
-- writes to them and never changes them.

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    identity TEXT NOT NULL,
    status TEXT NOT NULL,
    progress TEXT NOT NULL DEFAULT '{}',
    result TEXT,
    error TEXT,
    idempotency_key TEXT,
    reconcile_of TEXT,
    owner INTEGER,
    owner_lease TEXT,
    lease_until REAL,
    not_before REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(identity, idempotency_key)
);

CREATE TABLE IF NOT EXISTS inference_reservations (
    id TEXT PRIMARY KEY,
    job TEXT,
    provider TEXT,
    model TEXT,
    at REAL,
    input INTEGER,
    output INTEGER,
    usd REAL,
    neurons REAL
);

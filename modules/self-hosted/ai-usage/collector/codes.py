"""Fixed reason codes for the collector.

A reading can fail in many ways, and the failure itself can carry something
that must not leave the collector: a credential, an email address, a file
path, a URL with a token in it, or a provider's own diagnostic text. The
collector therefore never copies a failure message into a metric, a
snapshot, or the journal. Every failure is reduced to one of the fixed codes
below.

The codes are a closed set. Anything that does not map to a code is reported
as `unknown`, so a new failure cannot leak through by accident.
"""

from __future__ import annotations

# The closed vocabulary.
OK = "ok"
MISSING_CREDENTIALS = "missing_credentials"
EXPIRED_CREDENTIALS = "expired_credentials"
UNSUPPORTED = "unsupported"
HTTP_ERROR = "http_error"
HTTP_UNAUTHORIZED = "http_unauthorized"
HTTP_FORBIDDEN = "http_forbidden"
TIMEOUT = "timeout"
CONNECTION_ERROR = "connection_error"
INVALID_RESPONSE = "invalid_response"
PROTOCOL_ERROR = "protocol_error"
HANDSHAKE_REJECTED = "handshake_rejected"
RPC_FAILED = "rpc_failed"
UNAVAILABLE = "unavailable"
PROBE_FAILED = "probe_failed"
STALE_READING = "stale_reading"
# The T3 state was read but held no runtime observation in the window. It is
# not a database failure: the record is readable and simply has no event yet.
NO_RUNTIME_EVENTS = "no_runtime_events"
# The reader of a request record raised something its own fixed codes do not
# describe. It is never reported as an unreadable database, because the
# database was not what failed.
READER_ERROR = "reader_error"
UNKNOWN = "unknown"

# The reason codes of the two request readers. They are a closed set of
# fixed words as well, and they name the record that could not be read
# without naming a path: the OpenCode database and the pool ledger each
# have their own codes.
READ_CODES = frozenset(
    {
        "database_missing",
        "database_unreadable",
        # The database is readable, but another process held its write lock
        # for longer than the read could wait. It is a transient cause, not a
        # corrupt or missing record.
        "database_busy",
        # A live WAL database reported a transient I/O error while it was
        # being checkpointed. It is retried, and only a persistent one is
        # reported.
        "database_io_error",
        "database_corrupt",
        "database_schema_missing",
        "cache_unwritten",
        "ledger_missing",
        "ledger_unreadable",
        "ledger_corrupt",
        "ledger_schema_missing",
    }
)

CODES = frozenset(
    {
        OK,
        MISSING_CREDENTIALS,
        EXPIRED_CREDENTIALS,
        UNSUPPORTED,
        HTTP_ERROR,
        HTTP_UNAUTHORIZED,
        HTTP_FORBIDDEN,
        TIMEOUT,
        CONNECTION_ERROR,
        INVALID_RESPONSE,
        PROTOCOL_ERROR,
        HANDSHAKE_REJECTED,
        RPC_FAILED,
        UNAVAILABLE,
        PROBE_FAILED,
        STALE_READING,
        NO_RUNTIME_EVENTS,
        READER_ERROR,
        UNKNOWN,
    }
) | READ_CODES


def reason(code: str) -> str:
    """Return a fixed reason code, or `unknown` for anything else."""
    text = str(code or "").strip().lower()
    return text if text in CODES else UNKNOWN


def http_reason(status: int) -> str:
    """The reason code of an HTTP status."""
    if status in (401,):
        return HTTP_UNAUTHORIZED
    if status in (403,):
        return HTTP_FORBIDDEN
    if 200 <= status < 300:
        return OK
    if status:
        return HTTP_ERROR
    return CONNECTION_ERROR

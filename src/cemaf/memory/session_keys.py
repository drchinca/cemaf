"""Stable storage-key encoding for session-owned semantic memories."""

_SESSION_KEY_MARKER = "__cemaf_session__:"


def session_memory_key(*, session_id: str, key: str) -> str:
    """Return a collision-safe persisted key owned by one session."""
    return f"{_SESSION_KEY_MARKER}{len(session_id)}:{session_id}:{key}"


def session_memory_logical_key(*, session_id: str, stored_key: str) -> str | None:
    """Return the caller-facing key when ``stored_key`` belongs to ``session_id``."""
    prefix = f"{_SESSION_KEY_MARKER}{len(session_id)}:{session_id}:"
    return stored_key[len(prefix) :] if stored_key.startswith(prefix) else None


def parse_session_memory_key(stored_key: str) -> tuple[str, str] | None:
    """Decode a persisted session key without knowing its owner in advance."""
    if not stored_key.startswith(_SESSION_KEY_MARKER):
        return None
    remainder = stored_key[len(_SESSION_KEY_MARKER) :]
    length_text, separator, payload = remainder.partition(":")
    if not separator or not length_text.isdigit():
        return None
    session_length = int(length_text)
    if len(payload) <= session_length or payload[session_length] != ":":
        return None
    return payload[:session_length], payload[session_length + 1 :]

from urllib.parse import urlsplit


def server_origin(value: str) -> str:
    """Configuration URLs are server origins, never credential/query-bearing URLs."""
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise ValueError("expected an http(s) server origin without credentials, path, or query")
    _ = parts.port  # Validate malformed/out-of-range ports.
    return value.rstrip("/")

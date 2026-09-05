"""Safe, bounded provider exception diagnostics; never serialize exception state."""

import json
import os
import re
from urllib.parse import quote, quote_plus


def provider_error(exc: Exception) -> dict[str, str]:
    def sanitize(text: str) -> str:
        # Remove credential/header-bearing lines, including dictionary dumps.
        text = re.sub(
            r"(?im)^.*(?:authorization|proxy-authorization|headers|cookie|"
            r"api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|"
            r"credential|bearer\s|basic\s).*$", "[REDACTED sensitive detail]", text)
        # Environment values may also occur without labels or in encoded URLs.
        values = set()
        for value in os.environ.values():
            if value:
                values.update((value, quote(value, safe=""), quote_plus(value),
                               json.dumps(value)[1:-1]))
        if values:
            pattern = "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
        # Common unlabeled API-key forms; do not preserve request URL queries.
        text = re.sub(r"\b(?:AIza[\w-]+|sk-[\w-]+)\b", "[REDACTED]", text)
        text = re.sub(r"(https?://[^\s?'\"]+)\?[^\s'\"]+", r"\1?[REDACTED]", text)
        text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text)
        return text[:2000] or "No diagnostic message available"

    try:
        return {"type": sanitize(type(exc).__name__), "message": sanitize(str(exc))}
    except Exception:
        return {"type": "ProviderException", "message": "Diagnostic details could not be sanitized"}

"""Keep full provider diagnostics in operator logs while redacting credentials."""

import re


def redact(value: str) -> str:
    value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [redacted]", value)
    value = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
    value = re.sub(
        r"(?i)((?:api[_-]?key|token|password|secret|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s&\"']+",
        r"\1[redacted]",
        value,
    )
    return value

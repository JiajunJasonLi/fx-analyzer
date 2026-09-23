from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping


FIELDS = ("request_id", "run_id", "scope_id", "provider", "dataset", "event", "duration_seconds", "outcome")
FORBIDDEN = ("authorization", "cookie", "credential", "password", "secret", "token", "api_key", "payload", "body", "sql", "url")


class JsonFormatter(logging.Formatter):
    """Emit a bounded allowlisted event document, never arbitrary LogRecord state."""

    def format(self, record: logging.LogRecord) -> str:
        document: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_text(record.getMessage()),
        }
        for field in FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                document[field] = sanitize(value)
        context = getattr(record, "error_context", None)
        if isinstance(context, Mapping):
            document["error_context"] = sanitize(context)
        if record.exc_info:
            document["error_type"] = record.exc_info[0].__name__
        return json.dumps(document, separators=(",", ":"), sort_keys=True, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize(item)
            for key, item in value.items()
            if not any(word in str(key).lower() for word in FORBIDDEN)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value[:100]]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def sanitize_text(value: str) -> str:
    text = value.replace("\n", " ")[:1000]
    text = re.sub(r"(?i)(postgres(?:ql)?|https?)://\S+", "[redacted-url]", text)
    text = re.sub(r"(?i)(authorization|cookie|password|secret|token|api[_-]?key)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    return text

from __future__ import annotations

import logging
import re

_CONTROL_CHARS = re.compile(r"[\r\n\t\x00-\x1f\x7f]")
_MAX_LOG_VALUE_LENGTH = 300


def sanitize_for_log(value: object) -> str:
    """Strip control characters and cap length before a value reaches a log line.

    Filenames, titles and exception text can originate from an uploaded PDF and
    are not trusted: without this, a crafted value could inject fake log lines
    (CRLF injection) or flood the log with an oversized message.
    """
    text = str(value)
    text = _CONTROL_CHARS.sub(" ", text)
    if len(text) > _MAX_LOG_VALUE_LENGTH:
        text = text[:_MAX_LOG_VALUE_LENGTH] + "…"
    return text


def configure_logging(level: str = "INFO") -> None:
    """Configure the 'konverter' logger tree. Safe to call more than once."""
    root = logging.getLogger("konverter")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        root.addHandler(handler)
        root.propagate = False
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"konverter.{name}")


class DocumentLoggerAdapter(logging.LoggerAdapter):
    """Prefixes log lines with a sanitized "[document_id]" tag.

    Only pass static stage descriptions, counts and durations through this
    adapter. Never log extracted document content (block text, metadata field
    values, review item text) — the source PDF may contain sensitive or
    personal material that must not end up in application logs.
    """

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        return f"[{self.extra['document_id']}] {msg}", kwargs


def document_logger(name: str, document_id: str) -> DocumentLoggerAdapter:
    return DocumentLoggerAdapter(
        get_logger(name), {"document_id": sanitize_for_log(document_id)}
    )

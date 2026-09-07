"""Standard logging with redaction applied after messages and exceptions are formatted."""

import copy
import json
import logging
import re
import time
from collections.abc import Iterable
from typing import TextIO

_QUOTED_VALUE = r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')"""
_SECRET_FIELD = re.compile(
    r"(?i)([\"']?\b(?:[a-z0-9_]*api_?key|[a-z0-9_]*api_?secret|"
    r"[a-z0-9_]*token|[a-z0-9_]*password|secret)[\"']?\s*[:=]\s*)"
    r"(?:" + _QUOTED_VALUE + r"|\[REDACTED\]|[^\s,;}\]]+)"
)
_AUTHORIZATION = re.compile(
    r"(?im)([\"']?\bauthorization[\"']?\s*[:=]\s*)(?:" + _QUOTED_VALUE + r"|[^\r\n]+)"
)


class Redactor:
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        values = set()
        for secret in secrets:
            if secret:
                values.update((secret, json.dumps(secret)[1:-1], repr(secret)[1:-1]))
        self.values = sorted(values, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for value in self.values:
            text = text.replace(value, "[REDACTED]")
        text = _AUTHORIZATION.sub(r"\1[REDACTED]", text)
        return _SECRET_FIELD.sub(r"\1[REDACTED]", text)


class RedactingFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self, redactor: Redactor, run_id: str) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s run=%(run_id)s job=%(job_id)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        self.redactor = redactor
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.run_id = getattr(record, "run_id", self.run_id)
        safe_record.job_id = getattr(record, "job_id", "-")
        return self.redactor(super().format(safe_record))


def configure_logging(redactor: Redactor, run_id: str, *, stream: TextIO | None = None) -> None:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(redactor, run_id))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)

"""Bounded GET-only transport for Alpaca market data. No trading endpoint is reachable."""

import http.client
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from buffetbot.config import AlpacaCredentials

HOST = "data.alpaca.markets"
PATHS = ("/v2/stocks/bars", "/v1/corporate-actions")
MAX_RESPONSE_BYTES = 4_000_000
logger = logging.getLogger("buffetbot.ingestion")


class IngestionError(ValueError):
    """Recoverable provider/cache failure with a safe, stable code and message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.capture_id = None
        self.quality = None


@dataclass(frozen=True)
class Response:
    body: bytes
    received_at: datetime
    request_id: str | None = None


class AlpacaHTTP:
    origin = "historical"

    def __init__(
        self,
        credentials: AlpacaCredentials,
        *,
        connection_factory=http.client.HTTPSConnection,
        sleep=time.sleep,
        monotonic=time.monotonic,
        now=lambda: datetime.now(UTC),
    ):
        if credentials.missing_fields():
            raise IngestionError(
                "credentials_missing",
                "Configure Alpaca API key/secret in the documented environment variables or an "
                "explicit --secrets file. Real market-data verification is blocked.",
            )
        self._credentials = credentials
        self._connection_factory = connection_factory
        self._sleep, self._monotonic, self._now = sleep, monotonic, now
        self._next_request = 0.0

    def get(self, path: str, params: dict) -> Response:
        if path not in PATHS:
            raise IngestionError(
                "unsupported_endpoint",
                "Only the two fixed market-data GET endpoints are supported.",
            )
        headers = {
            "APCA-API-KEY-ID": self._credentials.api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": self._credentials.api_secret.get_secret_value(),
            "Accept": "application/json",
            "User-Agent": "buffetbot/0.1.0 BB-005",
        }
        for attempt in range(3):
            wait = max(0, self._next_request - self._monotonic())
            if wait:
                self._sleep(wait)
            self._next_request = self._monotonic() + 0.35  # Below 200 requests/minute.
            connection = None
            status, response_headers = None, {}
            try:
                connection = self._connection_factory(HOST, timeout=20)
                connection.request("GET", path + "?" + urlencode(params), headers=headers)
                reply = connection.getresponse()
                status = reply.status
                response_headers = {k.lower(): v for k, v in reply.getheaders()}
                if status == 200:
                    body = reply.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise IngestionError(
                            "response_too_large", "Provider response exceeds the bounded page size."
                        )
                    if "content-length" in response_headers and len(body) != int(
                        response_headers["content-length"]
                    ):
                        raise http.client.IncompleteRead(body)
                    return Response(body, self._now(), response_headers.get("x-request-id"))
                # Never persist or log provider error bodies, exception strings, or auth headers.
            except IngestionError:
                raise
            except (OSError, http.client.HTTPException, ValueError):
                status = None
            finally:
                if connection is not None:
                    connection.close()
            if status in (401, 402, 403):
                raise IngestionError(
                    "access_denied",
                    "Alpaca rejected authentication or data entitlement. Check the selected feed "
                    "and corporate-actions access; no feed substitution was made.",
                )
            if status is not None and status != 429 and status not in (500, 502, 503, 504):
                raise IngestionError(
                    "request_rejected",
                    "Alpaca rejected the request; check parameters. Redirects are not followed.",
                )
            if attempt == 2:
                raise IngestionError(
                    "retries_exhausted",
                    "Market-data read failed after three attempts; retry the import later.",
                )
            delay = float(2**attempt)
            try:
                retry_after = response_headers.get("retry-after")
                if retry_after is not None:
                    try:
                        requested = float(retry_after)
                    except ValueError:
                        requested = (
                            parsedate_to_datetime(retry_after) - self._now()
                        ).total_seconds()
                    if not math.isfinite(requested):
                        raise ValueError("Invalid retry interval")
                    delay = max(delay, requested)
                reset = response_headers.get("x-ratelimit-reset")
                if status == 429 and reset is not None:
                    reset_wait = float(reset) - self._now().timestamp()
                    if not math.isfinite(reset_wait):
                        raise ValueError("Invalid rate reset")
                    delay = max(delay, reset_wait)
            except (ValueError, TypeError, OverflowError):
                raise IngestionError(
                    "invalid_retry_hint",
                    "Provider retry timing is invalid; retry the import later.",
                ) from None
            if not 0 <= delay <= 30:
                raise IngestionError(
                    "rate_limited",
                    "Provider requires a wait beyond the 30-second retry budget; retry later.",
                )
            logger.warning(
                "Transient market-data read failure; retry %s/3 in %.2f seconds", attempt + 2, delay
            )
            self._sleep(delay)
        raise AssertionError("Retry loop must return or raise")

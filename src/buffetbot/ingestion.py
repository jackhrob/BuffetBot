"""Historical import orchestration: immutable response captures and a replaceable cache index."""

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from buffetbot.alpaca_history import collect_pages, normalise_capture, provenance_text
from buffetbot.config import AlpacaCredentials
from buffetbot.experiments import canonical_json
from buffetbot.ingestion_models import (
    ADAPTER_VERSION,
    HistoricalRequest,
    ImportReceipt,
    SourceCapture,
)
from buffetbot.market_http import AlpacaHTTP, IngestionError
from buffetbot.snapshots import SnapshotError, SnapshotQualityError, publish_snapshot, read_snapshot


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cache_key(request, origin):
    return digest(f"{ADAPTER_VERSION}:{origin}:{canonical_json(request)}".encode())


def member(data_root, directory, identifier):
    if not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{64}", identifier) is None:
        raise IngestionError(
            "invalid_identity", "Capture/cache identity must be a lowercase SHA-256 digest."
        )
    parent = Path(data_root) / directory
    path = parent / f"{identifier}.json"
    if parent.is_symlink() or path.is_symlink():
        raise IngestionError("unsafe_cache", "Capture and cache paths must not be symlinks.")
    return path


def atomic_write(path, data, *, immutable):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix=".staging-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if immutable:
            try:
                os.link(filename, path)  # Publish without replacing an existing content identity.
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != data:
                    raise IngestionError(
                        "capture_corrupt",
                        "An existing capture is corrupt; restore its original bytes.",
                    ) from None
        else:
            os.replace(filename, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(filename).unlink(missing_ok=True)


def read_capture(data_root, capture_id):
    try:
        path = member(data_root, "market-captures", capture_id)
        data = path.read_bytes()
        if digest(data) != capture_id:
            raise IngestionError(
                "capture_corrupt",
                "Original response capture checksum mismatch; restore the original file.",
            )
        capture = SourceCapture.model_validate_json(data)
        if canonical_json(capture).encode() != data:
            raise IngestionError(
                "capture_corrupt", "Original response capture is not canonically encoded."
            )
        return capture
    except IngestionError:
        raise
    except (OSError, ValueError):
        raise IngestionError(
            "capture_unreadable",
            "Original response capture is missing, inaccessible or unsupported.",
        ) from None


def publish_capture(data_root, capture_id):
    """Replay raw responses locally. A rejected capture remains evidence, never a usable dataset."""
    capture = read_capture(data_root, capture_id)
    try:
        snapshot = publish_snapshot(data_root, *normalise_capture(capture, capture_id))
        return snapshot
    except SnapshotQualityError as error:
        failure = IngestionError(
            "quality_rejected", "Downloaded records failed snapshot quality checks."
        )
        failure.quality = error.report
    except IngestionError as error:
        error.capture_id = capture_id
        raise
    except (ValidationError, SnapshotError, ValueError, OverflowError) as error:
        failure = IngestionError(
            "unsupported_records",
            "Downloaded bar/action records have unsupported fields, dates, units or storage. "
            "Inspect the retained capture and source requirements.",
        )
        failure.__cause__ = error
    failure.capture_id = capture_id
    raise failure


def receipt(request, snapshot, capture_id):
    return dict(
        schema_version=1,
        adapter_version=ADAPTER_VERSION,
        origin=snapshot.manifest.plan.origin,
        request_id=cache_key(request, snapshot.manifest.plan.origin),
        dataset_id=snapshot.dataset_id,
        capture_id=capture_id,
    )


def ingest_history(
    data_root,
    request,
    credentials=None,
    *,
    refresh=False,
    cache_only=False,
    transport=None,
    now=lambda: datetime.now(UTC),
):
    """Reuse verified cache without a connection; refresh reads a new complete version."""
    request = HistoricalRequest.model_validate(request)
    if refresh and cache_only:
        raise IngestionError("invalid_cache_mode", "Refresh and cache-only are mutually exclusive.")
    origin = "historical" if transport is None else transport.origin
    request_id = cache_key(request, origin)
    try:
        index = member(data_root, "market-imports", request_id)
        if index.exists() and not refresh:
            saved = ImportReceipt.model_validate_json(index.read_bytes()).model_dump(mode="json")
            capture = read_capture(data_root, saved["capture_id"])
            snapshot = read_snapshot(data_root, saved["dataset_id"])
            expected = receipt(request, snapshot, saved["capture_id"])
            if (
                saved != expected
                or capture.request != request
                or capture.origin != origin
                or snapshot.manifest.plan.origin != origin
                or snapshot.manifest.plan.retrieval_convention
                != provenance_text(saved["capture_id"])
            ):
                raise IngestionError(
                    "cache_mismatch",
                    "Cache receipt, request, snapshot and response provenance do not agree.",
                )
            return dict(expected, cache_hit=True)
        if cache_only:
            raise IngestionError(
                "cache_miss",
                "No cached import matches this request; no network request was made.",
            )
        if transport is None:
            transport = AlpacaHTTP(credentials or AlpacaCredentials())
        requested_at = now()
        pages = collect_pages(transport, request, requested_at)
        capture = SourceCapture(
            schema_version=1,
            origin=origin,
            request=request,
            requested_at=requested_at,
            captured_at=now(),
            pages=pages,
        )
        data = canonical_json(capture).encode()
        capture_id = digest(data)
        atomic_write(member(data_root, "market-captures", capture_id), data, immutable=True)
        snapshot = publish_capture(data_root, capture_id)
        completed = receipt(request, snapshot, capture_id)
        atomic_write(
            index,
            json.dumps(completed, sort_keys=True, separators=(",", ":")).encode(),
            immutable=False,
        )
        return dict(completed, cache_hit=False)
    except IngestionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, SnapshotError):
        raise IngestionError(
            "import_failed",
            "Import/cache is invalid or inaccessible; no successful receipt was published. "
            "Check the request and local files.",
        ) from None

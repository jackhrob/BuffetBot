"""Dataset command boundary, with explicit GET-only historical imports."""

from pydantic import ValidationError

from buffetbot.config import ConfigurationError, load_settings, resolve_paths
from buffetbot.fixtures import load_fixture
from buffetbot.ingestion import ingest_history, publish_capture, read_capture
from buffetbot.ingestion_models import HistoricalRequest
from buffetbot.market_http import IngestionError
from buffetbot.snapshots import (
    SnapshotError,
    SnapshotQualityError,
    inspect_snapshot,
    publish_snapshot,
)


def run(arguments, *, credentials=None) -> tuple[dict, int]:
    origin = "unverified"
    try:
        paths = resolve_paths(load_settings(arguments.config), arguments.config)
        if arguments.dataset_command == "fixture":
            origin = "synthetic"
            plan, bars, actions = load_fixture(arguments.case)
            snapshot = publish_snapshot(paths["data"], plan, bars, actions)
            dataset_id = snapshot.dataset_id
        elif arguments.dataset_command == "ingest":
            request = HistoricalRequest.model_validate_json(arguments.request.read_bytes())
            origin = "historical"
            receipt = ingest_history(
                paths["data"],
                request,
                credentials,
                refresh=arguments.refresh,
                cache_only=arguments.cache_only,
            )
            report = inspect_snapshot(paths["data"], receipt["dataset_id"])
            return dict(report, ingestion=receipt), 0
        elif arguments.dataset_command == "replay":
            capture = read_capture(paths["data"], arguments.capture_id)
            origin = capture.origin
            snapshot = publish_capture(paths["data"], arguments.capture_id)
            report = inspect_snapshot(paths["data"], snapshot.dataset_id)
            return dict(report, capture_id=arguments.capture_id, replayed=True), 0
        else:
            dataset_id = arguments.dataset_id
        return inspect_snapshot(paths["data"], dataset_id), 0
    except SnapshotQualityError as error:
        return {
            "status": "rejected",
            "origin": error.report.origin,
            "error": str(error),
            "quality": error.report.model_dump(mode="json"),
        }, 1
    except (ConfigurationError, SnapshotError) as error:
        return {"status": "invalid", "origin": origin, "error": str(error)}, 2
    except IngestionError as error:
        blocked = error.code in {
            "credentials_missing",
            "access_denied",
            "rate_limited",
            "cache_miss",
        }
        report = dict(
            status="blocked" if blocked else "rejected",
            origin=origin,
            code=error.code,
            error=str(error),
            capture_id=error.capture_id,
        )
        if error.quality is not None:
            report["quality"] = error.quality.model_dump(mode="json")
        return report, 1
    except (OSError, ValidationError):
        return dict(
            status="invalid",
            origin=origin,
            error="Cannot read request JSON or its fields are invalid; check the request schema.",
        ), 2

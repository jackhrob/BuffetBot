"""Offline dataset command boundary; no secrets, provider clients, or order writes."""

from buffetbot.config import ConfigurationError, load_settings, resolve_paths
from buffetbot.fixtures import load_fixture
from buffetbot.snapshots import (
    SnapshotError,
    SnapshotQualityError,
    inspect_snapshot,
    publish_snapshot,
)


def run(arguments) -> tuple[dict, int]:
    origin = "unverified"
    try:
        paths = resolve_paths(load_settings(arguments.config), arguments.config)
        if arguments.dataset_command == "fixture":
            origin = "synthetic"
            plan, bars, actions = load_fixture(arguments.case)
            snapshot = publish_snapshot(paths["data"], plan, bars, actions)
            dataset_id = snapshot.dataset_id
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

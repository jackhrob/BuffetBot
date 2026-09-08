"""Run the complete synthetic import/cache/refresh/replay path without network access."""

import json
import socket
import tempfile
from pathlib import Path


class NoNetworkSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise AssertionError("Network is disabled for the synthetic ingestion example")


socket.socket = NoNetworkSocket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No network"))
socket.getaddrinfo = socket.create_connection

from buffetbot.fixtures.alpaca import (  # noqa: E402
    CAPTURE_TIME,
    SyntheticAlpaca,
    history_request,
)
from buffetbot.ingestion import ingest_history, publish_capture, read_capture  # noqa: E402
from buffetbot.snapshots import inspect_snapshot  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="buffetbot-ingestion-demo-") as name:
        root, source, request = Path(name), SyntheticAlpaca(), history_request()
        first = ingest_history(root, request, transport=source, now=lambda: CAPTURE_TIME)
        capture = read_capture(root, first["capture_id"])
        report = inspect_snapshot(root, first["dataset_id"])
        assert len(capture.pages) == 6
        assert [r["bars"] for r in report["coverage"]] == [2, 2]
        calls = len(source.calls)
        cached = ingest_history(root, request, transport=source, cache_only=True)
        assert cached["cache_hit"] and len(source.calls) == calls
        source.bars["2024-07-02"]["BBTEST"][0]["h"] = 111
        revised = ingest_history(
            root, request, transport=source, refresh=True, now=lambda: CAPTURE_TIME
        )
        assert revised["dataset_id"] != first["dataset_id"]
        assert publish_capture(root, first["capture_id"]).dataset_id == first["dataset_id"]
        return dict(
            origin="synthetic",
            status="passed",
            initial=first,
            refreshed=revised,
            cached_without_network=True,
            replay_matches_original=True,
            report=report,
            captured_pages=len(capture.pages),
            temporary_files_removed=True,
        )


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))

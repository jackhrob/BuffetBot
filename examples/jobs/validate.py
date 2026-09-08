"""Run a durable job in an isolated local directory without network or broker/model imports."""

import json
import socket
import tempfile
from pathlib import Path


class NoNetworkSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise AssertionError("Network is disabled for the jobs example")


socket.socket = NoNetworkSocket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No network"))
socket.getaddrinfo = socket.create_connection

from buffetbot.jobs import JobStore  # noqa: E402
from buffetbot.jobs_models import JobRequest  # noqa: E402
from buffetbot.worker import Worker  # noqa: E402


def main():
    request = JobRequest.model_validate_json(
        Path(__file__).with_name("research-probe.json").read_bytes()
    )
    with tempfile.TemporaryDirectory(prefix="buffetbot-jobs-demo-") as directory:
        root = Path(directory)
        store = JobStore(root / "state")
        first = store.submit(request)
        duplicate = store.submit(request)
        assert first == duplicate and len(store.list()) == 1
        result = Worker(root / "state", root / "artifacts").run_once()
        final = store.get(request.request_id)
        artifact = root / "artifacts" / final.artifact.relative_path
        contents = json.loads(artifact.read_text())
        assert final.state == "succeeded" and contents["message"] == request.payload.message
        assert "BUFFETBOT_ALPACA_API_KEY" not in contents["environment_keys"]
        assert not any(
            name in __import__("sys").modules for name in ("lumibot", "alpaca", "sklearn")
        )
        return {
            "origin": "synthetic",
            "status": result["status"],
            "request_id": str(request.request_id),
            "artifact": final.artifact.model_dump(mode="json"),
            "events": store.events(request.request_id),
            "temporary_files_removed": True,
        }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))

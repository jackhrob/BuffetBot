"""CLI boundary for durable local jobs and worker lifecycle; no broker credentials are loaded."""

from pydantic import ValidationError

from buffetbot.config import ConfigurationError, load_settings, resolve_paths
from buffetbot.jobs import JobStore, JobStoreBusy, JobStoreError, UnknownJob
from buffetbot.jobs_models import JobRequest
from buffetbot.worker import Worker, WorkerAlreadyRunning, WorkerError


def _paths(config):
    settings = load_settings(config)
    return resolve_paths(settings, config)


def run(arguments):
    try:
        paths = _paths(arguments.config)
        store = JobStore(paths["state"])
        if arguments.command == "jobs":
            if arguments.jobs_command == "submit":
                request = JobRequest.model_validate_json(arguments.request.read_bytes())
                record = store.submit(request)
                return {
                    "status": "accepted",
                    "job": record.model_dump(mode="json"),
                    "events": store.events(request.request_id),
                }, 0
            if arguments.jobs_command == "show":
                record = store.get(arguments.request_id)
                return {
                    "status": "ok",
                    "job": record.model_dump(mode="json"),
                    "events": store.events(arguments.request_id),
                }, 0
            if arguments.jobs_command == "list":
                return {
                    "status": "ok",
                    "jobs": [
                        job.model_dump(mode="json") for job in store.list(limit=arguments.limit)
                    ],
                }, 0
            record = store.cancel(arguments.request_id)
            return {
                "status": "ok",
                "job": record.model_dump(mode="json"),
                "events": store.events(arguments.request_id),
            }, 0
        worker = Worker(paths["state"], paths["artifacts"])
        if arguments.worker_command == "status":
            return {"status": "ok", "worker": worker.status()}, 0
        if arguments.worker_command == "shutdown":
            worker.store.initialize()
            worker.store.request_shutdown(True)
            return {"status": "shutdown_requested", "worker": worker.status()}, 0
        if arguments.worker_command == "resume":
            worker.store.initialize()
            worker.store.request_shutdown(False)
            return {"status": "ready", "worker": worker.status()}, 0
        if arguments.worker_command == "once":
            return worker.run_once(), 0
        return worker.serve(poll_seconds=arguments.poll_seconds), 0
    except (ConfigurationError, ValidationError):
        return {"status": "invalid", "error": "Invalid job request or local configuration."}, 2
    except UnknownJob:
        return {"status": "not_found", "error": "Job request ID was not found."}, 2
    except JobStoreBusy:
        return {
            "status": "busy",
            "error": "Job state is busy after three short retries; try again.",
        }, 1
    except WorkerAlreadyRunning:
        return {"status": "busy", "error": "Another worker owns this state directory."}, 1
    except (JobStoreError, WorkerError, OSError):
        return {
            "status": "invalid",
            "error": "Cannot use local job state or artifacts; check storage and recovery.",
        }, 2

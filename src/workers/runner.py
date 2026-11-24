"""Run DA3 and 3DGS jobs against the workbench API from a separate process."""

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .registration import ExecutionError
from .splat_executor import execute, execute_points

log = logging.getLogger(__name__)


def post(base_url, path, payload):
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("SPATIAL_WORKER_TOKEN")
    if token:
        headers["X-Worker-Token"] = token
    request = Request(base_url + "/api/internal/" + path, json.dumps(payload).encode(), headers)
    with urlopen(request, timeout=15) as response:
        return json.load(response) if response.status != 204 else None


def renew(url, path, lease, seconds, done, lost):
    deadline = monotonic() + seconds
    interval = seconds / 3
    while not done.wait(interval):
        if monotonic() >= deadline:
            break
        started = monotonic()
        try:
            post(url, path + "/heartbeat", lease)
        except OSError as error:
            if isinstance(error, HTTPError) and error.code in {401, 404, 409}:
                break
            interval = 1
        else:
            deadline = started + seconds
            interval = seconds / 3
    if not done.is_set():
        lost.set()


def run_job(args, job, stopping):
    path = "jobs/" + job["job_id"]
    lease = {"lease_token": job["lease_token"]}
    done = Event()
    lost = Event()
    pulse = Thread(target=renew, args=(args.api_url, path, lease, job["lease_seconds"], done, lost))
    pulse.start()

    def cancelled():
        return stopping.is_set() or lost.is_set()

    try:
        try:
            if job["kind"] == "splat":
                finished = execute(job, args.data_dir, args.python, args.brush, args.splat_transform, cancelled)
            else:
                finished = execute_points(job, args.data_dir, args.da3_python, args.da3_model, cancelled)
        except (ExecutionError, OSError) as error:
            log.error("%s job %s failed: %s", job["kind"], job["job_id"], error)
            if not cancelled():
                code = error.code if isinstance(error, ExecutionError) else "EXECUTOR_ERROR"
                post(args.api_url, path + "/fail", {**lease, "error_code": code})
        else:
            if finished and not cancelled():
                result = post(args.api_url, path + "/complete", lease)
                log.info("%s job %s: %s", job["kind"], job["job_id"], result["status"])
    finally:
        done.set()
        pulse.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--data-dir", type=Path, default=os.environ.get("SPATIAL_DATA_DIR", "data/runtime"))
    parser.add_argument("--python", "--gs-python", default=os.environ.get("ORBIT_GS_PY", sys.executable))
    parser.add_argument("--brush", default=os.environ.get("ORBIT_BRUSH"))
    parser.add_argument("--splat-transform", default=os.environ.get("ORBIT_SOG_CLI"))
    parser.add_argument("--da3-python", default=os.environ.get("ORBIT_DA3_PY", sys.executable))
    parser.add_argument("--da3-model", default=os.environ.get("ORBIT_DA3_MODEL"))
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit")
    args = parser.parse_args()
    args.api_url = args.api_url.rstrip("/")
    args.data_dir = args.data_dir.resolve()
    kinds = []
    if args.da3_model:
        kinds.extend(["depth", "fusion"])
    if args.brush:
        kinds.append("splat")
    if not kinds:
        parser.error("Set ORBIT_DA3_MODEL and/or ORBIT_BRUSH")
    logging.basicConfig(level=logging.INFO)
    stopping = Event()

    def stop(_number, _frame):
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping.is_set():
        try:
            job = post(args.api_url, "workers/claim", {"kinds": kinds})
            if job:
                run_job(args, job, stopping)
        except (OSError, ValueError) as error:
            log.error("Worker request failed: %s", error)
            if args.once or isinstance(error, HTTPError) and error.code == 401:
                return 1
        if args.once:
            return 0
        stopping.wait(1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

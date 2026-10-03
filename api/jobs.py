"""Background jobs with a server-sent-events log.

Agent work (LLM calls, TuringDB branch builds) runs on a worker thread per job. HTTP handlers only start a
job or read its event log, so no request ever waits on a model or a write. A client streams
`GET .../events` (SSE); each event carries an `id`, so a reconnecting EventSource resumes after the last
event it saw (Last-Event-ID) instead of receiving duplicates. Every job ends with a `done` event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable

from api.support import ApiError, NotFound

log = logging.getLogger("opsmap.jobs")

POLL_S = 0.2
HEARTBEAT_S = 15.0
MAX_JOBS = 64  # finished jobs beyond this are forgotten, oldest first
MAX_RUNNING = 4


class TooManyJobs(ApiError):
    status_code = 429


@dataclass(frozen=True)
class JobEvent:
    id: int
    type: str
    data: dict


class Job:
    def __init__(self, kind: str, job_id: str | None = None, handle: Any = None) -> None:
        self.id = job_id or uuid.uuid4().hex[:8]
        self.kind = kind
        self.handle = handle  # the controllable object (a Match), if any
        self.status = "running"
        self.result: Any = None
        self.started = time.time()
        self._events: list[JobEvent] = []
        self._lock = threading.Lock()
        self._finished = threading.Event()

    @property
    def finished(self) -> bool:
        return self._finished.is_set()

    def emit(self, kind: str, data: dict | None = None) -> None:
        with self._lock:
            self._events.append(JobEvent(len(self._events), kind, dict(data or {})))

    def since(self, first: int) -> list[JobEvent]:
        with self._lock:
            return self._events[max(0, first):]

    def finish(self, status: str) -> None:
        self.status = status
        self.emit("done", {"status": status, "job_id": self.id, "kind": self.kind})
        self._finished.set()

    def snapshot(self) -> dict:
        with self._lock:
            count = len(self._events)
        return {"id": self.id, "kind": self.kind, "status": self.status, "events": count, "result": self.result}


Work = Callable[[Job], Any]


class JobRegistry:
    def __init__(self, max_jobs: int = MAX_JOBS, max_running: int = MAX_RUNNING) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.max_jobs, self.max_running = max_jobs, max_running

    def start(self, kind: str, work: Work, handle: Any = None, job_id: str | None = None) -> Job:
        job = Job(kind, job_id, handle)
        with self._lock:
            running = sum(not j.finished for j in self._jobs.values())
            if running >= self.max_running:
                raise TooManyJobs(f"{running} agent jobs are already running; wait for one to finish")
            self._jobs[job.id] = job
            self._evict()
        threading.Thread(target=self._run, args=(job, work), daemon=True, name=f"job-{kind}-{job.id}").start()
        return job

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFound(f"no job {job_id!r}")
        return job

    def _evict(self) -> None:
        done = sorted((j for j in self._jobs.values() if j.finished), key=lambda j: j.started)
        for old in done[:max(0, len(self._jobs) - self.max_jobs)]:
            self._jobs.pop(old.id, None)

    @staticmethod
    def _run(job: Job, work: Work) -> None:
        job.emit("job_started", {"job_id": job.id, "kind": job.kind})
        try:
            job.result = work(job)
            status = job.result.get("status", "done") if isinstance(job.result, dict) else "done"
            job.finish(status if status in ("done", "stopped", "error") else "done")
        except Exception as exc:  # surfaced to the client; the server keeps serving
            log.exception("job %s (%s) failed", job.id, job.kind)
            job.emit("error", {"message": f"{type(exc).__name__}: {exc}"})
            job.finish("error")


def _frame(event: JobEvent) -> str:
    body = json.dumps({"type": event.type, **event.data}, default=str)
    return f"id: {event.id}\nevent: {event.type}\ndata: {body}\n\n"


async def sse_stream(job: Job, last_event_id: str | None = None) -> AsyncIterator[str]:
    """Replay the job's events after `last_event_id`, then follow it live until it finishes."""
    try:
        cursor = int(last_event_id) + 1 if last_event_id else 0
    except ValueError:
        cursor = 0
    quiet = 0.0
    yield "retry: 2000\n\n"
    while True:
        events = job.since(cursor)
        for event in events:
            yield _frame(event)
        cursor += len(events)
        if job.finished and not job.since(cursor):
            return
        if events:
            quiet = 0.0
        else:
            quiet += POLL_S
            if quiet >= HEARTBEAT_S:  # keeps proxies from closing an idle stream
                quiet = 0.0
                yield ": heartbeat\n\n"
        await asyncio.sleep(POLL_S)

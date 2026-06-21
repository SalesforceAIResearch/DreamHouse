"""FastAPI app implementing the DreamHouse evaluation API locally.

Endpoints mirror the documented public API:

    GET  /v1/tasks/{task_id}
    GET  /v1/tasks/{task_id}/images/{view}
    POST /v1/sessions
    POST /v1/sessions/{session_id}/submit
    GET  /v1/sessions/{session_id}/results/{job_id}

Run:
    uvicorn server.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import tasks as tasks_mod
from .validator_runner import ValidatorError, run_validation


SESSION_TTL_HOURS = 48

app = FastAPI(title="DreamHouse Local Eval", version="0.1.0")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    task_id: str
    model_id: str = "local"
    protocol: Literal["stepwise", "oneshot"] = "stepwise"


class SubmitRequest(BaseModel):
    members: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# In-memory stores (local-only server; persistence is out of scope)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}
_jobs: dict[str, dict] = {}
_session_round: dict[str, int] = {}
_store_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = tasks_mod.load_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
    return {
        "id": task.id,
        "style": task.style,
        "description": task.description,
        "constraints": task.constraints,
        "reference_images": [
            f"/v1/tasks/{task.id}/images/{view}" for view in task.image_views
        ],
    }


@app.get("/v1/tasks/{task_id}/images/{view}")
def get_task_image(task_id: str, view: str):
    task = tasks_mod.load_task(task_id)
    if task is None or view not in task.image_views:
        raise HTTPException(status_code=404, detail="Image not found")
    content = tasks_mod.load_image(task_id, view)
    if content is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(content=content, media_type="image/png")


@app.get("/v1/tasks")
def list_tasks() -> dict:
    return {"task_ids": tasks_mod.list_task_ids()}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@app.post("/v1/sessions")
def create_session(req: CreateSessionRequest) -> dict:
    if tasks_mod.load_task(req.task_id) is None:
        raise HTTPException(status_code=404, detail=f"Task {req.task_id!r} not found")

    session_id = str(uuid.uuid4())
    created = _now()
    expires = created + timedelta(hours=SESSION_TTL_HOURS)
    session = {
        "session_id": session_id,
        "task_id": req.task_id,
        "model_id": req.model_id,
        "protocol": req.protocol,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
    }
    with _store_lock:
        _sessions[session_id] = session
        _session_round[session_id] = 0
    return session


def _get_session_or_404(session_id: str) -> dict:
    with _store_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    if datetime.fromisoformat(session["expires_at"]) < _now():
        raise HTTPException(status_code=410, detail="Session expired")
    return session


def _run_job(job_id: str, session_id: str, task_id: str, submission: dict) -> None:
    try:
        results = run_validation(submission, task_id)
        error: Optional[str] = results.get("error") if isinstance(results, dict) else None
        with _store_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            if error:
                job["status"] = "failed"
                job["error"] = error
                job["results"] = None
            else:
                job["status"] = "complete"
                job["error"] = None
                job["results"] = results
    except ValidatorError as exc:
        with _store_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "failed"
                job["error"] = str(exc)
                job["results"] = None
    except Exception as exc:  # noqa: BLE001
        with _store_lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "failed"
                job["error"] = f"internal error: {exc}"
                job["results"] = None


@app.post("/v1/sessions/{session_id}/submit")
def submit(session_id: str, req: SubmitRequest) -> dict:
    session = _get_session_or_404(session_id)
    if not req.members:
        raise HTTPException(status_code=400, detail="members cannot be empty")

    job_id = str(uuid.uuid4())
    with _store_lock:
        _session_round[session_id] = _session_round.get(session_id, 0) + 1
        round_num = _session_round[session_id]
        _jobs[job_id] = {
            "job_id": job_id,
            "session_id": session_id,
            "round": round_num,
            "status": "queued",
            "results": None,
            "error": None,
        }

    submission = {"members": req.members}
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, session_id, session["task_id"], submission),
        daemon=True,
    )
    thread.start()

    with _store_lock:
        _jobs[job_id]["status"] = "running"

    return {
        "job_id": job_id,
        "round": round_num,
        "status": "queued",
        "poll_url": f"/v1/sessions/{session_id}/results/{job_id}",
    }


@app.get("/v1/sessions/{session_id}/results/{job_id}")
def get_results(session_id: str, job_id: str) -> dict:
    with _store_lock:
        job = _jobs.get(job_id)
    if job is None or job.get("session_id") != session_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "session_id": session_id,
        "job_id": job_id,
        "round": job["round"],
        "status": job["status"],
        "results": job.get("results"),
        "error": job.get("error"),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "tasks": len(tasks_mod.list_task_ids())}

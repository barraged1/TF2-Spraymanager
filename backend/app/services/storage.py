"""Per-job working storage with safe IDs and TTL-based cleanup.

Each conversion session gets an opaque job id and an isolated directory under the
configured data folder. Job ids are validated against a strict pattern so they
can never be used for path traversal.
"""
from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

from ..config import settings

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class StorageError(Exception):
    pass


def new_job() -> str:
    """Create a new job directory and return its id."""
    settings.ensure_dirs()
    job_id = uuid.uuid4().hex
    (settings.uploads_dir / job_id).mkdir(parents=True, exist_ok=True)
    return job_id


def job_dir(job_id: str, *, create: bool = False) -> Path:
    """Return the validated directory for ``job_id``."""
    if not _JOB_ID_RE.match(job_id):
        raise StorageError("Invalid job id.")
    path = settings.uploads_dir / job_id
    if create:
        path.mkdir(parents=True, exist_ok=True)
    elif not path.is_dir():
        raise StorageError("Unknown job id.")
    return path


def job_path(job_id: str, filename: str, *, create: bool = False) -> Path:
    """Resolve a filename *inside* a job directory, rejecting traversal."""
    base = job_dir(job_id, create=create)
    # Strip any directory components from the supplied name.
    safe = Path(filename).name
    target = (base / safe).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise StorageError("Resolved path escapes the job directory.")
    return target


def cleanup_expired(now: float | None = None) -> int:
    """Delete job directories older than the configured TTL. Returns count."""
    now = now or time.time()
    if not settings.uploads_dir.exists():
        return 0
    removed = 0
    for child in settings.uploads_dir.iterdir():
        if not child.is_dir() or not _JOB_ID_RE.match(child.name):
            continue
        age = now - child.stat().st_mtime
        if age > settings.job_ttl_s:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed

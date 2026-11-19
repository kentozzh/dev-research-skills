"""Atomic canonical run state with immutable history and diagnostic projections.

Only run.json is read by load_run. Individual JSON projections may straddle an
interrupted save and must never be used to reconstruct an authoritative state.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from .contracts import RequestContract, RunState
from .evidence import canonical_json, content_hash
from .identity import snapshot_id
from .validation import ARCHITECTURE_CONDITION, ContractError, validate_request


def _stored_request(request: RequestContract, revision: int) -> RequestContract:
    parsed = validate_request(request.to_dict())
    if parsed.skill in {"skill-finding", "tool-finding"}:
        if parsed.preferences.get("tool_intent") == "architecture_reference":
            key, mandatory = "architecture_design", ARCHITECTURE_CONDITION
        else:
            key, mandatory = "license", "License explicitly covers the intended reuse"
        if mandatory not in parsed.hard_constraints.values():
            while key in parsed.hard_constraints:
                key = "required_" + key
            parsed.hard_constraints[key] = mandatory
    parsed.contract_revision = revision
    return RequestContract.from_dict(parsed.to_dict())


def prepare_run(request: RequestContract, run_dir: Path) -> RunState:
    request = _stored_request(request, 1)
    run_dir = Path(run_dir)
    if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
        raise ContractError("run_dir", "destination already exists and is not empty")
    run_dir.mkdir(parents=True, exist_ok=True)
    state = RunState("run:" + uuid.uuid4().hex, request, "unassigned")
    state.snapshot_id = snapshot_id(state)
    save_run(state, run_dir)
    return state


def revise_run(state: RunState, request: RequestContract) -> RunState:
    revised = RunState.from_dict(state.to_dict())
    revised.request = _stored_request(request, state.request.contract_revision + 1)
    revised.snapshot_id = snapshot_id(revised)
    revised.assessments = {}
    revised.invalidated = True
    revised.invalidation_reason = "Request revision changed; submit assessments for the new snapshot"
    return revised


def _atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_run(run_dir: Path) -> RunState:
    try:
        data = json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ContractError("run_dir", "cannot read valid canonical run JSON") from None
    state = RunState.from_dict(data)
    if state.snapshot_id != snapshot_id(state):
        raise ContractError("RunState.snapshot_id", "snapshot hash does not match request and facts")
    digest = content_hash(state.to_dict())
    archive = Path(run_dir) / "history" / (digest + ".json")
    if not archive.exists():
        # Older runs nested the full-state hash under a redundant fact hash.
        archive = Path(run_dir) / "history" / state.snapshot_id.split(":", 1)[1] / (digest + ".json")
    try:
        history = json.loads(archive.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ContractError("run_dir.history", "canonical state has no matching immutable history") from None
    if canonical_json(history) != canonical_json(state.to_dict()):
        raise ContractError("run_dir.history", "canonical state differs from immutable history")
    return state


def save_run(state: RunState, run_dir: Path) -> None:
    state = RunState.from_dict(state.to_dict())
    if state.snapshot_id != snapshot_id(state):
        raise ContractError("RunState.snapshot_id", "snapshot hash does not match request and facts")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = run_dir / ".save.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ContractError("run_dir", "run is already being saved") from None
    try:
        os.close(fd)
        if (run_dir / "run.json").exists():
            previous = load_run(run_dir)
            if previous.run_id != state.run_id:
                raise ContractError("RunState.run_id", "cannot overwrite a different run")
            if previous.request.contract_revision > state.request.contract_revision:
                raise ContractError("RunState.request.contract_revision", "cannot overwrite a newer request revision")
        value = state.to_dict()
        digest = content_hash(value)
        # The full-state digest already binds its fact snapshot; one hash path
        # avoids exceeding native Windows MAX_PATH for otherwise normal runs.
        archive = run_dir / "history" / (digest + ".json")
        if archive.exists():
            if archive.read_text(encoding="utf-8") != canonical_json(value) + "\n":
                raise ContractError("run_dir.history", "immutable history content does not match")
        else:
            _atomic_json(archive, value)
        projections = {"request": value["request"], "candidates": value["candidates"],
            "evidence": value["evidence"], "assessments": value["assessments"],
            "manifest": {"run_id": state.run_id, "snapshot_id": state.snapshot_id,
                "contract_revision": state.request.contract_revision, "state_hash": digest,
                "history": archive.relative_to(run_dir).as_posix(), "invalidated": state.invalidated,
                "canonical": "run.json", "projections_are_diagnostic": True}}
        for name, projection in projections.items():
            _atomic_json(run_dir / (name + ".json"), projection)
        # The sole commit point: old run.json survives every earlier interruption.
        _atomic_json(run_dir / "run.json", value)
    finally:
        lock.unlink(missing_ok=True)

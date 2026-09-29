from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from platformdirs import user_state_path

from jolly.core.errors import ConfigurationError


def state_dir() -> Path:
    override = os.environ.get("JOLLY_STATE_DIR")
    return Path(override).expanduser() if override else user_state_path("jolly", "TeamAudiyo")


def state_file() -> Path:
    return state_dir() / "state.json"


@contextmanager
def state_lock() -> Iterator[None]:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".lock"
    handle = lock_path.open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


def load_state() -> dict[str, object] | None:
    path = state_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"State file is unreadable: {path}. Run 'jolly reset' to replace it.") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"State file has an invalid root value: {path}. Run 'jolly reset' to replace it.")
    return data


def save_state(state: dict[str, object]) -> None:
    # Explicit reset/scene/challenge replacement invalidates the prior session.
    # Retain its audit snapshot instead of leaving a stale trial scoreable.
    try:
        previous = load_state() or {}
    except ConfigurationError:
        previous = {}
    old = previous.get("benchmark_session")
    new = state.get("benchmark_session")
    if "benchmark_invalidations" in previous and "benchmark_invalidations" not in state:
        state["benchmark_invalidations"] = previous["benchmark_invalidations"]
    if old and (not new or old.get("seed") != new.get("seed") or old.get("started_at") != new.get("started_at")):
        from copy import deepcopy
        from datetime import datetime, timezone
        invalidations = list(previous.get("benchmark_invalidations", []))
        invalidations.append({"invalidated_at": datetime.now(timezone.utc).isoformat(),
                              "session": deepcopy(old), "controls": previous.get("benchmark_controls", [])})
        state["benchmark_invalidations"] = invalidations[-20:]
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)

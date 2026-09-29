from __future__ import annotations

from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from jolly import __version__
from jolly.core.errors import JollyError
from jolly.core.models import list_models
from jolly.core.physics import PhysicsEngine
from jolly.core.scenes import list_scenes
from jolly.core.store import load_state, save_state, state_lock


class MoveRequest(BaseModel):
    joints: list[float]
    gripper: float | None = Field(default=None, ge=0.0, le=1.0)
    steps: int = Field(default=120, ge=1, le=2400)
    allow_collision: bool = False


class ReachRequest(BaseModel):
    x: float
    y: float
    z: float
    gripper: float | None = Field(default=None, ge=0.0, le=1.0)
    steps: int = Field(default=160, ge=1, le=2400)
    allow_collision: bool = False


class ResetRequest(BaseModel):
    model: str = "jolly6"
    scene: str = "empty"


app = FastAPI(title="Jolly local simulator", version=__version__, docs_url="/api/docs")


def _run(
    operation: Any,
    *,
    model: str | None = None,
    scene: str | None = None,
    preserve_metadata: bool = True,
    count_challenge_command: bool = False,
) -> dict[str, object]:
    with state_lock():
        try:
            saved = load_state()
        except JollyError as exc:
            if preserve_metadata:
                raise HTTPException(
                    status_code=400, detail={"type": exc.__class__.__name__, "message": str(exc)}
                ) from exc
            saved = None  # reset replaces a corrupt state file
        selected_model = model or (str(saved["model"]["id"]) if saved else "jolly6")
        selected_scene = scene or (str(saved.get("scene", "empty")) if saved else "empty")
        try:
            with PhysicsEngine(selected_model, selected_scene) as engine:
                if saved and saved.get("model", {}).get("id") == selected_model and saved.get("scene") == selected_scene:
                    engine.restore(saved)
                state = operation(engine)
                if not isinstance(state, dict):
                    state = engine.state()
                if preserve_metadata and saved and "active_challenge" in saved:
                    state["active_challenge"] = saved["active_challenge"]
                    state["challenge_commands"] = int(saved.get("challenge_commands", 0)) + int(count_challenge_command)
                save_state(state)
                state["skeleton_points"] = engine.joint_positions()
                return state
        except JollyError as exc:
            raise HTTPException(status_code=400, detail={"type": exc.__class__.__name__, "message": str(exc)}) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return files("jolly.web").joinpath("index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config() -> dict[str, object]:
    return {"ok": True, "version": __version__, "models": list_models(), "scenes": list_scenes()}


@app.get("/api/state")
def state() -> dict[str, object]:
    return _run(lambda engine: engine.state())


@app.post("/api/move")
def move(request: MoveRequest) -> dict[str, object]:
    return _run(
        lambda engine: engine.move_joints(
            request.joints,
            gripper=request.gripper,
            steps=request.steps,
            allow_collision=request.allow_collision,
        ),
        count_challenge_command=True,
    )


@app.post("/api/reach")
def reach(request: ReachRequest) -> dict[str, object]:
    return _run(
        lambda engine: engine.reach(
            request.x,
            request.y,
            request.z,
            gripper=request.gripper,
            steps=request.steps,
            allow_collision=request.allow_collision,
        ),
        count_challenge_command=True,
    )


@app.post("/api/reset")
def reset(request: ResetRequest) -> dict[str, object]:
    return _run(
        lambda engine: engine.reset(),
        model=request.model,
        scene=request.scene,
        preserve_metadata=False,
    )

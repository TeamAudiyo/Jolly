from __future__ import annotations

import struct
import zlib
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from jolly import __version__
from jolly.benchmark import BENCHMARK_METADATA_KEYS, benchmark_control_history, ensure_control_allowed
from jolly.core.errors import ConfigurationError, JollyError, MotionError
from jolly.core.models import list_models
from jolly.engine import JollyEngine
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
    model: str = "so101"
    scene: str = "empty"


app = FastAPI(title="Jolly local simulator", version=__version__, docs_url="/api/docs")


def _run(
    operation: Any,
    *,
    model: str | None = None,
    scene: str | None = None,
    preserve_metadata: bool = True,
    count_challenge_command: bool = False,
    benchmark_control: tuple[str, dict[str, object]] | None = None,
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
        selected_model = model or (str(saved["model"]["id"]) if saved else "so101")
        selected_scene = scene or (str(saved.get("scene", "empty")) if saved else "empty")
        try:
            if saved and saved.get("backend") == "hardware" and preserve_metadata:
                raise HTTPException(status_code=400, detail={"type": "ConfigurationError", "message": "Hardware benchmark cannot use simulator API controls."})
            if count_challenge_command:
                ensure_control_allowed(saved or {})
            with JollyEngine(selected_model, selected_scene) as engine:
                if saved and saved.get("model", {}).get("id") == selected_model and saved.get("scene") == selected_scene:
                    engine.restore(saved)
                try:
                    state = operation(engine)
                except MotionError as exc:
                    if saved and saved.get("active_benchmark") and benchmark_control:
                        command, requested = benchmark_control
                        result = engine.state()
                        result["motion_collision"] = engine.motion_collision
                        result["control_error"] = str(exc)
                        saved["benchmark_controls"] = benchmark_control_history(
                            saved, source="web-api", command=command,
                            requested={**requested, "error": str(exc)}, result=result,
                        )
                        save_state(saved)
                    raise
                if not isinstance(state, dict):
                    state = engine.state()
                if preserve_metadata and saved and "active_challenge" in saved:
                    for key in BENCHMARK_METADATA_KEYS:
                        if key in saved:
                            state[key] = saved[key]
                    state["challenge_commands"] = int(saved.get("challenge_commands", 0)) + int(count_challenge_command)
                    if benchmark_control:
                        command, requested = benchmark_control
                        controls = benchmark_control_history(
                            saved,
                            source="web-api",
                            command=command,
                            requested=requested,
                            result=state,
                        )
                        if controls is not None:
                            state["benchmark_controls"] = controls
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


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def _encode_png(width: int, height: int, rgb: bytes) -> bytes:
    stride = width * 3
    scanlines = b"".join(b"\0" + rgb[row * stride : (row + 1) * stride] for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(
        b"IDAT", zlib.compress(scanlines, 6)
    ) + _png_chunk(b"IEND", b"")


@app.get("/api/render.png", response_class=Response)
def render_image(
    yaw: float = 42.0,
    pitch: float = -28.0,
    distance: float = 0.85,
    width: int = 960,
    height: int = 640,
) -> Response:
    yaw = max(-360.0, min(360.0, yaw))
    pitch = max(-89.0, min(20.0, pitch))
    distance = max(0.35, min(2.0, distance))
    width = max(320, min(1440, width))
    height = max(240, min(960, height))
    with state_lock():
        try:
            saved = load_state()
            if saved and saved.get("backend") == "hardware":
                raise ConfigurationError("Hardware benchmark cannot render a substituted simulator world.")
            selected_model = str(saved["model"]["id"]) if saved else "so101"
            selected_scene = str(saved.get("scene", "empty")) if saved else "empty"
            with JollyEngine(selected_model, selected_scene) as engine:
                if saved:
                    engine.restore(saved)
                rendered_width, rendered_height, rgb = engine.camera_rgb(
                    width=width,
                    height=height,
                    yaw=yaw,
                    pitch=pitch,
                    distance=distance,
                )
        except JollyError as exc:
            raise HTTPException(
                status_code=400, detail={"type": exc.__class__.__name__, "message": str(exc)}
            ) from exc
    return Response(
        _encode_png(rendered_width, rendered_height, rgb),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


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
        benchmark_control=(
            "move",
            {
                "joints_degrees": request.joints,
                "gripper": request.gripper,
                "steps": request.steps,
                "allow_collision": request.allow_collision,
            },
        ),
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
        benchmark_control=(
            "reach",
            {
                "x": request.x,
                "y": request.y,
                "z": request.z,
                "gripper": request.gripper,
                "steps": request.steps,
                "allow_collision": request.allow_collision,
            },
        ),
    )


@app.post("/api/reset")
def reset(request: ResetRequest) -> dict[str, object]:
    return _run(
        lambda engine: engine.reset(),
        model=request.model,
        scene=request.scene,
        preserve_metadata=False,
    )

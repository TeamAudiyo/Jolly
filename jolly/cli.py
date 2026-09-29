from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from jolly import __version__
from jolly.benchmark import run_benchmark
from jolly.challenges import evaluate, get_challenge, list_challenges
from jolly.driver import JollyDriver
from jolly.engine import JollyEngine
from jolly.core.errors import ConfigurationError, JollyError
from jolly.core.models import get_model, list_models
from jolly.core.scenes import get_scene, list_scenes
from jolly.core.store import load_state, save_state, state_lock

console = Console()


def emit(data: Any, *, json_output: bool, message: str | None = None) -> None:
    if json_output:
        click.echo(json.dumps(data, indent=2, sort_keys=True))
    elif message:
        click.echo(message)
    elif isinstance(data, dict):
        click.echo(json.dumps(data, indent=2, sort_keys=True))
    else:
        click.echo(str(data))


def parse_joints(_: click.Context, __: click.Parameter, value: str | None) -> list[float] | None:
    if value is None:
        return None
    try:
        values = [float(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise click.BadParameter("Use comma-separated numbers in degrees.") from exc
    if not values:
        raise click.BadParameter("Provide at least one joint angle.")
    return values


@contextmanager
def current_engine(
    *, model: str | None = None, scene: str | None = None, gui: bool = False, recover: bool = False
) -> Iterator[JollyEngine]:
    with state_lock():
        try:
            saved = load_state()
        except ConfigurationError:
            if not recover:
                raise
            saved = None
        selected_model = model or (str(saved["model"]["id"]) if saved else "jolly6")
        selected_scene = scene or (str(saved.get("scene", "empty")) if saved else "empty")
        with JollyEngine(model=selected_model, scene=selected_scene, gui=gui, realtime=gui) as engine:
            if saved and saved.get("model", {}).get("id") == selected_model and saved.get("scene") == selected_scene:
                engine.restore(saved)
            yield engine


def persist(
    engine: JollyEngine,
    *,
    extra: dict[str, object] | None = None,
    count_challenge_command: bool = False,
) -> dict[str, object]:
    state = engine.state()
    previous = load_state() or {}
    if "active_challenge" in previous:
        for key in ("active_challenge", "challenge_seed", "challenge_instance"):
            if key in previous:
                state[key] = previous[key]
        state["challenge_commands"] = int(previous.get("challenge_commands", 0)) + int(count_challenge_command)
    if extra:
        state.update(extra)
    save_state(state)
    return state


def json_error(exc: Exception) -> str:
    return json.dumps({"ok": False, "error": {"type": exc.__class__.__name__, "message": str(exc)}}, sort_keys=True)


class SafeGroup(click.Group):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ctx.meta["json_requested"] = "--json" in args or os.environ.get("JOLLY_JSON") == "1"
        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except JollyError as exc:
            if ctx.meta.get("json_requested"):
                click.echo(json_error(exc))
                ctx.exit(2)
            raise click.ClickException(str(exc)) from exc


@click.group(cls=SafeGroup, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__)
def main() -> None:
    """Jolly: local robot-arm physics for terminal users and LLM agents."""


@main.command("models")
@click.option("json_output", "--json", is_flag=True, help="Return structured JSON.")
def models_command(json_output: bool) -> None:
    """List bundled robot models."""
    data = {"ok": True, "models": list_models()}
    if json_output:
        emit(data, json_output=True)
        return
    table = Table(title="Jolly robot models")
    table.add_column("ID")
    table.add_column("DOF", justify="right")
    table.add_column("Name")
    table.add_column("License")
    for model in data["models"]:
        table.add_row(str(model["id"]), str(model["dof"]), str(model["name"]), str(model["license"]))
    console.print(table)


@main.command("state")
@click.option("model", "--model", type=click.Choice([item["id"] for item in list_models()]))
@click.option("json_output", "--json", is_flag=True, help="Return structured JSON.")
def state_command(model: str | None, json_output: bool) -> None:
    """Return joints, tool pose, objects, and collisions."""
    with current_engine(model=model) as engine:
        data = persist(engine)
    emit(data, json_output=json_output, message=f"{data['model']['name']}: tool={data['end_effector']['position']} collision={data['collisions']['collision']}")


@main.command("move")
@click.option("joints", "--joints", required=True, callback=parse_joints, help="Comma-separated joint angles in degrees.")
@click.option("gripper", "--gripper", type=click.FloatRange(0.0, 1.0))
@click.option("steps", "--steps", type=click.IntRange(1, 2400), default=120, show_default=True)
@click.option("allow_collision", "--allow-collision", is_flag=True, help="Do not roll back a colliding motion.")
@click.option("json_output", "--json", is_flag=True, help="Return structured JSON.")
def move_command(joints: list[float], gripper: float | None, steps: int, allow_collision: bool, json_output: bool) -> None:
    """Move to exact joint angles."""
    with current_engine() as engine:
        data = engine.move_joints(joints, gripper=gripper, steps=steps, allow_collision=allow_collision)
        data = persist(
            engine,
            extra={"ik": data.get("ik")} if data.get("ik") else None,
            count_challenge_command=True,
        )
    emit(data, json_output=json_output, message=f"Moved {len(joints)} joints. Tool={data['end_effector']['position']}")


@main.command("reach")
@click.option("x", "--x", required=True, type=float)
@click.option("y", "--y", required=True, type=float)
@click.option("z", "--z", required=True, type=float)
@click.option("gripper", "--gripper", type=click.FloatRange(0.0, 1.0))
@click.option("steps", "--steps", type=click.IntRange(1, 2400), default=160, show_default=True)
@click.option("allow_collision", "--allow-collision", is_flag=True)
@click.option("json_output", "--json", is_flag=True, help="Return structured JSON.")
def reach_command(x: float, y: float, z: float, gripper: float | None, steps: int, allow_collision: bool, json_output: bool) -> None:
    """Solve inverse kinematics and move the tool."""
    with current_engine() as engine:
        data = engine.reach(x, y, z, gripper=gripper, steps=steps, allow_collision=allow_collision)
        ik = data["ik"]
        data = persist(engine, extra={"ik": ik}, count_challenge_command=True)
    emit(data, json_output=json_output, message=f"Reached {data['end_effector']['position']} with {data['ik']['error_meters']:.4f} m error.")


@main.command("fk")
@click.option("joints", "--joints", callback=parse_joints, help="Optional comma-separated angles in degrees.")
@click.option("json_output", "--json", is_flag=True)
def fk_command(joints: list[float] | None, json_output: bool) -> None:
    """Compute forward kinematics without changing saved state."""
    with current_engine() as engine:
        data = {"ok": True, "model": engine.model.id, "forward_kinematics": engine.forward_kinematics(joints)}
    emit(data, json_output=json_output)


@main.command("reset")
@click.option("model", "--model", type=click.Choice([item["id"] for item in list_models()]), default="jolly6")
@click.option("scene", "--scene", type=click.Choice([item["id"] for item in list_scenes()]), default="empty")
@click.option("json_output", "--json", is_flag=True)
def reset_command(model: str, scene: str, json_output: bool) -> None:
    """Reset the world and home the selected robot."""
    with current_engine(model=model, scene=scene, recover=True) as engine:
        data = engine.reset()
        save_state(data)
    emit(data, json_output=json_output, message=f"Reset {model} in scene '{scene}'.")


@main.command("render")
@click.option("json_output", "--json", is_flag=True, help="Return pose points instead of a table.")
def render_command(json_output: bool) -> None:
    """Render a compact terminal status table and stick figure."""
    with current_engine() as engine:
        state = engine.state()
        points = engine.joint_positions()
        state = persist(engine)
    if json_output:
        emit({"ok": True, "state": state, "skeleton_points": points}, json_output=True)
        return
    table = Table(title=f"Jolly · {state['model']['name']} · {state['scene']}")
    table.add_column("Joint")
    table.add_column("Angle", justify="right")
    table.add_column("Limits", justify="right")
    for joint in state["joints"]:
        limits = joint["limits_degrees"]
        table.add_row(joint["name"], f"{joint['position_degrees']:.2f}°", f"{limits[0]:.0f}° … {limits[1]:.0f}°")
    console.print(table)
    ee = state["end_effector"]["position"]
    collision = "COLLISION" if state["collisions"]["collision"] else "clear"
    console.print(f"base ●──●──●──●──●──◆ tool  xyz=({ee[0]:.3f}, {ee[1]:.3f}, {ee[2]:.3f})")
    console.print(f"gripper={state['gripper']:.2f}  held={state['held_object'] or 'none'}  collision={collision}")


@main.group("scene")
def scene_group() -> None:
    """List or load simulation scenes."""


@scene_group.command("list")
@click.option("json_output", "--json", is_flag=True)
def scene_list_command(json_output: bool) -> None:
    data = {"ok": True, "scenes": list_scenes()}
    emit(data, json_output=json_output)


@scene_group.command("load")
@click.argument("scene_id", type=click.Choice([item["id"] for item in list_scenes()]))
@click.option("json_output", "--json", is_flag=True)
def scene_load_command(scene_id: str, json_output: bool) -> None:
    get_scene(scene_id)
    saved = load_state()
    model = str(saved["model"]["id"]) if saved else "jolly6"
    with current_engine(model=model, scene=scene_id) as engine:
        data = engine.reset()
        save_state(data)
    emit(data, json_output=json_output, message=f"Loaded scene '{scene_id}'.")


@main.group("challenge")
def challenge_group() -> None:
    """Run repeatable manipulation challenges."""


@challenge_group.command("list")
@click.option("json_output", "--json", is_flag=True)
def challenge_list_command(json_output: bool) -> None:
    emit({"ok": True, "challenges": list_challenges()}, json_output=json_output)


@challenge_group.command("start")
@click.argument("challenge_id", type=click.Choice([item["id"] for item in list_challenges()]))
@click.option("model", "--model", type=click.Choice([item["id"] for item in list_models()]), default="jolly6")
@click.option("seed", "--seed", type=click.IntRange(0, 2**63 - 1))
@click.option("json_output", "--json", is_flag=True)
def challenge_start_command(challenge_id: str, model: str, seed: int | None, json_output: bool) -> None:
    challenge = get_challenge(challenge_id)
    driver = JollyDriver(seed)
    instance = driver.challenge_instance(challenge_id)
    with current_engine(model=model, scene=challenge.scene) as engine:
        engine.reset()
        state = engine.set_object_positions(instance["object_positions"])
        state["active_challenge"] = challenge_id
        state["challenge_commands"] = 0
        state["challenge_seed"] = driver.seed
        state["challenge_instance"] = instance
        save_state(state)
    emit({"ok": True, "challenge": vars(challenge), "seed": driver.seed, "instance": instance, "state": state}, json_output=json_output, message=f"Started randomized '{challenge.name}' with seed {driver.seed}.")


@challenge_group.command("status")
@click.option("challenge_id", "--challenge", type=click.Choice([item["id"] for item in list_challenges()]))
@click.option("json_output", "--json", is_flag=True)
def challenge_status_command(challenge_id: str | None, json_output: bool) -> None:
    saved = load_state() or {}
    selected = challenge_id or saved.get("active_challenge")
    if not selected:
        raise ConfigurationError("No active challenge. Run 'jolly challenge start ID'.")
    with current_engine() as engine:
        state = persist(engine)
    data = evaluate(str(selected), state)
    emit(data, json_output=json_output, message=f"{data['challenge']['name']}: {'PASS' if data['success'] else 'IN PROGRESS'} · score={data['score']}")


@main.command("benchmark")
@click.option("seed", "--seed", type=click.IntRange(0, 2**63 - 1))
@click.option("cases", "--cases", type=click.IntRange(1, 25), default=3, show_default=True)
@click.option("json_output", "--json", is_flag=True)
def benchmark_command(seed: int | None, cases: int, json_output: bool) -> None:
    """Run Jolly's seeded randomized engine benchmark."""
    data = run_benchmark(seed=seed, cases=cases)
    emit(data, json_output=json_output, message=f"Benchmark score: {data['score']:.1f}/100 ({data['passed']}/{data['total']} checks)")


@main.command("viewer")
@click.option("model", "--model", type=click.Choice([item["id"] for item in list_models()]))
@click.option("scene", "--scene", type=click.Choice([item["id"] for item in list_scenes()]))
def viewer_command(model: str | None, scene: str | None) -> None:
    """Open the native PyBullet 3D window."""
    with current_engine(model=model, scene=scene, gui=True) as engine:
        click.echo("Viewer opened. Close the PyBullet window to exit.")
        engine.run_viewer()


@main.command("serve")
@click.option("host", "--host", default="127.0.0.1", show_default=True)
@click.option("port", "--port", type=click.IntRange(1, 65535), default=8765, show_default=True)
@click.option("unsafe_public", "--unsafe-public", is_flag=True, help="Allow a non-loopback bind without authentication.")
def serve_command(host: str, port: int, unsafe_public: bool) -> None:
    """Start the optional local web viewer and JSON API."""
    if host not in {"127.0.0.1", "localhost", "::1"} and not unsafe_public:
        raise click.ClickException("Non-loopback web control requires explicit --unsafe-public.")
    try:
        import uvicorn
    except ImportError as exc:
        raise click.ClickException("Install web support with: pip install 'jolly-cli[web]'") from exc
    uvicorn.run("jolly.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from jolly import __version__
from jolly.benchmark import (
    BENCHMARK_CHALLENGE,
    BENCHMARK_ID,
    BENCHMARK_METADATA_KEYS,
    CONTROL_WORKFLOW,
    benchmark_control_history,
    score_operator_benchmark,
    activate_trial, ensure_control_allowed, new_session, session_from, summary, validate_configuration,
)
from jolly.challenges import evaluate, get_challenge, list_challenges
from jolly.driver import JollyDriver
from jolly.engine import JollyEngine
from jolly.hardware import SO101Calibration, SO101HardwareDriver, calibration_example
from jolly.core.errors import ConfigurationError, JollyError, MotionError
from jolly.core.models import get_model, list_models
from jolly.core.scenes import get_scene, list_scenes
from jolly.core.store import load_state, save_state, state_lock
from jolly.measurement import hardware_provider, measure_hardware, read_json, utc_now
from jolly.robots.registry import arm_profile, list_arms, model_for_arm, workspace_from

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
    *, model: str | None = None, scene: str | None = None, gui: bool = False, recover: bool = False,
    requested: dict | None = None
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
        if saved and saved.get("active_benchmark") and model and model != saved["model"]["id"] and not recover and scene is None:
            raise ConfigurationError("Cannot change models inside a benchmark. Reset explicitly first.")
        if saved and saved.get("backend") == "hardware" and not recover and scene is None:
            raise ConfigurationError("Hardware state cannot run in the simulator. Use jolly arm controls or reset explicitly.")
        with JollyEngine(model=selected_model, scene=selected_scene, gui=gui, realtime=gui) as engine:
            if saved and saved.get("model", {}).get("id") == selected_model and saved.get("scene") == selected_scene:
                engine.restore(saved)
            try:
                yield engine
            except MotionError as exc:
                if saved and saved.get("active_benchmark") == BENCHMARK_ID:
                    result = engine.state()
                    result["motion_collision"] = engine.motion_collision
                    result["control_error"] = str(exc)
                    controls = benchmark_control_history(
                        saved, source="cli", command="rejected-control",
                        requested=requested or {}, result=result,
                    )
                    saved["benchmark_controls"] = controls
                    save_state(saved)
                raise


def persist(
    engine: JollyEngine,
    *,
    extra: dict[str, object] | None = None,
    count_challenge_command: bool = False,
) -> dict[str, object]:
    state = engine.state()
    previous = load_state() or {}
    if "active_challenge" in previous:
        for key in BENCHMARK_METADATA_KEYS:
            if key in previous:
                state[key] = previous[key]
        state["challenge_commands"] = int(previous.get("challenge_commands", 0)) + int(count_challenge_command)
    if extra:
        state.update(extra)
    save_state(state)
    return state


def benchmark_control_extra(
    previous: dict[str, object],
    *,
    command: str,
    requested: dict[str, object],
    result: dict[str, object],
) -> dict[str, object] | None:
    """Append an explicit operator control when an operator benchmark is active."""
    controls = benchmark_control_history(
        previous,
        source="cli",
        command=command,
        requested=requested,
        result=result,
    )
    if controls is None:
        return None
    return {"benchmark_controls": controls}


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
@click.option("model", "--model", type=str)
@click.option("json_output", "--json", is_flag=True, help="Return structured JSON.")
def state_command(model: str | None, json_output: bool) -> None:
    """Return joints, tool pose, objects, and collisions."""
    saved = load_state()
    if (
        model is not None
        and saved
        and saved.get("active_benchmark") == BENCHMARK_ID
        and saved.get("model", {}).get("id") != model
    ):
        raise ConfigurationError("Cannot change the model while an operator benchmark is active. Run 'jolly reset' first.")
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
    with current_engine(requested={"joints_degrees": joints, "gripper": gripper, "steps": steps, "allow_collision": allow_collision}) as engine:
        ensure_control_allowed(load_state() or {})
        data = engine.move_joints(joints, gripper=gripper, steps=steps, allow_collision=allow_collision)
        previous = load_state() or {}
        benchmark_extra = benchmark_control_extra(
            previous,
            command="move",
            requested={
                "joints_degrees": joints,
                "gripper": gripper,
                "steps": steps,
                "allow_collision": allow_collision,
            },
            result=data,
        )
        data = persist(
            engine,
            extra=benchmark_extra,
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
    with current_engine(requested={"x": x, "y": y, "z": z, "gripper": gripper, "steps": steps, "allow_collision": allow_collision}) as engine:
        ensure_control_allowed(load_state() or {})
        data = engine.reach(x, y, z, gripper=gripper, steps=steps, allow_collision=allow_collision)
        ik = data["ik"]
        previous = load_state() or {}
        benchmark_extra = benchmark_control_extra(
            previous,
            command="reach",
            requested={
                "x": x,
                "y": y,
                "z": z,
                "gripper": gripper,
                "steps": steps,
                "allow_collision": allow_collision,
            },
            result=data,
        ) or {}
        benchmark_extra["ik"] = ik
        data = persist(engine, extra=benchmark_extra, count_challenge_command=True)
    emit(
        data,
        json_output=json_output,
        message=(
            f"Reached {data['end_effector']['position']} with {data['ik']['error_meters']:.4f} m error; "
            f"gripper={data['gripper']:.1f}, held={data['held_object'] or 'none'}."
        ),
    )


@main.command("fk")
@click.option("joints", "--joints", callback=parse_joints, help="Optional comma-separated angles in degrees.")
@click.option("json_output", "--json", is_flag=True)
def fk_command(joints: list[float] | None, json_output: bool) -> None:
    """Compute forward kinematics without changing saved state."""
    with current_engine() as engine:
        data = {"ok": True, "model": engine.model.id, "forward_kinematics": engine.forward_kinematics(joints)}
    emit(data, json_output=json_output)


@main.command("reset")
@click.option("model", "--model", type=str, default="jolly6")
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
@click.option("model", "--model", type=str, default="jolly6")
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


@main.group("benchmark")
def benchmark_group() -> None:
    """Run an operator-controlled randomized pick-and-place benchmark."""


@benchmark_group.command("start")
@click.option("seed", "--seed", type=click.IntRange(0, 2**63 - 1))
@click.option("arm", "--arm", "--model", default="so101", show_default=True)
@click.option("trials", "--trials", type=click.IntRange(1, 100), default=3, show_default=True)
@click.option("backend", "--backend", type=click.Choice(["simulation", "hardware"]), default="simulation")
@click.option("measurement_config", "--measurement-config", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("arm_config", "--arm-config", type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("tolerance", "--placement-tolerance", type=click.FloatRange(min=0.001, max=0.04), default=0.02)
@click.option("max_commands", "--max-commands", type=click.IntRange(1, 1000), default=20)
@click.option("max_seconds", "--max-trial-seconds", type=click.FloatRange(min=1, max=86400))
@click.option("json_output", "--json", is_flag=True)
def benchmark_start_command(seed, arm, trials, backend, measurement_config, arm_config,
                            tolerance, max_commands, max_seconds, json_output):
    """Plan randomized trials; execute no task controls."""
    arm_profile(arm)
    workspace = None
    if backend == "hardware":
        if arm_profile(arm).get("robot_type") is None:
            raise ConfigurationError("This arm has no hardware adapter.")
        hardware_provider(measurement_config)
        if not arm_config:
            raise ConfigurationError("Hardware benchmark needs --arm-config with a calibrated workspace.")
        config = read_json(arm_config)
        if config.get("arm") != arm:
            raise ConfigurationError("Hardware config arm does not match --arm.")
        workspace = workspace_from(config)
    session = new_session(seed, trials, arm, backend, tolerance, max_commands, max_seconds,
                          measurement_config, workspace)
    session["arm_config"] = arm_config
    session["arm_snapshot"] = read_json(arm_config) if arm_config else None
    with state_lock():
        if backend == "simulation":
            with JollyEngine(model_for_arm(arm), "pickplace") as engine:
                state = engine.set_object_positions(session["planned_trials"][0]["object_positions"])
        else:
            state = {"model": {"id": arm}, "backend": "hardware", "objects": []}
        activate_trial(state, session)
        save_state(state)
    data = {"ok": True, "benchmark": BENCHMARK_ID, "backend": backend, "seed": session["seed"],
            "instance": state["challenge_instance"], "state": state, "motion_executed": False,
            "control_workflow": CONTROL_WORKFLOW, "summary": summary(session)}
    emit(data, json_output=json_output, message=f"Trial 1/{trials}, seed {session['seed']}: pickup={state['challenge_instance']['object_positions']['part']}, target={state['challenge_instance']['target']}. Enter explicit controls, then benchmark score.")


@benchmark_group.command("score")
@click.option("json_output", "--json", is_flag=True)
def benchmark_score_command(json_output):
    """Measure once; report numeric trial error and success percentage."""
    with state_lock():
        saved = load_state() or {}
        session = session_from(saved)
        if len(session["results"]) > session["current_trial_index"]:
            data = score_operator_benchmark(saved)
        elif session["backend"] == "simulation":
            with JollyEngine(saved["model"]["id"], saved["scene"]) as engine:
                engine.restore(saved)
                data = score_operator_benchmark(saved, engine)
                state = engine.state()
                for key in BENCHMARK_METADATA_KEYS:
                    if key in saved:
                        state[key] = saved[key]
                state["challenge_commands"] = saved.get("challenge_commands", 0)
                save_state(state)
        else:
            try:
                data = score_operator_benchmark(saved)
            except ConfigurationError as exc:
                session["aborted"] = {"at": utc_now(), "error": str(exc), "emergency_stop_attempted": False}
                save_state(saved)
                raise
            save_state(saved)
    trial, report = data["trial"], data["summary"]
    emit(data, json_output=json_output, message=f"Trial {trial['index']}: {trial['outcome']}; placement error={trial['placement_error_meters']:.6f} m. Success={report['success_percentage']:.2f}% ({report['successful_trials']}/{report['completed_trials']}).")


@benchmark_group.command("next")
@click.option("json_output", "--json", is_flag=True)
def benchmark_next_command(json_output):
    """Activate the next randomized layout, never solve the trial."""
    with state_lock():
        saved = load_state() or {}
        session = session_from(saved)
        validate_configuration(session)
        if len(session["results"]) <= session["current_trial_index"]:
            raise ConfigurationError("Score the current trial before benchmark next.")
        if session["current_trial_index"] + 1 >= session["trial_count"]:
            raise ConfigurationError("All trials are complete. Run benchmark report.")
        session["current_trial_index"] += 1
        if session["backend"] == "simulation":
            with JollyEngine(model_for_arm(session["arm"]), "pickplace") as engine:
                state = engine.set_object_positions(session["planned_trials"][session["current_trial_index"]]["object_positions"])
        else:
            state = {"model": {"id": session["arm"]}, "backend": "hardware", "objects": []}
        activate_trial(state, session)
        save_state(state)
    emit({"ok": True, "instance": state["challenge_instance"], "summary": summary(session), "motion_executed": False},
         json_output=json_output, message=f"Trial {session['current_trial_index'] + 1}/{session['trial_count']}: pickup={state['challenge_instance']['object_positions']['part']}, target={state['challenge_instance']['target']}.")


@benchmark_group.command("report")
@click.option("json_output", "--json", is_flag=True)
def benchmark_report_command(json_output):
    """Report measured success percentage and mean placement error."""
    session = session_from(load_state() or {})
    report = summary(session)
    if not report["completed_trials"]:
        raise ConfigurationError("No trial is scored. No numeric report is available.")
    emit(report, json_output=json_output, message=f"Success={report['success_percentage']:.2f}% ({report['successful_trials']}/{report['completed_trials']}); mean placement error={report['mean_placement_error_meters']:.6f} m; backend={report['backend']}; complete={report['complete']}.")


@benchmark_group.command("status")
@click.option("json_output", "--json", is_flag=True)
def benchmark_status_command(json_output):
    saved = load_state() or {}
    session = session_from(saved)
    emit({"ok": True, "instance": saved["challenge_instance"], "controls": saved["benchmark_controls"],
          "current_trial": session["current_trial_index"] + 1, "summary": summary(session)}, json_output=json_output)


@benchmark_group.command("history")
@click.option("json_output", "--json", is_flag=True)
def benchmark_history_command(json_output):
    saved = load_state() or {}
    session = session_from(saved) if saved.get("active_benchmark") else None
    emit({"ok": True, "trials": session["results"] if session else [],
          "invalidations": saved.get("benchmark_invalidations", [])}, json_output=json_output)


@main.group("arm")
def arm_group():
    """LeRobot hardware and explicit multi-arm configuration."""


@arm_group.command("list")
@click.option("json_output", "--json", is_flag=True)
def arm_list_command(json_output):
    emit({"ok": True, "arms": list_arms()}, json_output=json_output)


def arm_options(func):
    for decorator in [
        click.option("json_output", "--json", is_flag=True),
        click.option("confirm", "--confirm-hardware", is_flag=True),
        click.option("config", "--config", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True)),
        click.option("arm", "--arm", required=True),
    ]:
        func = decorator(func)
    return func


def run_arm(arm, config, confirm, operation, requested=None):
    if not confirm:
        raise ConfigurationError("LeRobot connection configures motors. Use --confirm-hardware only after supporting the arm and checking calibration.")
    from jolly.robots.lerobot_driver import LeRobotDriver
    with state_lock():
        saved = load_state() or {}
        if saved.get("active_benchmark") and operation != "stop":
            session = session_from(saved)
            if session["backend"] != "hardware" or session["arm"] != arm or Path(session["arm_config"]).resolve() != Path(config).resolve():
                raise ConfigurationError("Hardware arm/config does not match the active trial.")
            validate_configuration(session)
        if requested is not None:
            ensure_control_allowed(saved, "hardware")
        result = {}
        driver = None
        try:
            driver = LeRobotDriver(arm, config)
            with driver:
                if operation == "state":
                    result = driver.state()
                elif operation == "stop":
                    driver.stop()
                    return {"ok": True, "torque_enabled": False}
                elif operation == "move":
                    result = driver.move(requested["joints"], requested["gripper"])
                else:
                    result = driver.reach(requested["x"], requested["y"], requested["z"], requested["gripper"])
                if requested is not None and saved.get("active_benchmark"):
                    session = session_from(saved)
                    instance = saved["challenge_instance"]
                    measurements = measure_hardware(session["measurement_config"], ["part", instance["place_slot"]],
                                                     trial_id=f"{session['seed']}:{session['current_trial_index'] + 1}",
                                                     not_before=session["trial_started_at"])
                    result["sensor_evidence"] = measurements.get("evidence", {})
                    if result["sensor_evidence"].get("collision_free_during_trial") is False:
                        raise MotionError("Sensor reports a hardware collision. Emergency stop required.")
                    saved["benchmark_controls"] = benchmark_control_history(saved, source="lerobot", command=operation,
                                                                             requested=requested, result=result)
                    save_state(saved)
                return result
        except Exception as exc:
            if requested is not None and saved.get("active_benchmark"):
                result["control_error"] = str(exc)
                saved["benchmark_controls"] = benchmark_control_history(saved, source="lerobot", command=operation,
                                                                         requested=requested, result=result)
                session_from(saved)["aborted"] = {"at": utc_now(), "error": str(exc),
                                                  "emergency_stop_attempted": bool(driver and driver.emergency_stop_attempted)}
                save_state(saved)
            raise


@arm_group.command("state")
@arm_options
def arm_state_command(arm, config, confirm, json_output):
    emit(run_arm(arm, config, confirm, "state"), json_output=json_output)


@arm_group.command("move")
@arm_options
@click.option("joints", "--joints", required=True, callback=parse_joints)
@click.option("gripper", "--gripper", type=click.FloatRange(0, 1))
def arm_move_command(arm, config, confirm, json_output, joints, gripper):
    emit(run_arm(arm, config, confirm, "move", {"joints": joints, "gripper": gripper}), json_output=json_output)


@arm_group.command("reach")
@arm_options
@click.option("x", "--x", type=float, required=True)
@click.option("y", "--y", type=float, required=True)
@click.option("z", "--z", type=float, required=True)
@click.option("gripper", "--gripper", type=click.FloatRange(0, 1))
def arm_reach_command(arm, config, confirm, json_output, x, y, z, gripper):
    emit(run_arm(arm, config, confirm, "reach", {"x": x, "y": y, "z": z, "gripper": gripper}), json_output=json_output)


@arm_group.command("stop")
@arm_options
def arm_stop_command(arm, config, confirm, json_output):
    emit(run_arm(arm, config, confirm, "stop"), json_output=json_output, message="Hardware torque disable attempted. Support the arm.")


@main.group("hardware")
def hardware_group() -> None:
    """Control a physical SO-101 through its STS3215 serial bus."""


def _hardware(port: str, calibration_path: str) -> SO101HardwareDriver:
    return SO101HardwareDriver(port, SO101Calibration.load(calibration_path))


@hardware_group.command("calibration-example")
@click.option("output", "--output", required=True, type=click.Path(dir_okay=False))
def hardware_calibration_example_command(output: str) -> None:
    """Write a physical-arm calibration template without enabling hardware."""
    Path(output).write_text(json.dumps(calibration_example(), indent=2) + "\n", encoding="utf-8")
    click.echo(f"Wrote placeholder calibration template to {output}. Measure the physical arm before use.")


@hardware_group.command("scan")
@click.option("port", "--port", required=True, help="Serial device, for example /dev/ttyACM0.")
@click.option("calibration_path", "--calibration", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("json_output", "--json", is_flag=True)
def hardware_scan_command(port: str, calibration_path: str, json_output: bool) -> None:
    """Ping the six configured physical motors."""
    with _hardware(port, calibration_path) as hardware:
        found = hardware.scan()
    emit({"ok": len(found) == 6, "driver": SO101HardwareDriver.name, "port": port, "motor_ids": found}, json_output=json_output, message=f"Found physical motor IDs: {found}")


@hardware_group.command("state")
@click.option("port", "--port", required=True)
@click.option("calibration_path", "--calibration", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("json_output", "--json", is_flag=True)
def hardware_state_command(port: str, calibration_path: str, json_output: bool) -> None:
    """Read measured positions from a physical SO-101."""
    with _hardware(port, calibration_path) as hardware:
        data = hardware.state()
    emit(data, json_output=json_output, message="Read physical SO-101 state.")


@hardware_group.command("move")
@click.option("port", "--port", required=True)
@click.option("calibration_path", "--calibration", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("joints", "--joints", required=True, callback=parse_joints)
@click.option("gripper", "--gripper", required=True, type=click.FloatRange(0.0, 1.0))
@click.option("confirm_hardware", "--confirm-hardware", is_flag=True, help="Confirm that the physical workspace is clear.")
@click.option("json_output", "--json", is_flag=True)
def hardware_move_command(port: str, calibration_path: str, joints: list[float], gripper: float, confirm_hardware: bool, json_output: bool) -> None:
    """Move a physical SO-101 with feedback and a 20-degree step limit."""
    if not confirm_hardware:
        raise ConfigurationError("Physical movement requires --confirm-hardware after clearing the workspace.")
    with _hardware(port, calibration_path) as hardware:
        data = hardware.move(joints, gripper)
    emit(data, json_output=json_output, message=f"Physical move completed with {data['max_error_degrees']:.2f}° maximum error. Torque remains enabled to hold the arm; support it before 'hardware stop'.")


@hardware_group.command("benchmark")
@click.option("port", "--port", required=True)
@click.option("calibration_path", "--calibration", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True))
@click.option("seed", "--seed", type=click.IntRange(0, 2**63 - 1))
@click.option("cases", "--cases", type=click.IntRange(1, 10), default=3, show_default=True)
@click.option("confirm_hardware", "--confirm-hardware", is_flag=True, help="Confirm a clear physical workspace and bounded motion.")
@click.option("json_output", "--json", is_flag=True)
def hardware_benchmark_command(port: str, calibration_path: str, seed: int | None, cases: int, confirm_hardware: bool, json_output: bool) -> None:
    """Execute bounded random motion on a physical SO-101 and score feedback."""
    if not confirm_hardware:
        raise ConfigurationError("Physical benchmarking requires --confirm-hardware after clearing the workspace.")
    selected_seed = seed if seed is not None else secrets.randbits(63)
    with _hardware(port, calibration_path) as hardware:
        data = hardware.benchmark(seed=selected_seed, cases=cases)
    emit(data, json_output=json_output, message=f"Physical hardware score: {data['score']:.1f}/100.")


@hardware_group.command("stop")
@click.option("port", "--port", required=True)
@click.option("calibration_path", "--calibration", required=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True))
def hardware_stop_command(port: str, calibration_path: str) -> None:
    """Disable torque on every configured physical motor."""
    with _hardware(port, calibration_path) as hardware:
        hardware.emergency_stop()
    click.echo("Physical SO-101 torque disabled.")


@main.command("viewer")
@click.option("model", "--model", type=str)
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

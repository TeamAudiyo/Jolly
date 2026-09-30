"""Sequential randomized trials scored from object measurements, not commands."""
from __future__ import annotations

import copy
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from jolly.core.errors import ConfigurationError
from jolly.driver import JollyDriver
from jolly.measurement import measure_hardware, measure_simulation, read_json, utc_now

BENCHMARK_ID = "jolly-pick-place-trials-v1"
BENCHMARK_CHALLENGE = "pickplace"
BENCHMARK_METADATA_KEYS = (
    "active_challenge", "challenge_seed", "challenge_instance", "active_benchmark",
    "benchmark_controls", "benchmark_session", "benchmark_invalidations",
)
CONTROL_WORKFLOW = [
    "Read this trial's measured pickup position and generated destination.",
    "Issue explicit reach/move commands: approach, descend, grasp, lift, carry, lower, release.",
    "Score the trial, then use benchmark next for a different randomized trial.",
    "Use benchmark report for measured success percentage and placement error.",
]


def session_from(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("active_benchmark") != BENCHMARK_ID or not isinstance(state.get("benchmark_session"), dict):
        raise ConfigurationError("No current measured benchmark. Run 'jolly benchmark start' (old 0.5 states require restart).")
    return state["benchmark_session"]


def ensure_control_allowed(state: dict[str, Any], backend: str = "simulation") -> None:
    if "active_benchmark" not in state:
        return
    session = session_from(state)
    validate_configuration(session)
    if session.get("aborted"):
        raise ConfigurationError("Trial aborted after a hardware or sensor error. Stop safely, then restart the benchmark.")
    if session["backend"] != backend:
        raise ConfigurationError(f"Active benchmark uses {session['backend']}; this control uses {backend}.")
    if len(session["results"]) > session["current_trial_index"]:
        raise ConfigurationError("Trial is already scored. Run 'jolly benchmark next' before another control.")


def new_session(seed: int | None, trials: int, arm: str, backend: str, tolerance: float,
                max_commands: int, max_seconds: float | None, measurement_config: str | None,
                workspace: list[list[float]] | None = None) -> dict[str, Any]:
    if not math.isfinite(tolerance) or not 0.001 <= tolerance <= 0.04:
        raise ConfigurationError("Placement tolerance must be finite and within 0.001..0.04 meters.")
    if max_seconds is not None and (not math.isfinite(max_seconds) or not 1 <= max_seconds <= 86400):
        raise ConfigurationError("Time budget must be finite and within 1..86400 seconds.")
    driver = JollyDriver(seed)
    layouts = [driver.pick_place_instance(workspace) for _ in range(trials)]
    from jolly.robots.registry import configuration
    return {"id": BENCHMARK_ID, "backend": backend, "arm": arm, "seed": driver.seed,
            "planned_trials": layouts, "trial_count": trials, "current_trial_index": 0,
            "results": [], "started_at": utc_now(), "trial_started_at": utc_now(),
            "placement_tolerance_meters": tolerance, "max_commands": max_commands,
            "max_trial_seconds": max_seconds, "measurement_config": measurement_config,
            "registry_snapshot": configuration(),
            "measurement_snapshot": read_json(measurement_config) if measurement_config else None}


def validate_configuration(session: dict[str, Any]) -> None:
    from jolly.robots.registry import configuration
    if configuration() != session.get("registry_snapshot", {}):
        raise ConfigurationError("Arm registry changed during the trial. Restart the benchmark.")
    for path_key, snapshot_key in (("measurement_config", "measurement_snapshot"), ("arm_config", "arm_snapshot")):
        path = session.get(path_key)
        if path and read_json(path) != session.get(snapshot_key):
            raise ConfigurationError(f"{path_key} changed during the trial. Restart the benchmark.")


def activate_trial(state: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    instance = session["planned_trials"][session["current_trial_index"]]
    state.update(active_challenge=BENCHMARK_CHALLENGE, active_benchmark=BENCHMARK_ID,
                 challenge_seed=session["seed"], challenge_instance=instance,
                 benchmark_session=session, benchmark_controls=[], challenge_commands=0)
    session["trial_started_at"] = utc_now()
    return state


def benchmark_control_history(previous: dict[str, Any], *, source: str, command: str,
                              requested: dict[str, Any], result: dict[str, Any]) -> list[Any] | None:
    if previous.get("active_benchmark") != BENCHMARK_ID:
        return None
    ensure_control_allowed(previous, "hardware" if source == "lerobot" else "simulation")
    controls = list(previous.get("benchmark_controls", []))
    controls.append({"index": len(controls) + 1, "source": source, "command": command,
                     "requested": requested, "measured_at": utc_now(),
                     "measured": {
                         "tool_position": result.get("end_effector", {}).get("position"),
                         "gripper": result.get("gripper"), "held_object": result.get("held_object"),
                         "collision": result.get("motion_collision", result.get("collisions", {}).get("collision")),
                         "sensor_evidence": result.get("sensor_evidence", {}),
                         "error": result.get("control_error"),
                     }})
    return controls


def summary(session: dict[str, Any]) -> dict[str, Any]:
    records = session["results"]
    errors = [r["placement_error_meters"] for r in records]
    successes = [r for r in records if r["success"]]
    good_errors = [r["placement_error_meters"] for r in successes]
    return {"ok": True, "benchmark": BENCHMARK_ID, "backend": session["backend"],
            "arm": session["arm"], "seed": session["seed"], "planned_trials": session["trial_count"],
            "completed_trials": len(records), "successful_trials": len(successes),
            "success_percentage": 100 * len(successes) / len(records) if records else None,
            "score": 100 * len(successes) / len(records) if records else None,
            "score_units": "percent successful trials", "placement_error_units": "meters",
            "mean_placement_error_meters": statistics.mean(errors) if errors else None,
            "min_placement_error_meters": min(errors) if errors else None,
            "max_placement_error_meters": max(errors) if errors else None,
            "successful_mean_placement_error_meters": statistics.mean(good_errors) if good_errors else None,
            "complete": len(records) == session["trial_count"],
            "measurement_sources": sorted({r["measurements"]["object"]["source"] for r in records}),
            "failure_counts": dict(Counter(reason for r in records for reason in r["failure_reasons"])),
            "trials": records}


def score_operator_benchmark(state: dict[str, Any], engine: Any = None) -> dict[str, Any]:
    session = session_from(state)
    index = session["current_trial_index"]
    if len(session["results"]) > index:
        return {"ok": True, "trial": copy.deepcopy(session["results"][index]), "summary": summary(session)}
    if session.get("aborted"):
        raise ConfigurationError("Aborted trial has no verified score. Stop safely, then restart the benchmark.")
    validate_configuration(session)
    instance = session["planned_trials"][index]
    controls = state.get("benchmark_controls", [])
    names = ["part", instance["place_slot"]]
    if session["backend"] == "simulation":
        if engine is None:
            raise ConfigurationError("Live simulation measurements are required for scoring.")
        engine.settle()
        measurements = measure_simulation(engine, names)
        final = engine.state()
        grasped = any(c["measured"]["held_object"] == "part" for c in controls)
        released = final["held_object"] is None
        collision_free = not final["collisions"]["collision"] and not any(c["measured"]["collision"] for c in controls)
        # A pad is physical support: use the rotated box bottom height and contact,
        # not the gripper pose. Center must also be near the measured pad center.
        from jolly.core.physics import p
        part = measurements["part"]
        rotation = p.getMatrixFromQuaternion(part["orientation_quaternion"])
        size = engine.object_specs["part"]["size"]
        extent_z = sum(abs(rotation[6 + axis]) * size[axis] / 2 for axis in range(3))
        pad_z = measurements[names[1]]["position_meters"][2] + 0.006
        bottom = part["position_meters"][2] - extent_z
        on_pad = abs(bottom - pad_z) <= 0.008
        p.performCollisionDetection(physicsClientId=engine.client)
        on_pad = on_pad and bool(p.getContactPoints(bodyA=engine.object_ids["part"],
                                    bodyB=engine.object_ids[names[1]], physicsClientId=engine.client))
        linear, angular = p.getBaseVelocity(engine.object_ids["part"], physicsClientId=engine.client)
        stable = all(abs(v) < 0.02 for v in linear) and all(abs(v) < 0.1 for v in angular)
    else:
        trial_id = f"{session['seed']}:{index + 1}"
        measurements = measure_hardware(session["measurement_config"], names, trial_id=trial_id,
                                        not_before=session["trial_started_at"])
        evidence = measurements.pop("evidence", {})
        # Missing evidence is unknown, never presumed true from a command.
        sensor_history = [c["measured"].get("sensor_evidence", {}) for c in controls]
        grasped = any(e.get("grasped_during_trial") is True for e in sensor_history)
        released = evidence.get("released") is True
        collision_free = (evidence.get("collision_free_during_trial") is True
                          and all(e.get("collision_free_during_trial") is True for e in sensor_history))
        on_pad = evidence.get("on_pad") is True
        stable = evidence.get("stable") is True
    obj, target = measurements[names[0]], measurements[names[1]]
    dimensions = min(obj["dimensions"], target["dimensions"])
    error_xy = math.dist(obj["position_meters"][:2], target["position_meters"][:2])
    error_3d = math.dist(obj["position_meters"], target["position_meters"]) if dimensions == 3 else None
    seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(session["trial_started_at"])).total_seconds()
    checks = {"no_grasp_evidence": grasped, "no_release": released,
              "wrong_place": error_xy <= session["placement_tolerance_meters"],
              "collision": collision_free, "not_on_pad": on_pad, "unstable_object": stable,
              "command_budget_exceeded": len(controls) <= session["max_commands"],
              "time_budget_exceeded": session["max_trial_seconds"] is None or seconds <= session["max_trial_seconds"]}
    checks["target_moved"] = math.dist(target["position_meters"][:dimensions], instance["target"][:dimensions]) <= 0.008
    checks["control_failed"] = not any(c["measured"].get("error") for c in controls)
    if session["backend"] == "simulation":
        checks["dropped_object"] = not any(
            before["measured"]["held_object"] == "part" and after["measured"]["held_object"] is None
            and (after["measured"].get("gripper") or 0) >= 0.7
            for before, after in zip(controls, controls[1:])
        )
    failures = sorted(k for k, passed in checks.items() if not passed)
    record = {"index": index + 1, "seed": instance["seed"], "instance": instance,
              "controls": copy.deepcopy(controls), "control_count": len(controls), "measurements": {
                  "object": obj, "target": target}, "placement_error_meters": error_xy,
              "center_distance_3d_meters": error_3d,
              "verification_scope": "3d" if dimensions == 3 else "planar-only",
              "success": not failures, "outcome": "SUCCESS" if not failures else "FAIL",
              "failure_reasons": failures, "duration_seconds": seconds, "scored_at": utc_now(),
              "checks": checks}
    record["grasp_events"] = [c for c in copy.deepcopy(controls) if c["measured"].get("held_object") == "part"
                              or c["measured"].get("sensor_evidence", {}).get("grasped_during_trial") is True]
    record["collision_events"] = [c for c in copy.deepcopy(controls) if c["measured"].get("collision")
                                  or c["measured"].get("sensor_evidence", {}).get("collision_free_during_trial") is False]
    session["results"].append(record)
    return {"ok": True, "trial": record, "summary": summary(session)}

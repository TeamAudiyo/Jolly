from __future__ import annotations

import math
import time
from typing import Any, Callable

from jolly.challenges import list_challenges
from jolly.core.errors import ConfigurationError
from jolly.driver import JollyDriver
from jolly.engine import JollyEngine


def _bounded_accuracy(error: float, full_score_error: float, zero_score_error: float) -> float:
    if error <= full_score_error:
        return 1.0
    if error >= zero_score_error:
        return 0.0
    return 1.0 - (error - full_score_error) / (zero_score_error - full_score_error)


def _task_result(
    *,
    name: str,
    weight: float,
    seed: int,
    started: float,
    score: float,
    metrics: dict[str, object],
    error: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "name": name,
        "seed": seed,
        "weight": weight,
        "score": round(max(0.0, min(weight, score)), 3),
        "passed": score >= weight * 0.7,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "metrics": metrics,
    }
    if error:
        result["error"] = error
    return result


def _run_reach_task(model: str, instance: dict[str, Any]) -> dict[str, object]:
    started = time.perf_counter()
    weight = 25.0
    target = [float(value) for value in instance["target"]]
    try:
        with JollyEngine(model=model, scene="empty") as engine:
            state = engine.reach(*target, tolerance=0.06)
            actual = state["end_effector"]["position"]
            error = math.dist(actual, target)
            collision_free = not state["collisions"]["collision"]
            score = weight * _bounded_accuracy(error, 0.015, 0.08)
            if not collision_free:
                score *= 0.25
            return _task_result(
                name="randomized-reach",
                weight=weight,
                seed=int(instance["seed"]),
                started=started,
                score=score,
                metrics={"target": target, "actual": actual, "error_meters": round(error, 6), "collision_free": collision_free},
            )
    except Exception as exc:
        return _task_result(name="randomized-reach", weight=weight, seed=int(instance["seed"]), started=started, score=0.0, metrics={"target": target}, error=str(exc))


def _run_obstacle_task(model: str, instance: dict[str, Any]) -> dict[str, object]:
    started = time.perf_counter()
    weight = 25.0
    goal = [float(value) for value in instance["target"]]
    target = [goal[0], goal[1], max(0.14, goal[2] + 0.12)]
    try:
        with JollyEngine(model=model, scene="obstacles") as engine:
            engine.set_object_positions(instance["object_positions"])
            state = engine.reach(*target, tolerance=0.07)
            actual = state["end_effector"]["position"]
            error = math.dist(actual, target)
            collision_free = not state["collisions"]["collision"]
            score = weight * _bounded_accuracy(error, 0.02, 0.10)
            if not collision_free:
                score = 0.0
            return _task_result(
                name="randomized-obstacle-reach",
                weight=weight,
                seed=int(instance["seed"]),
                started=started,
                score=score,
                metrics={"target": target, "actual": actual, "error_meters": round(error, 6), "collision_free": collision_free},
            )
    except Exception as exc:
        return _task_result(name="randomized-obstacle-reach", weight=weight, seed=int(instance["seed"]), started=started, score=0.0, metrics={"target": target}, error=str(exc))


def _run_drop_task(model: str, instance: dict[str, Any]) -> dict[str, object]:
    started = time.perf_counter()
    weight = 50.0
    peg_start = [float(value) for value in instance["object_positions"]["peg"]]
    target = [float(value) for value in instance["target"]]
    metrics: dict[str, object] = {"peg_start": peg_start, "hole_center": target}
    try:
        with JollyEngine(model=model, scene="insertion") as engine:
            engine.set_object_positions(instance["object_positions"])
            engine.reach(peg_start[0], peg_start[1], peg_start[2] + 0.10, gripper=0.0, tolerance=0.06)
            grasp_state = engine.reach(peg_start[0], peg_start[1], peg_start[2] + 0.095, gripper=1.0, tolerance=0.07)
            grasped = grasp_state["held_object"] == "peg"
            metrics["grasped"] = grasped
            if grasped:
                engine.reach(peg_start[0], peg_start[1], 0.34, gripper=1.0, tolerance=0.08)
                state = engine.reach(target[0], target[1], 0.34, gripper=1.0, tolerance=0.08)
                for height in (0.34, 0.27, 0.27):
                    peg = next(item for item in state["objects"] if item["name"] == "peg")
                    tool = state["end_effector"]["position"]
                    corrected_x = tool[0] + target[0] - peg["position"][0]
                    corrected_y = tool[1] + target[1] - peg["position"][1]
                    state = engine.reach(corrected_x, corrected_y, height, gripper=1.0, tolerance=0.08)
                tool = state["end_effector"]["position"]
                state = engine.reach(tool[0], tool[1], 0.27, gripper=0.0, tolerance=0.08)
            else:
                state = grasp_state
            peg = next(item for item in state["objects"] if item["name"] == "peg")
            xy_error = math.dist(peg["position"][:2], target[:2])
            below_rim = peg["position"][2] < float(instance["rim_height"])
            released = state["held_object"] is None
            collision_free = not state["collisions"]["collision"]
            inside = xy_error <= float(instance["hole_radius"]) and below_rim
            score = 10.0 if grasped else 0.0
            score += 15.0 * _bounded_accuracy(xy_error, 0.008, 0.06)
            score += 20.0 if inside else (8.0 if below_rim else 0.0)
            score += 5.0 if released and collision_free else 0.0
            metrics.update(
                {
                    "final_position": peg["position"],
                    "xy_error_meters": round(xy_error, 6),
                    "inside_hole": inside,
                    "below_rim": below_rim,
                    "released": released,
                    "collision_free": collision_free,
                }
            )
            return _task_result(name="randomized-drop-in-hole", weight=weight, seed=int(instance["seed"]), started=started, score=score, metrics=metrics)
    except Exception as exc:
        return _task_result(name="randomized-drop-in-hole", weight=weight, seed=int(instance["seed"]), started=started, score=0.0, metrics=metrics, error=str(exc))


def run_benchmark(*, seed: int | None = None, cases: int = 3, model: str = "so101") -> dict[str, object]:
    """Execute randomized contact tasks and score only measured physical outcomes."""
    if not 1 <= cases <= 25:
        raise ConfigurationError("Benchmark cases must be between 1 and 25.")
    if model not in ("so101", "jolly6"):
        raise ConfigurationError(f"Unsupported benchmark model '{model}'.")
    driver = JollyDriver(seed)
    tasks: list[dict[str, object]] = []
    started = time.perf_counter()
    generators: list[tuple[str, Callable[[str, dict[str, Any]], dict[str, object]]]] = [
        ("reach-center", _run_reach_task),
        ("obstacle-reach", _run_obstacle_task),
        ("drop-in-hole", _run_drop_task),
    ]
    for case_index in range(cases):
        for challenge_id, execute in generators:
            instance = driver.challenge_instance(challenge_id)
            result = execute(model, instance)
            result["case"] = case_index + 1
            result["challenge"] = challenge_id
            result["instance"] = instance
            tasks.append(result)
    earned = sum(float(task["score"]) for task in tasks)
    available = sum(float(task["weight"]) for task in tasks)
    score = 100.0 * earned / available if available else 0.0
    passed = sum(1 for task in tasks if task["passed"])
    return {
        "ok": passed == len(tasks),
        "benchmark": "jolly-physical-tasks-v3",
        "engine": JollyEngine.name,
        "driver": JollyDriver.name,
        "physics_backend": JollyEngine.physics_backend,
        "model": model,
        "seed": driver.seed,
        "cases": cases,
        "score": round(score, 2),
        "score_basis": "Measured reach error, contact-safe motion, grasp state, physical release, and final peg pose.",
        "passed": passed,
        "total": len(tasks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "tasks": tasks,
        "agent_challenges": list_challenges(),
    }

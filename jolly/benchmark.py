from __future__ import annotations

import math
import time

from jolly.challenges import list_challenges
from jolly.core.errors import ConfigurationError
from jolly.driver import JollyDriver
from jolly.engine import JollyEngine
from jolly.core.models import MODELS


def run_benchmark(*, seed: int | None = None, cases: int = 3) -> dict[str, object]:
    """Run seeded randomized checks with Jolly's own engine and driver."""
    if not 1 <= cases <= 25:
        raise ConfigurationError("Benchmark cases must be between 1 and 25.")
    driver = JollyDriver(seed)
    checks: list[dict[str, object]] = []
    started = time.perf_counter()
    for model_id in MODELS:
        for case_index in range(cases):
            case_started = time.perf_counter()
            generated: dict[str, object] = {"seed": None}
            try:
                with JollyEngine(model=model_id, scene="empty") as engine:
                    limits = [
                        (math.degrees(joint.lower), math.degrees(joint.upper))
                        for joint in engine.arm_joints
                    ]
                    generated = driver.joint_case(limits)
                    fk = engine.forward_kinematics(generated["joints_degrees"])
                    finite = all(math.isfinite(value) for value in fk["position"])
                    passed = len(generated["joints_degrees"]) == engine.model.dof and finite
                    checks.append(
                        {
                            "name": f"{model_id}:random-fk:{case_index + 1}",
                            "passed": passed,
                            "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                            "input": generated,
                            "metrics": {"dof": engine.model.dof, "end_effector": fk["position"]},
                        }
                    )
            except Exception as exc:  # benchmark reports errors instead of hiding remaining cases
                checks.append(
                    {
                        "name": f"{model_id}:random-fk:{case_index + 1}",
                        "passed": False,
                        "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                        "input": generated,
                        "error": str(exc),
                    }
                )
    scene_challenges = {"blocks": "sort-red", "shelf": "shelf-load", "obstacles": "obstacle-reach"}
    for scene, challenge_id in scene_challenges.items():
        for case_index in range(cases):
            case_started = time.perf_counter()
            generated = driver.challenge_instance(challenge_id)
            try:
                with JollyEngine(scene=scene) as engine:
                    engine.set_object_positions(generated["object_positions"])
                    state = engine.state()
                    positions = {item["name"]: item["position"] for item in state["objects"]}
                    applied = all(
                        name in positions and math.dist(position, positions[name]) <= 0.001
                        for name, position in generated["object_positions"].items()
                    )
                    checks.append(
                        {
                            "name": f"scene:{scene}:random:{case_index + 1}",
                            "passed": len(state["objects"]) > 0 and applied,
                            "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                            "input": generated,
                            "metrics": {"objects": len(state["objects"]), "positions_applied": applied},
                        }
                    )
            except Exception as exc:
                checks.append(
                    {
                        "name": f"scene:{scene}:random:{case_index + 1}",
                        "passed": False,
                        "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                        "input": generated,
                        "error": str(exc),
                    }
                )
    passed = sum(1 for check in checks if check["passed"])
    return {
        "ok": passed == len(checks),
        "benchmark": "jolly-randomized-engine-v2",
        "engine": JollyEngine.name,
        "driver": JollyDriver.name,
        "physics_backend": JollyEngine.physics_backend,
        "seed": driver.seed,
        "cases_per_group": cases,
        "score": round(100 * passed / len(checks), 2),
        "passed": passed,
        "total": len(checks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "checks": checks,
        "agent_challenges": list_challenges(),
    }

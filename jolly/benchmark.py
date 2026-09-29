from __future__ import annotations

import math
import time

from jolly.challenges import list_challenges
from jolly.core.models import MODELS
from jolly.core.physics import PhysicsEngine


def run_benchmark() -> dict[str, object]:
    """Run deterministic engine checks, not an agent policy."""
    checks: list[dict[str, object]] = []
    started = time.perf_counter()
    for model_id in MODELS:
        case_started = time.perf_counter()
        try:
            with PhysicsEngine(model=model_id, scene="empty") as engine:
                state = engine.state()
                home = [joint["position_degrees"] for joint in state["joints"]]
                fk = engine.forward_kinematics(home)
                finite = all(math.isfinite(value) for value in fk["position"])
                passed = len(home) == engine.model.dof and finite
                checks.append(
                    {
                        "name": f"{model_id}:load-fk",
                        "passed": passed,
                        "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                        "metrics": {"dof": len(home), "end_effector": fk["position"]},
                    }
                )
        except Exception as exc:  # benchmark reports errors instead of hiding remaining cases
            checks.append(
                {
                    "name": f"{model_id}:load-fk",
                    "passed": False,
                    "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                    "error": str(exc),
                }
            )
    for scene in ("blocks", "shelf", "obstacles"):
        case_started = time.perf_counter()
        try:
            with PhysicsEngine(scene=scene) as engine:
                state = engine.state()
                checks.append(
                    {
                        "name": f"scene:{scene}",
                        "passed": len(state["objects"]) > 0,
                        "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                        "metrics": {"objects": len(state["objects"])},
                    }
                )
        except Exception as exc:
            checks.append(
                {
                    "name": f"scene:{scene}",
                    "passed": False,
                    "duration_ms": round((time.perf_counter() - case_started) * 1000, 3),
                    "error": str(exc),
                }
            )
    passed = sum(1 for check in checks if check["passed"])
    return {
        "ok": passed == len(checks),
        "benchmark": "jolly-engine-v1",
        "score": round(100 * passed / len(checks), 2),
        "passed": passed,
        "total": len(checks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "checks": checks,
        "agent_challenges": list_challenges(),
    }

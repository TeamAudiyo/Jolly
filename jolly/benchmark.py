from __future__ import annotations

from typing import Any

from jolly.challenges import evaluate
from jolly.core.errors import ConfigurationError

BENCHMARK_ID = "jolly-operator-pick-place-v5"
BENCHMARK_CHALLENGE = "drop-in-hole"

CONTROL_WORKFLOW = [
    "Inspect the generated peg and hole coordinates in the start result or with 'jolly state --json'.",
    "Move above the peg with 'jolly reach' and an open gripper.",
    "Move down until the gripper contacts the peg, then close the gripper.",
    "Lift the grasped peg.",
    "Move the peg horizontally above the generated hole.",
    "Lower the peg into the opening and release it.",
    "Run 'jolly benchmark score' to measure the final physical state.",
]


def score_operator_benchmark(state: dict[str, Any]) -> dict[str, object]:
    """Measure an operator-controlled pick-and-place attempt without moving the robot."""
    if state.get("active_benchmark") != BENCHMARK_ID:
        raise ConfigurationError("No operator benchmark is active. Run 'jolly benchmark start'.")
    if state.get("active_challenge") != BENCHMARK_CHALLENGE:
        raise ConfigurationError("The active benchmark is not the drop-in-hole pick-and-place task.")
    controls = state.get("benchmark_controls")
    if not isinstance(controls, list):
        raise ConfigurationError("The active benchmark has no control history. Start it again.")
    evaluation = evaluate(BENCHMARK_CHALLENGE, state)
    success = bool(evaluation["success"])
    return {
        "ok": True,
        "benchmark": BENCHMARK_ID,
        "engine": "JollyEngine",
        "physics_backend": "PyBullet",
        "mode": "operator-controlled",
        "seed": evaluation["seed"],
        "outcome": "PASS" if success else "FAIL",
        "success": success,
        "control_count": len(controls),
        "controls": controls,
        "instance": evaluation["instance"],
        "measurements": evaluation["metrics"],
        "score": None,
        "score_basis": "No synthetic numeric score. PASS requires the released peg to settle inside the generated hole without collision and within the command budget.",
    }

from __future__ import annotations

from typing import Any

from jolly.challenges import evaluate
from jolly.core.errors import ConfigurationError

BENCHMARK_ID = "jolly-operator-pick-place-v5"
BENCHMARK_CHALLENGE = "drop-in-hole"
BENCHMARK_METADATA_KEYS = (
    "active_challenge",
    "challenge_seed",
    "challenge_instance",
    "active_benchmark",
    "benchmark_controls",
)

CONTROL_WORKFLOW = [
    "Inspect the generated peg and hole coordinates in the start result or with 'jolly state --json'.",
    "Move above the peg with 'jolly reach' and an open gripper.",
    "Move down until the gripper contacts the peg, then close the gripper.",
    "Lift the grasped peg.",
    "Move the peg horizontally above the generated hole.",
    "Lower the peg into the opening and release it.",
    "Run 'jolly benchmark score' to measure the final physical state.",
]


def benchmark_control_history(
    previous: dict[str, object],
    *,
    source: str,
    command: str,
    requested: dict[str, object],
    result: dict[str, object],
) -> list[object] | None:
    """Return the control history with one measured explicit motion appended."""
    if previous.get("active_benchmark") != BENCHMARK_ID:
        return None
    existing = previous.get("benchmark_controls", [])
    controls = list(existing) if isinstance(existing, list) else []
    controls.append(
        {
            "index": len(controls) + 1,
            "source": source,
            "command": command,
            "requested": requested,
            "measured": {
                "tool_position": result["end_effector"]["position"],
                "gripper": result["gripper"],
                "held_object": result["held_object"],
                "collision": result["collisions"]["collision"],
            },
        }
    )
    return controls


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

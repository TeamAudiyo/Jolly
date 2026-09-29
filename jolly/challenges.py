from __future__ import annotations

import math
from dataclasses import dataclass

from jolly.core.errors import ConfigurationError


@dataclass(frozen=True)
class Challenge:
    id: str
    name: str
    scene: str
    description: str
    success: str
    max_commands: int


CHALLENGES: dict[str, Challenge] = {
    "reach-center": Challenge(
        id="reach-center",
        name="Reach Center",
        scene="empty",
        description="Move the tool to (0.35, 0.00, 0.18) without a collision.",
        success="End-effector error <= 3 cm and no collision.",
        max_commands=3,
    ),
    "sort-red": Challenge(
        id="sort-red",
        name="Sort Red Block",
        scene="blocks",
        description="Place red_block on left_target.",
        success="Red block center is within 7 cm of the left target center.",
        max_commands=12,
    ),
    "shelf-load": Challenge(
        id="shelf-load",
        name="Shelf Load",
        scene="shelf",
        description="Place cargo on the shelf surface.",
        success="Cargo rests inside the shelf bounds above 12 cm.",
        max_commands=14,
    ),
    "obstacle-reach": Challenge(
        id="obstacle-reach",
        name="Obstacle Reach",
        scene="obstacles",
        description="Reach within 7 cm of goal while remaining collision-free.",
        success="Tool-to-goal error <= 7 cm and no collision.",
        max_commands=10,
    ),
}


def get_challenge(challenge_id: str) -> Challenge:
    try:
        return CHALLENGES[challenge_id]
    except KeyError as exc:
        available = ", ".join(sorted(CHALLENGES))
        raise ConfigurationError(f"Unknown challenge '{challenge_id}'. Available: {available}") from exc


def list_challenges() -> list[dict[str, object]]:
    return [vars(CHALLENGES[key]) for key in sorted(CHALLENGES)]


def evaluate(challenge_id: str, state: dict[str, object]) -> dict[str, object]:
    challenge = get_challenge(challenge_id)
    ee = state["end_effector"]["position"]
    objects = {item["name"]: item for item in state.get("objects", [])}
    collision = bool(state["collisions"]["collision"])
    metrics: dict[str, object]
    success = False
    if challenge_id == "reach-center":
        error = math.dist(ee, [0.35, 0.0, 0.18])
        success = error <= 0.03 and not collision
        metrics = {"target_error_meters": round(error, 6), "collision_free": not collision}
    elif challenge_id == "sort-red":
        position = objects["red_block"]["position"]
        error = math.dist(position[:2], [0.16, -0.27])
        success = error <= 0.07 and position[2] <= 0.09
        metrics = {"target_xy_error_meters": round(error, 6), "block_height_meters": position[2]}
    elif challenge_id == "shelf-load":
        position = objects["cargo"]["position"]
        inside = 0.16 <= position[0] <= 0.40 and 0.10 <= position[1] <= 0.26
        success = inside and position[2] >= 0.12
        metrics = {"inside_shelf_xy": inside, "cargo_height_meters": position[2]}
    else:
        goal = objects["goal"]["position"]
        error = math.dist(ee, goal)
        success = error <= 0.07 and not collision
        metrics = {"goal_error_meters": round(error, 6), "collision_free": not collision}
    return {
        "ok": True,
        "challenge": vars(challenge),
        "success": success,
        "score": 100 if success else 0,
        "metrics": metrics,
    }

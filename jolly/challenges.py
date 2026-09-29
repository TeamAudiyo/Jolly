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
        description="Move the tool to the generated target without a collision.",
        success="End-effector error <= 3 cm and no collision.",
        max_commands=3,
    ),
    "sort-red": Challenge(
        id="sort-red",
        name="Sort Red Block",
        scene="blocks",
        description="Place red_block on the generated target pad.",
        success="Red block center is within 7 cm of the left target center.",
        max_commands=12,
    ),
    "shelf-load": Challenge(
        id="shelf-load",
        name="Shelf Load",
        scene="shelf",
        description="Place randomized cargo on the randomized shelf surface.",
        success="Cargo rests inside the shelf bounds above 12 cm.",
        max_commands=14,
    ),
    "obstacle-reach": Challenge(
        id="obstacle-reach",
        name="Obstacle Reach",
        scene="obstacles",
        description="Reach the generated goal through randomized barriers without collision.",
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
    if state.get("scene") != challenge.scene:
        raise ConfigurationError(
            f"Challenge '{challenge_id}' requires scene '{challenge.scene}', not '{state.get('scene')}'. "
            f"Run 'jolly challenge start {challenge_id}'."
        )
    ee = state["end_effector"]["position"]
    objects = {item["name"]: item for item in state.get("objects", [])}
    collision = bool(state["collisions"]["collision"])
    instance = state.get("challenge_instance")
    if not isinstance(instance, dict):
        raise ConfigurationError("This challenge has no randomized instance. Start it again.")
    metrics: dict[str, object]
    success = False
    if challenge_id == "reach-center":
        target = instance["target"]
        error = math.dist(ee, target)
        success = error <= 0.03 and not collision
        metrics = {"target": target, "target_error_meters": round(error, 6), "collision_free": not collision}
    elif challenge_id == "sort-red":
        object_name = str(instance["object_name"])
        position = objects[object_name]["position"]
        target = instance["target"]
        error = math.dist(position[:2], target[:2])
        success = error <= 0.07 and position[2] <= 0.09
        metrics = {"object": object_name, "target": instance["target_name"], "target_xy_error_meters": round(error, 6), "block_height_meters": position[2]}
    elif challenge_id == "shelf-load":
        position = objects["cargo"]["position"]
        bounds = instance["target_bounds"]
        inside = bounds["x"][0] <= position[0] <= bounds["x"][1] and bounds["y"][0] <= position[1] <= bounds["y"][1]
        success = inside and position[2] >= bounds["minimum_z"]
        metrics = {"inside_shelf_xy": inside, "cargo_height_meters": position[2]}
    else:
        goal = instance["target"]
        error = math.dist(ee, goal)
        success = error <= 0.07 and not collision
        metrics = {"goal_error_meters": round(error, 6), "collision_free": not collision}
    command_count = int(state.get("challenge_commands", 0))
    within_budget = command_count <= challenge.max_commands
    success = success and within_budget
    metrics["commands"] = command_count
    metrics["within_command_budget"] = within_budget
    return {
        "ok": True,
        "challenge": vars(challenge),
        "seed": state.get("challenge_seed"),
        "instance": instance,
        "success": success,
        "score": 100 if success else 0,
        "metrics": metrics,
    }

from __future__ import annotations

import random
import secrets
from typing import Any

from jolly.core.errors import ConfigurationError


class JollyDriver:
    """Generate reproducible, unseen simulator cases without an external harness."""

    name = "JollyDriver"

    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed if seed is not None else secrets.randbits(63)
        self._random = random.Random(self.seed)

    def _case_random(self) -> tuple[int, random.Random]:
        case_seed = self._random.randrange(0, 2**63)
        return case_seed, random.Random(case_seed)

    @staticmethod
    def _point(*values: float) -> list[float]:
        return [round(value, 6) for value in values]

    def challenge_instance(self, challenge_id: str) -> dict[str, Any]:
        case_seed, rng = self._case_random()
        instance: dict[str, Any] = {"seed": case_seed, "object_positions": {}}
        if challenge_id == "reach-center":
            instance["target"] = self._point(
                rng.uniform(0.27, 0.40), rng.uniform(-0.14, 0.14), rng.uniform(0.13, 0.27)
            )
        elif challenge_id == "sort-red":
            slots = [-0.16, 0.0, 0.16]
            rng.shuffle(slots)
            objects = instance["object_positions"]
            for name, y in zip(("red_block", "blue_block", "green_block"), slots, strict=True):
                objects[name] = self._point(rng.uniform(0.27, 0.34), y + rng.uniform(-0.018, 0.018), 0.025)
            left = self._point(rng.uniform(0.14, 0.19), rng.uniform(-0.29, -0.24), 0.006)
            right = self._point(rng.uniform(0.14, 0.19), rng.uniform(0.24, 0.29), 0.006)
            objects["left_target"], objects["right_target"] = left, right
            instance["target_name"] = rng.choice(("left_target", "right_target"))
            instance["target"] = objects[instance["target_name"]]
            instance["object_name"] = "red_block"
        elif challenge_id == "shelf-load":
            objects = instance["object_positions"]
            cargo = self._point(rng.uniform(0.23, 0.34), rng.uniform(-0.22, -0.11), 0.03)
            shelf = self._point(rng.uniform(0.25, 0.31), rng.uniform(0.14, 0.22), 0.12)
            objects["cargo"] = cargo
            objects["shelf"] = shelf
            objects["shelf_back"] = self._point(shelf[0] + 0.11, shelf[1], 0.21)
            instance["target_bounds"] = {
                "x": self._point(shelf[0] - 0.09, shelf[0] + 0.09),
                "y": self._point(shelf[1] - 0.06, shelf[1] + 0.06),
                "minimum_z": 0.12,
            }
            instance["object_name"] = "cargo"
        elif challenge_id == "obstacle-reach":
            objects = instance["object_positions"]
            goal = self._point(rng.uniform(0.35, 0.42), rng.uniform(-0.055, 0.055), 0.025)
            barrier_x = rng.uniform(0.20, 0.25)
            gap = rng.uniform(0.075, 0.105)
            objects["goal"] = goal
            objects["barrier_left"] = self._point(barrier_x, -gap, 0.11)
            objects["barrier_right"] = self._point(barrier_x, gap, 0.11)
            instance["target"] = goal
        else:
            raise ConfigurationError(f"Unknown challenge '{challenge_id}'.")
        return instance

    def joint_case(self, limits_degrees: list[tuple[float, float]]) -> dict[str, Any]:
        case_seed, rng = self._case_random()
        joints = []
        for low, high in limits_degrees:
            margin = (high - low) * 0.18
            joints.append(round(rng.uniform(low + margin, high - margin), 6))
        return {"seed": case_seed, "joints_degrees": joints}

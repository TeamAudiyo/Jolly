from __future__ import annotations

from copy import deepcopy

from jolly.core.errors import ConfigurationError


SCENES: dict[str, dict[str, object]] = {
    "pickplace": {
        "description": "Randomized contact-based pickup and measured placement on a pad.",
        "objects": [
            {"name": "part", "kind": "box", "position": [0.3, -0.14, 0.05], "size": [0.024, 0.024, 0.10], "color": [0.16, 0.58, 0.96, 1.0], "mass": 0.06, "graspable": True},
        ] + [
            {"name": f"{kind}_slot_{i}", "kind": "box", "position": [1.5 + i * 0.2, (-1 if kind == 'pick' else 1), 0.006], "size": [0.1, 0.1, 0.012], "color": [0.96, 0.68, 0.12, 0.7], "mass": 0.0, "graspable": False, "collidable": kind == "place"}
            for kind in ("pick", "place") for i in range(3)
        ],
    },
    "empty": {
        "description": "A clear floor for kinematics and motion checks.",
        "objects": [],
    },
    "blocks": {
        "description": "Three graspable blocks and two marked target pads.",
        "objects": [
            {"name": "red_block", "kind": "box", "position": [0.30, -0.16, 0.025], "size": [0.05, 0.05, 0.05], "color": [0.92, 0.18, 0.16, 1.0], "mass": 0.08, "graspable": True},
            {"name": "blue_block", "kind": "box", "position": [0.32, 0.00, 0.025], "size": [0.05, 0.05, 0.05], "color": [0.12, 0.45, 0.95, 1.0], "mass": 0.08, "graspable": True},
            {"name": "green_block", "kind": "box", "position": [0.30, 0.16, 0.025], "size": [0.05, 0.05, 0.05], "color": [0.16, 0.72, 0.28, 1.0], "mass": 0.08, "graspable": True},
            {"name": "left_target", "kind": "box", "position": [0.16, -0.27, 0.006], "size": [0.12, 0.12, 0.012], "color": [0.96, 0.68, 0.12, 0.45], "mass": 0.0, "graspable": False},
            {"name": "right_target", "kind": "box", "position": [0.16, 0.27, 0.006], "size": [0.12, 0.12, 0.012], "color": [0.68, 0.22, 0.92, 0.45], "mass": 0.0, "graspable": False},
        ],
    },
    "shelf": {
        "description": "A block must move from the floor onto a low shelf.",
        "objects": [
            {"name": "cargo", "kind": "box", "position": [0.28, -0.16, 0.03], "size": [0.06, 0.06, 0.06], "color": [0.15, 0.68, 0.92, 1.0], "mass": 0.10, "graspable": True},
            {"name": "shelf", "kind": "box", "position": [0.28, 0.18, 0.12], "size": [0.22, 0.16, 0.025], "color": [0.52, 0.34, 0.18, 1.0], "mass": 0.0, "graspable": False},
            {"name": "shelf_back", "kind": "box", "position": [0.39, 0.18, 0.21], "size": [0.025, 0.16, 0.20], "color": [0.42, 0.27, 0.14, 1.0], "mass": 0.0, "graspable": False},
        ],
    },
    "obstacles": {
        "description": "Two barriers create a collision-avoidance reaching task.",
        "objects": [
            {"name": "goal", "kind": "box", "position": [0.38, 0.00, 0.025], "size": [0.05, 0.05, 0.05], "color": [0.18, 0.82, 0.34, 1.0], "mass": 0.05, "graspable": True},
            {"name": "barrier_left", "kind": "box", "position": [0.22, -0.09, 0.11], "size": [0.05, 0.09, 0.22], "color": [0.85, 0.22, 0.18, 1.0], "mass": 0.0, "graspable": False},
            {"name": "barrier_right", "kind": "box", "position": [0.22, 0.09, 0.11], "size": [0.05, 0.09, 0.22], "color": [0.85, 0.22, 0.18, 1.0], "mass": 0.0, "graspable": False},
        ],
    },
    "insertion": {
        "description": "A physical peg must be released through a raised square opening.",
        "objects": [
            {"name": "peg", "kind": "box", "position": [0.30, -0.14, 0.05], "size": [0.024, 0.024, 0.10], "color": [0.16, 0.58, 0.96, 1.0], "mass": 0.06, "graspable": True},
            {"name": "hole_bottom", "kind": "box", "position": [0.27, 0.16, 0.012], "size": [0.09, 0.09, 0.024], "color": [0.18, 0.22, 0.28, 1.0], "mass": 0.0, "graspable": False},
            {"name": "hole_left", "kind": "box", "position": [0.27, 0.105, 0.07], "size": [0.12, 0.035, 0.12], "color": [0.70, 0.48, 0.20, 1.0], "mass": 0.0, "graspable": False},
            {"name": "hole_right", "kind": "box", "position": [0.27, 0.215, 0.07], "size": [0.12, 0.035, 0.12], "color": [0.70, 0.48, 0.20, 1.0], "mass": 0.0, "graspable": False},
            {"name": "hole_front", "kind": "box", "position": [0.215, 0.16, 0.07], "size": [0.035, 0.075, 0.12], "color": [0.70, 0.48, 0.20, 1.0], "mass": 0.0, "graspable": False},
            {"name": "hole_back", "kind": "box", "position": [0.325, 0.16, 0.07], "size": [0.035, 0.075, 0.12], "color": [0.70, 0.48, 0.20, 1.0], "mass": 0.0, "graspable": False},
        ],
    },
}


def get_scene(scene_id: str) -> dict[str, object]:
    try:
        scene = deepcopy(SCENES[scene_id])
    except KeyError as exc:
        available = ", ".join(sorted(SCENES))
        raise ConfigurationError(f"Unknown scene '{scene_id}'. Available: {available}") from exc
    scene["id"] = scene_id
    return scene


def list_scenes() -> list[dict[str, object]]:
    return [
        {"id": key, "description": str(SCENES[key]["description"]), "object_count": len(SCENES[key]["objects"])}
        for key in sorted(SCENES)
    ]

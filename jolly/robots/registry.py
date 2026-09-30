from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from jolly.core.errors import ConfigurationError
from jolly.core.models import MODELS, RobotModel
from jolly.measurement import read_json, vector

MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
ARMS = {
    "so100": {"robot_type": "so100_follower", "kinematic_model": "so100"},
    "so101": {"robot_type": "so101_follower", "kinematic_model": "so101"},
    "koch": {"robot_type": "koch_follower", "kinematic_model": None},
    "jolly6": {"robot_type": None, "kinematic_model": "jolly6", "motor_names": list(MODELS["jolly6"].arm_joint_names)},
}


def configuration() -> dict[str, Any]:
    path = os.environ.get("JOLLY_ARM_CONFIG")
    cfg = read_json(path) if path else {}
    for key in ("arms", "kinematic_models"):
        if not isinstance(cfg.get(key, []), list) or any(not isinstance(item, dict) for item in cfg.get(key, [])):
            raise ConfigurationError(f"{key} must be a list of configuration objects.")
    return cfg


def configured_models() -> dict[str, RobotModel]:
    result = {}
    try:
        for spec in configuration().get("kinematic_models", []):
            path = Path(spec["urdf"]).resolve()
            if not path.is_file():
                raise ValueError(f"Missing URDF: {path}")
            joints = tuple(spec["joint_names"])
            if not joints or len(set(joints)) != len(joints) or not all(isinstance(j, str) and j for j in joints):
                raise ValueError("Unique joint_names are required")
            if not all(isinstance(spec[k], str) and spec[k] for k in ("id", "source", "license", "end_effector_link")):
                raise ValueError("Model ID, source, license and end effector must be nonempty strings")
            grippers = spec["gripper_joint_names"]
            if not isinstance(grippers, list) or not grippers or not all(isinstance(g, str) and g for g in grippers):
                raise ValueError("gripper_joint_names must be a nonempty list")
            result[spec["id"]] = RobotModel(
                id=spec["id"], name=spec.get("name", spec["id"]), urdf=str(path),
                arm_joint_names=joints, gripper_joint_names=tuple(spec["gripper_joint_names"]),
                end_effector_link=spec["end_effector_link"],
                home_degrees=tuple(vector(spec["home_degrees"], len(joints), "home_degrees")),
                description="User-configured kinematic model", source=spec["source"], license=spec["license"],
            )
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f"Invalid kinematic model configuration: {exc}") from exc
    return result


def arm_profile(arm: str) -> dict[str, Any]:
    profiles = {name: {"id": name, "motor_names": MOTORS, "gripper_motor": "gripper", **item}
                for name, item in ARMS.items()}
    try:
        for item in configuration().get("arms", []):
            spec = {"motor_names": MOTORS, "gripper_motor": "gripper", **item}
            if not isinstance(spec["id"], str) or not isinstance(spec["motor_names"], list):
                raise ValueError("Invalid arm ID or motor_names")
            names = spec["motor_names"] + [spec["gripper_motor"]]
            if len(set(names)) != len(names) or not all(isinstance(x, str) and x for x in names):
                raise ValueError("Unique motor names are required")
            if "mock" in str(spec.get("robot_type", "")).lower():
                raise ValueError("Mock robot types cannot be registered")
            profiles[spec["id"]] = spec
        profile = profiles[arm]
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"Unknown or malformed arm {arm}: {exc}") from exc
    model = profile.get("kinematic_model")
    if model is not None and model not in MODELS and model not in configured_models():
        raise ConfigurationError(f"Arm {arm} references an unregistered model: {model}")
    return {**profile, "reach_supported": model is not None, "physically_verified": False,
            "integration": "simulation-only" if arm == "jolly6" else "implemented-unverified"}


def list_arms() -> list[dict[str, Any]]:
    try:
        ids = set(ARMS) | {item["id"] for item in configuration().get("arms", [])}
    except (KeyError, TypeError) as exc:
        raise ConfigurationError("Each configured arm needs a string ID.") from exc
    return [arm_profile(name) for name in sorted(ids)]


def model_for_arm(arm: str) -> str:
    model = arm_profile(arm).get("kinematic_model")
    if model is None:
        raise ConfigurationError(f"Arm {arm} needs a matching configured URDF for Cartesian controls or simulation. Use joint controls on hardware.")
    return str(model)


def workspace_from(config: dict[str, Any]) -> list[list[float]]:
    bounds = config.get("workspace_meters")
    if not isinstance(bounds, list) or len(bounds) != 3:
        raise ConfigurationError("Hardware needs a measured workspace_meters: [[xmin,xmax],[ymin,ymax],[zmin,zmax]].")
    result = [vector(axis, 2, "workspace") for axis in bounds]
    if not all(low < high for low, high in result) or not result[1][0] < 0 < result[1][1]:
        raise ConfigurationError("Workspace bounds must increase and include both pickup and placement y bands.")
    if not result[2][0] <= 0.006 <= result[2][1] or not result[2][0] <= 0.05 <= result[2][1]:
        raise ConfigurationError("The workspace must contain the physical table and part positions.")
    return result

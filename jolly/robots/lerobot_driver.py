"""LeRobot 0.6 adapter. Real I/O only; no simulator fallback."""
from __future__ import annotations

import importlib
import math
import time
from pathlib import Path
from typing import Any

from jolly.core.errors import ConfigurationError, MotionError
from jolly.measurement import read_json, vector
from jolly.robots.registry import arm_profile, model_for_arm, workspace_from


class LeRobotDriver:
    def __init__(self, arm: str, config_path: str):
        self.emergency_stop_attempted = False
        self.profile = arm_profile(arm)
        self.config = read_json(config_path)
        if self.config.get("arm") != arm or self.config.get("use_degrees") is not True:
            raise ConfigurationError("Hardware config needs matching arm and use_degrees=true.")
        self.workspace = workspace_from(self.config)
        self.gripper_endpoints = vector(self.config.get("gripper_open_closed"), 2, "gripper_open_closed")
        if (not all(0 <= v <= 100 for v in self.gripper_endpoints)
                or abs(self.gripper_endpoints[0] - self.gripper_endpoints[1]) < 10):
            raise ConfigurationError("Measured LeRobot gripper open/closed endpoints must be distinct and within 0..100.")
        self.names = self.profile["motor_names"]
        self.mapping = self.config.get("joint_mapping")
        if not isinstance(self.mapping, dict) or set(self.mapping) != set(self.names):
            raise ConfigurationError("Explicit measured joint_mapping for every motor is required.")
        for name in self.names:
            item = self.mapping[name]
            try:
                values = vector([item["sign"], item["offset_degrees"]], 2, name)
                if values[0] not in (-1, 1):
                    raise ValueError("sign must be -1 or 1")
                limits = vector(item["limits_degrees"], 2, name)
                if limits[0] >= limits[1]:
                    raise ValueError("limits must increase")
            except (KeyError, ValueError, TypeError) as exc:
                raise ConfigurationError(f"Invalid joint mapping for {name}: {exc}") from exc
        try:
            from lerobot.robots.utils import make_robot_from_config
            robot_type = self.profile["robot_type"]
            if robot_type in ("so100_follower", "so101_follower"):
                module = importlib.import_module("lerobot.robots.so_follower.config_so_follower")
                cls = getattr(module, "SO100FollowerConfig" if robot_type == "so100_follower" else "SO101FollowerConfig")
            elif robot_type == "koch_follower":
                module = importlib.import_module("lerobot.robots.koch_follower.config_koch_follower")
                cls = module.KochFollowerConfig
            else:
                module = importlib.import_module(self.profile["config_module"])
                cls = getattr(module, self.profile["config_class"])
            config = cls(port=self.config["port"], id=self.config["id"],
                         calibration_dir=Path(self.config["calibration_dir"]), use_degrees=True,
                         max_relative_target=10.0, disable_torque_on_disconnect=False)
            self.robot = make_robot_from_config(config)
            if not self.robot.calibration:
                raise ConfigurationError("Run LeRobot calibration separately before connecting through Jolly.")
        except ImportError as exc:
            raise ConfigurationError("Install Jolly arms-feetech or arms-dynamixel extras on Python >=3.12.") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"Invalid LeRobot configuration: {exc}") from exc
        keys = {f"{n}.pos" for n in self.names + [self.profile["gripper_motor"]]}
        if not keys.issubset(self.robot.action_features) or not keys.issubset(self.robot.observation_features):
            raise ConfigurationError("LeRobot observation/action motor mapping does not match this arm.")

    def __enter__(self):
        try:
            self.robot.connect(calibrate=False)
            if not self.robot.is_calibrated:
                raise ConfigurationError("Motor calibration does not match the saved LeRobot calibration.")
        except Exception as exc:
            self._emergency_stop()
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(f"LeRobot connection failed: {exc}") from exc
        return self

    def __exit__(self, kind, value, traceback):
        if kind is not None:
            self._emergency_stop()
        elif self.robot.is_connected:
            try:
                self.robot.disconnect()  # Config keeps torque enabled to support the arm.
            except Exception:
                self._emergency_stop()
                raise

    def stop(self) -> None:
        try:
            self.robot.bus.disable_torque()
        finally:
            if self.robot.is_connected:
                self.robot.disconnect()

    def _emergency_stop(self) -> None:
        self.emergency_stop_attempted = True
        try:
            self.stop()
        except Exception:
            pass  # Preserve the original transport error; power cutoff may still be necessary.

    def state(self) -> dict[str, Any]:
        try:
            observation = self.robot.get_observation()
            joints = []
            for name in self.names:
                raw = float(observation[f"{name}.pos"])
                degrees = raw * self.mapping[name]["sign"] + self.mapping[name]["offset_degrees"]
                if not math.isfinite(degrees):
                    raise ValueError("Nonfinite motor observation")
                joints.append(degrees)
            opened, closed = self.gripper_endpoints
            gripper = (float(observation[f"{self.profile['gripper_motor']}.pos"]) - opened) / (closed - opened)
            if not math.isfinite(gripper) or not 0 <= gripper <= 1:
                raise ValueError("Invalid gripper observation")
            return {"ok": True, "backend": "hardware", "arm": self.profile["id"],
                    "joints_degrees": joints, "gripper": gripper,
                    "motor_observation": {k: observation[k] for k in self.robot.action_features},
                    "physically_verified": False}
        except Exception as exc:
            raise ConfigurationError(f"LeRobot motor read failed: {exc}") from exc

    def move(self, joints: list[float], gripper: float | None = None) -> dict[str, Any]:
        joints = vector(joints, len(self.names), "joints")
        before = self.state()
        if gripper is not None and (not math.isfinite(gripper) or not 0 <= gripper <= 1):
            raise MotionError("Gripper must be between 0 and 1.")
        if gripper is not None and abs(gripper - before["gripper"]) > 0.2:
            raise MotionError("Hardware gripper movement is limited to 0.2 per control.")
        action = {}
        for name, goal, start in zip(self.names, joints, before["joints_degrees"]):
            low, high = self.mapping[name]["limits_degrees"]
            if not low <= goal <= high or abs(goal - start) > 10:
                raise MotionError(f"{name} exceeds calibrated limits or the 10-degree control cap.")
            action[f"{name}.pos"] = (goal - self.mapping[name]["offset_degrees"]) / self.mapping[name]["sign"]
        opened, closed = self.gripper_endpoints
        action[f"{self.profile['gripper_motor']}.pos"] = opened + (closed - opened) * (before["gripper"] if gripper is None else gripper)
        try:
            applied = self.robot.send_action(action)
            time.sleep(0.25)
            measured = self.state()
            measured["applied_command"] = applied
            measured["torque_enabled"] = True
            return measured
        except Exception as exc:
            self._emergency_stop()
            raise MotionError(f"Hardware control failed; emergency stop attempted: {exc}") from exc

    def reach(self, x: float, y: float, z: float, gripper: float | None = None) -> dict[str, Any]:
        point = vector([x, y, z], 3, "reach")
        if not all(low <= value <= high for value, (low, high) in zip(point, self.workspace)):
            raise MotionError("Cartesian target is outside the calibrated hardware workspace.")
        from jolly.engine import JollyEngine
        from jolly.core.physics import p
        measured = self.state()
        with JollyEngine(model_for_arm(self.profile["id"]), "empty") as engine:
            for joint, value in zip(engine.arm_joints, measured["joints_degrees"]):
                p.resetJointState(engine.robot_id, joint.index, math.radians(value), physicsClientId=engine.client)
            # This computes joint targets only. Simulator object poses never score hardware.
            solved = engine.reach(*point, gripper=gripper)
            targets = [item["position_degrees"] for item in solved["joints"]]
        result = self.move(targets, gripper)
        result["ik_command"] = solved["ik"]
        return result

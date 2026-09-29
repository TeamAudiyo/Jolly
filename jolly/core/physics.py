from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

def _import_pybullet():
    """Import PyBullet without its unconditional native build-time banner."""
    try:
        output_fds = [sys.stdout.fileno(), sys.stderr.fileno()]
    except (AttributeError, OSError):
        output_fds = []
    if not output_fds or os.name == "nt":
        import pybullet

        return pybullet
    saved_fds = [os.dup(fd) for fd in output_fds]
    try:
        with open(os.devnull, "w", encoding="utf-8") as null:
            for fd in output_fds:
                os.dup2(null.fileno(), fd)
            import pybullet
    finally:
        for fd, saved_fd in zip(output_fds, saved_fds, strict=True):
            os.dup2(saved_fd, fd)
            os.close(saved_fd)
    return pybullet


p = _import_pybullet()

from jolly.core.errors import ConfigurationError, MotionError
from jolly.core.models import RobotModel, get_model, model_path
from jolly.core.scenes import get_scene


@dataclass(frozen=True)
class JointInfo:
    index: int
    q_index: int
    name: str
    link_name: str
    lower: float
    upper: float
    max_force: float
    max_velocity: float


class PhysicsEngine:
    """Own a PyBullet world and expose deterministic robot-arm operations."""

    timestep = 1.0 / 240.0

    def __init__(
        self,
        model: str = "jolly6",
        scene: str = "empty",
        *,
        gui: bool = False,
        realtime: bool = False,
    ) -> None:
        self.model: RobotModel = get_model(model)
        self.scene_id = scene
        self.gui = gui
        self.realtime = realtime
        self.client = p.connect(p.GUI if gui else p.DIRECT)
        if self.client < 0:
            raise RuntimeError("PyBullet could not create a physics client.")
        self.robot_id = -1
        self.plane_id = -1
        self.joints: dict[str, JointInfo] = {}
        self.arm_joints: list[JointInfo] = []
        self.gripper_joints: list[JointInfo] = []
        self.ik_solution_indexes: dict[int, int] = {}
        self.end_effector_index = -1
        self.object_ids: dict[str, int] = {}
        self.object_specs: dict[str, dict[str, object]] = {}
        self.held_object: str | None = None
        self.gripper = 0.0
        try:
            self._load_world()
        except Exception:
            p.disconnect(self.client)
            raise

    def __enter__(self) -> "PhysicsEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if p.isConnected(self.client):
            p.disconnect(self.client)

    def camera_rgb(
        self,
        *,
        width: int = 960,
        height: int = 640,
        yaw: float = 42.0,
        pitch: float = -28.0,
        distance: float = 0.85,
    ) -> tuple[int, int, bytes]:
        """Render the current physical world with PyBullet's local renderer."""
        view = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[0.12, 0.0, 0.16],
            distance=distance,
            yaw=yaw,
            pitch=pitch,
            roll=0.0,
            upAxisIndex=2,
        )
        projection = p.computeProjectionMatrixFOV(
            fov=48.0,
            aspect=width / height,
            nearVal=0.01,
            farVal=5.0,
        )
        result = p.getCameraImage(
            width,
            height,
            viewMatrix=view,
            projectionMatrix=projection,
            lightDirection=[-1.0, -0.6, 2.0],
            shadow=1,
            renderer=p.ER_TINY_RENDERER,
            physicsClientId=self.client,
        )
        rgba = result[2]
        raw = rgba.tobytes() if hasattr(rgba, "tobytes") else bytes(rgba)
        rgb = bytearray(width * height * 3)
        rgb[0::3] = raw[0::4]
        rgb[1::3] = raw[1::4]
        rgb[2::3] = raw[2::4]
        return width, height, bytes(rgb)

    def _load_world(self) -> None:
        p.resetSimulation(physicsClientId=self.client)
        p.setGravity(0, 0, -9.81, physicsClientId=self.client)
        p.setTimeStep(self.timestep, physicsClientId=self.client)
        p.setPhysicsEngineParameter(
            fixedTimeStep=self.timestep,
            numSolverIterations=100,
            deterministicOverlappingPairs=1,
            physicsClientId=self.client,
        )
        plane_shape = p.createCollisionShape(p.GEOM_PLANE, physicsClientId=self.client)
        self.plane_id = p.createMultiBody(0, plane_shape, physicsClientId=self.client)
        p.changeVisualShape(self.plane_id, -1, rgbaColor=[0.13, 0.15, 0.18, 1], physicsClientId=self.client)
        self.robot_id = p.loadURDF(
            str(model_path(self.model)),
            useFixedBase=True,
            flags=p.URDF_USE_SELF_COLLISION | p.URDF_USE_INERTIA_FROM_FILE,
            physicsClientId=self.client,
        )
        self._index_robot()
        self._load_scene()
        self.reset()

    def _index_robot(self) -> None:
        for index in range(p.getNumJoints(self.robot_id, physicsClientId=self.client)):
            raw = p.getJointInfo(self.robot_id, index, physicsClientId=self.client)
            info = JointInfo(
                index=index,
                q_index=int(raw[3]),
                name=raw[1].decode(),
                link_name=raw[12].decode(),
                lower=float(raw[8]),
                upper=float(raw[9]),
                max_force=float(raw[10]) or 25.0,
                max_velocity=float(raw[11]) or 2.0,
            )
            self.joints[info.name] = info
            if info.link_name == self.model.end_effector_link:
                self.end_effector_index = index
        try:
            self.arm_joints = [self.joints[name] for name in self.model.arm_joint_names]
            self.gripper_joints = [self.joints[name] for name in self.model.gripper_joint_names]
        except KeyError as exc:
            raise RuntimeError(f"Robot model is missing expected joint {exc.args[0]!r}.") from exc
        if self.end_effector_index < 0:
            raise RuntimeError(f"Robot model is missing end-effector link '{self.model.end_effector_link}'.")
        movable = sorted((info for info in self.joints.values() if info.q_index >= 0), key=lambda info: info.q_index)
        self.ik_solution_indexes = {info.index: offset for offset, info in enumerate(movable)}

    def _load_scene(self) -> None:
        scene = get_scene(self.scene_id)
        self.object_ids.clear()
        self.object_specs.clear()
        for raw_spec in scene["objects"]:
            spec = dict(raw_spec)
            half_extents = [float(value) / 2.0 for value in spec["size"]]
            collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents, physicsClientId=self.client)
            visual = p.createVisualShape(
                p.GEOM_BOX,
                halfExtents=half_extents,
                rgbaColor=spec["color"],
                physicsClientId=self.client,
            )
            body = p.createMultiBody(
                baseMass=float(spec["mass"]),
                baseCollisionShapeIndex=collision,
                baseVisualShapeIndex=visual,
                basePosition=spec["position"],
                physicsClientId=self.client,
            )
            name = str(spec["name"])
            self.object_ids[name] = body
            self.object_specs[name] = spec
            p.changeDynamics(body, -1, lateralFriction=0.8, restitution=0.05, physicsClientId=self.client)

    def reset(self) -> dict[str, object]:
        self.held_object = None
        self.gripper = 0.0
        for name, body in self.object_ids.items():
            spec = self.object_specs[name]
            p.resetBasePositionAndOrientation(
                body,
                spec["position"],
                [0, 0, 0, 1],
                physicsClientId=self.client,
            )
            p.resetBaseVelocity(body, [0, 0, 0], [0, 0, 0], physicsClientId=self.client)
        for info, degrees in zip(self.arm_joints, self.model.home_degrees, strict=True):
            p.resetJointState(self.robot_id, info.index, math.radians(degrees), physicsClientId=self.client)
        self._set_gripper_state(0.0)
        self._hold_current_pose()
        self._step(60)
        return self.state()

    def set_object_positions(self, positions: dict[str, list[float]]) -> dict[str, object]:
        """Apply a generated scene instance and make it the reset baseline."""
        specs = self.object_specs
        for name, position in positions.items():
            if name not in self.object_ids or name not in specs:
                raise ConfigurationError(f"Scene '{self.scene_id}' has no object named '{name}'.")
            if len(position) != 3 or not all(math.isfinite(float(value)) for value in position):
                raise ConfigurationError(f"Object '{name}' requires three finite coordinates.")
            normalized = [float(value) for value in position]
            body_id = self.object_ids[name]
            _, orientation = p.getBasePositionAndOrientation(body_id, physicsClientId=self.client)
            p.resetBasePositionAndOrientation(
                body_id, normalized, orientation, physicsClientId=self.client
            )
            p.resetBaseVelocity(
                body_id, linearVelocity=[0.0, 0.0, 0.0], angularVelocity=[0.0, 0.0, 0.0], physicsClientId=self.client
            )
            specs[name]["position"] = normalized
        return self.state()

    def restore(self, state: dict[str, object]) -> None:
        joints = state.get("joints", [])
        if isinstance(joints, list) and len(joints) == self.model.dof:
            for info, joint in zip(self.arm_joints, joints, strict=True):
                value = float(joint["position_degrees"] if isinstance(joint, dict) else joint)
                p.resetJointState(self.robot_id, info.index, math.radians(value), physicsClientId=self.client)
        self.gripper = float(state.get("gripper", 0.0))
        self._set_gripper_state(self.gripper)
        saved_objects = state.get("objects", [])
        if isinstance(saved_objects, list):
            for item in saved_objects:
                if not isinstance(item, dict) or item.get("name") not in self.object_ids:
                    continue
                p.resetBasePositionAndOrientation(
                    self.object_ids[str(item["name"])],
                    item.get("position", [0, 0, 0]),
                    item.get("orientation", [0, 0, 0, 1]),
                    physicsClientId=self.client,
                )
        held = state.get("held_object")
        self.held_object = str(held) if held in self.object_ids else None
        self._sync_held_object()
        self._hold_current_pose()
        p.performCollisionDetection(physicsClientId=self.client)

    def move_joints(
        self,
        degrees: Sequence[float],
        *,
        gripper: float | None = None,
        steps: int = 120,
        allow_collision: bool = False,
    ) -> dict[str, object]:
        if len(degrees) != self.model.dof:
            raise MotionError(f"Model '{self.model.id}' needs {self.model.dof} joint angles, received {len(degrees)}.")
        if not all(math.isfinite(float(value)) for value in degrees):
            raise MotionError("Joint angles must be finite numbers.")
        targets = [math.radians(float(value)) for value in degrees]
        for target, info in zip(targets, self.arm_joints, strict=True):
            if not info.lower <= target <= info.upper:
                raise MotionError(
                    f"Joint '{info.name}' target {math.degrees(target):.2f}° is outside "
                    f"[{math.degrees(info.lower):.2f}°, {math.degrees(info.upper):.2f}°]."
                )
        start = [p.getJointState(self.robot_id, info.index, physicsClientId=self.client)[0] for info in self.arm_joints]
        old_gripper = self.gripper
        old_held_object = self.held_object
        old_objects = self._object_poses()
        steps = max(1, min(int(steps), 2400))
        collision_detected = False
        for frame in range(1, steps + 1):
            blend = frame / steps
            values = [a + (b - a) * blend for a, b in zip(start, targets, strict=True)]
            for info, value in zip(self.arm_joints, values, strict=True):
                p.resetJointState(self.robot_id, info.index, value, physicsClientId=self.client)
            if gripper is not None:
                self._set_gripper_state(old_gripper + (float(gripper) - old_gripper) * blend)
            self._sync_held_object()
            p.performCollisionDetection(physicsClientId=self.client)
            if self.collisions()["collision"]:
                collision_detected = True
                if not allow_collision:
                    break
            if self.realtime:
                time.sleep(self.timestep)
        if collision_detected and not allow_collision:
            for info, value in zip(self.arm_joints, start, strict=True):
                p.resetJointState(self.robot_id, info.index, value, physicsClientId=self.client)
            self._set_gripper_state(old_gripper)
            self._restore_object_poses(old_objects)
            raise MotionError("Motion stopped because the robot collided. Use --allow-collision only for controlled tests.")
        if gripper is not None:
            self._set_gripper_state(float(gripper))
            self._update_grasp()
        self._hold_current_pose()
        self._step(8)
        self._clamp_arm_to_limits()
        final_collisions = self.collisions()
        if final_collisions["collision"] and not allow_collision:
            for info, value in zip(self.arm_joints, start, strict=True):
                p.resetJointState(self.robot_id, info.index, value, physicsClientId=self.client)
            self._set_gripper_state(old_gripper)
            self.held_object = old_held_object
            self._restore_object_poses(old_objects)
            self._hold_current_pose()
            raise MotionError("Motion rolled back because settling created a collision.")
        return self.state()

    def _clamp_arm_to_limits(self) -> None:
        for info in self.arm_joints:
            value = p.getJointState(self.robot_id, info.index, physicsClientId=self.client)[0]
            clamped = min(max(value, info.lower), info.upper)
            if clamped != value:
                p.resetJointState(self.robot_id, info.index, clamped, physicsClientId=self.client)
        self._hold_current_pose()

    def reach(
        self,
        x: float,
        y: float,
        z: float,
        *,
        gripper: float | None = None,
        steps: int = 160,
        allow_collision: bool = False,
        tolerance: float = 0.025,
    ) -> dict[str, object]:
        target = [float(x), float(y), float(z)]
        if not all(math.isfinite(value) for value in target):
            raise MotionError("Target coordinates must be finite numbers.")
        if z < 0.005 or math.sqrt(x * x + y * y + z * z) > 0.75:
            raise MotionError("Target is outside the simulator safety workspace.")
        solution = p.calculateInverseKinematics(
            self.robot_id,
            self.end_effector_index,
            target,
            maxNumIterations=300,
            residualThreshold=1e-5,
            physicsClientId=self.client,
        )
        degrees: list[float] = []
        for info in self.arm_joints:
            solution_index = self.ik_solution_indexes.get(info.index, -1)
            if solution_index < 0 or solution_index >= len(solution):
                raise MotionError(f"IK did not return a value for joint '{info.name}'.")
            radians = min(max(float(solution[solution_index]), info.lower), info.upper)
            degrees.append(math.degrees(radians))
        result = self.move_joints(degrees, gripper=gripper, steps=steps, allow_collision=allow_collision)
        actual = result["end_effector"]["position"]
        error = math.dist(actual, target)
        result["ik"] = {"target": target, "error_meters": round(error, 6), "within_tolerance": error <= tolerance}
        if error > tolerance:
            raise MotionError(f"IK target was not reachable within {tolerance:.3f} m; residual error is {error:.3f} m.")
        return result

    def _set_gripper_state(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise MotionError("Gripper must be between 0.0 (open) and 1.0 (closed).")
        self.gripper = float(value)
        for info in self.gripper_joints:
            target = info.upper - self.gripper * (info.upper - info.lower)
            p.resetJointState(self.robot_id, info.index, target, physicsClientId=self.client)

    def _hold_current_pose(self) -> None:
        for info in [*self.arm_joints, *self.gripper_joints]:
            target = p.getJointState(self.robot_id, info.index, physicsClientId=self.client)[0]
            p.setJointMotorControl2(
                self.robot_id,
                info.index,
                p.POSITION_CONTROL,
                targetPosition=target,
                force=max(info.max_force, 10.0),
                maxVelocity=max(info.max_velocity, 0.2),
                physicsClientId=self.client,
            )

    def _update_grasp(self) -> None:
        if self.gripper <= 0.25:
            if self.held_object and self.held_object in self.object_ids:
                body = self.object_ids[self.held_object]
                position, orientation = p.getBasePositionAndOrientation(body, physicsClientId=self.client)
                released_position = [position[0], position[1], max(0.02, position[2] - 0.025)]
                p.resetBasePositionAndOrientation(
                    body,
                    released_position,
                    orientation,
                    physicsClientId=self.client,
                )
            self.held_object = None
            return
        if self.gripper < 0.75 or self.held_object is not None:
            return
        ee = self.end_effector_position()
        candidates: list[tuple[float, str]] = []
        for name, body in self.object_ids.items():
            if not self.object_specs[name].get("graspable"):
                continue
            position, _ = p.getBasePositionAndOrientation(body, physicsClientId=self.client)
            candidates.append((math.dist(ee, position), name))
        if candidates:
            distance, name = min(candidates)
            if distance <= 0.10:
                self.held_object = name
                self._sync_held_object()

    def _sync_held_object(self) -> None:
        if self.held_object is None or self.held_object not in self.object_ids:
            return
        position = self.end_effector_position()
        held_position = [position[0], position[1], max(0.02, position[2] - 0.045)]
        p.resetBasePositionAndOrientation(
            self.object_ids[self.held_object], held_position, [0, 0, 0, 1], physicsClientId=self.client
        )

    def _step(self, count: int) -> None:
        for _ in range(count):
            self._sync_held_object()
            p.stepSimulation(physicsClientId=self.client)
            if self.realtime:
                time.sleep(self.timestep)

    def end_effector_position(self) -> list[float]:
        state = p.getLinkState(
            self.robot_id,
            self.end_effector_index,
            computeForwardKinematics=True,
            physicsClientId=self.client,
        )
        return [float(value) for value in state[4]]

    def forward_kinematics(self, degrees: Sequence[float] | None = None) -> dict[str, object]:
        if degrees is not None:
            if len(degrees) != self.model.dof:
                raise MotionError(f"Forward kinematics needs {self.model.dof} joint angles.")
            previous = [p.getJointState(self.robot_id, j.index, physicsClientId=self.client)[0] for j in self.arm_joints]
            for info, value in zip(self.arm_joints, degrees, strict=True):
                p.resetJointState(self.robot_id, info.index, math.radians(float(value)), physicsClientId=self.client)
        else:
            previous = []
        link = p.getLinkState(
            self.robot_id,
            self.end_effector_index,
            computeForwardKinematics=True,
            physicsClientId=self.client,
        )
        if previous:
            for info, value in zip(self.arm_joints, previous, strict=True):
                p.resetJointState(self.robot_id, info.index, value, physicsClientId=self.client)
        quaternion = [float(value) for value in link[5]]
        return {
            "position": [round(float(value), 6) for value in link[4]],
            "orientation_quaternion": [round(value, 6) for value in quaternion],
            "orientation_euler_degrees": [round(math.degrees(value), 4) for value in p.getEulerFromQuaternion(quaternion)],
        }

    def collisions(self) -> dict[str, object]:
        p.performCollisionDetection(physicsClientId=self.client)
        details: list[dict[str, object]] = []
        names_by_body = {body: name for name, body in self.object_ids.items()}
        contacts = p.getContactPoints(bodyA=self.robot_id, physicsClientId=self.client)
        for contact in contacts:
            body_b = int(contact[2])
            link_a = int(contact[3])
            link_b = int(contact[4])
            if self.held_object and body_b == self.object_ids.get(self.held_object):
                continue
            if body_b == self.plane_id and link_a == -1:
                continue
            if body_b == self.robot_id and abs(link_a - link_b) <= 1:
                continue
            details.append(
                {
                    "type": "self" if body_b == self.robot_id else "environment",
                    "robot_link": self._link_name(link_a),
                    "other": self._link_name(link_b) if body_b == self.robot_id else names_by_body.get(body_b, "floor"),
                    "distance": round(float(contact[8]), 6),
                    "normal_force": round(float(contact[9]), 6),
                }
            )
        if self.held_object and self.held_object in self.object_ids:
            held_body = self.object_ids[self.held_object]
            for contact in p.getContactPoints(bodyA=held_body, physicsClientId=self.client):
                body_b = int(contact[2])
                if body_b in (self.robot_id, held_body):
                    continue
                details.append(
                    {
                        "type": "held_object_environment",
                        "robot_link": self.model.end_effector_link,
                        "other": names_by_body.get(body_b, "floor"),
                        "distance": round(float(contact[8]), 6),
                        "normal_force": round(float(contact[9]), 6),
                    }
                )
        return {"collision": bool(details), "count": len(details), "contacts": details}

    def _link_name(self, index: int) -> str:
        if index == -1:
            return "base_link"
        raw = p.getJointInfo(self.robot_id, index, physicsClientId=self.client)
        return raw[12].decode()

    def _object_poses(self) -> dict[str, tuple[Sequence[float], Sequence[float]]]:
        return {
            name: p.getBasePositionAndOrientation(body, physicsClientId=self.client)
            for name, body in self.object_ids.items()
        }

    def _restore_object_poses(self, poses: dict[str, tuple[Sequence[float], Sequence[float]]]) -> None:
        for name, (position, orientation) in poses.items():
            p.resetBasePositionAndOrientation(
                self.object_ids[name], position, orientation, physicsClientId=self.client
            )

    def state(self) -> dict[str, object]:
        joint_states = []
        for info in self.arm_joints:
            raw = p.getJointState(self.robot_id, info.index, physicsClientId=self.client)
            joint_states.append(
                {
                    "name": info.name,
                    "position_degrees": round(math.degrees(float(raw[0])), 5),
                    "velocity_degrees_per_second": round(math.degrees(float(raw[1])), 5),
                    "limits_degrees": [round(math.degrees(info.lower), 4), round(math.degrees(info.upper), 4)],
                }
            )
        objects = []
        for name, body in self.object_ids.items():
            position, orientation = p.getBasePositionAndOrientation(body, physicsClientId=self.client)
            objects.append(
                {
                    "name": name,
                    "position": [round(float(value), 6) for value in position],
                    "orientation": [round(float(value), 6) for value in orientation],
                    "graspable": bool(self.object_specs[name].get("graspable")),
                }
            )
        return {
            "ok": True,
            "model": {"id": self.model.id, "name": self.model.name, "dof": self.model.dof},
            "scene": self.scene_id,
            "joints": joint_states,
            "gripper": round(self.gripper, 4),
            "end_effector": self.forward_kinematics(),
            "collisions": self.collisions(),
            "held_object": self.held_object,
            "objects": objects,
        }

    def joint_positions(self) -> list[list[float]]:
        points = [[0.0, 0.0, 0.0]]
        for info in self.arm_joints:
            state = p.getLinkState(self.robot_id, info.index, computeForwardKinematics=True, physicsClientId=self.client)
            points.append([round(float(value), 6) for value in state[4]])
        points.append([round(value, 6) for value in self.end_effector_position()])
        return points

    def run_viewer(self) -> None:
        if not self.gui:
            raise RuntimeError("Viewer requires gui=True.")
        p.resetDebugVisualizerCamera(0.9, 40, -28, [0.18, 0, 0.14], physicsClientId=self.client)
        while p.isConnected(self.client):
            self._step(1)

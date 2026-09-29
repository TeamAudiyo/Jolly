import math

import pytest

from jolly.core.errors import MotionError
from jolly.core.physics import PhysicsEngine


@pytest.mark.parametrize(("model", "dof"), [("jolly6", 6), ("so101", 5)])
def test_models_load_and_export_state(model: str, dof: int) -> None:
    with PhysicsEngine(model=model) as engine:
        state = engine.state()
        assert state["ok"] is True
        assert state["model"]["dof"] == dof
        assert len(state["joints"]) == dof
        assert len(state["end_effector"]["position"]) == 3
        assert all(math.isfinite(value) for value in state["end_effector"]["position"])


def test_forward_kinematics_does_not_change_pose() -> None:
    with PhysicsEngine() as engine:
        before = engine.state()["joints"]
        result = engine.forward_kinematics([0, -10, 40, -30, 15, 20])
        after = engine.state()["joints"]
        assert len(result["position"]) == 3
        assert [joint["position_degrees"] for joint in before] == [
            joint["position_degrees"] for joint in after
        ]


def test_joint_limit_violation_is_rejected() -> None:
    with PhysicsEngine() as engine:
        with pytest.raises(MotionError, match="outside"):
            engine.move_joints([999, 0, 0, 0, 0, 0])


def test_scenes_create_objects() -> None:
    with PhysicsEngine(scene="blocks") as engine:
        state = engine.state()
        assert {item["name"] for item in state["objects"]} >= {"red_block", "left_target"}


def test_grasp_helper_tracks_nearby_object() -> None:
    with PhysicsEngine(scene="blocks") as engine:
        engine.reach(0.30, -0.16, 0.10, gripper=0.0)
        state = engine.reach(0.30, -0.16, 0.10, gripper=1.0)
        assert state["held_object"] == "red_block"
        assert state["collisions"]["collision"] is False
        released = engine.reach(0.30, -0.16, 0.15, gripper=0.0)
        assert released["held_object"] is None
        assert released["collisions"]["collision"] is False


def test_carried_object_floor_collision_rolls_back() -> None:
    with PhysicsEngine(scene="blocks") as engine:
        engine.reach(0.30, -0.16, 0.10, gripper=0.0)
        grasped = engine.reach(0.30, -0.16, 0.10, gripper=1.0)
        safe_position = grasped["end_effector"]["position"]
        with pytest.raises(MotionError, match="collision"):
            engine.reach(0.30, -0.16, 0.04, gripper=1.0)
        assert engine.state()["end_effector"]["position"] == pytest.approx(safe_position, abs=1e-4)


def test_non_finite_inputs_rejected_clearly() -> None:
    with PhysicsEngine() as engine:
        with pytest.raises(MotionError, match="finite"):
            engine.reach(float("nan"), 0.0, 0.2)
        with pytest.raises(MotionError, match="finite"):
            engine.move_joints([float("nan"), 0, 0, 0, 0, 0])


def test_allow_collision_motion_stays_within_joint_limits() -> None:
    with PhysicsEngine() as engine:
        state = engine.move_joints([0, 120, 120, 0, 0, 0], allow_collision=True)
        for joint in state["joints"]:
            low, high = joint["limits_degrees"]
            assert low <= joint["position_degrees"] <= high

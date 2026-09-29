from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path

from jolly.core.errors import ConfigurationError


@dataclass(frozen=True)
class RobotModel:
    id: str
    name: str
    urdf: str
    arm_joint_names: tuple[str, ...]
    gripper_joint_names: tuple[str, ...]
    end_effector_link: str
    home_degrees: tuple[float, ...]
    description: str
    source: str
    license: str

    @property
    def dof(self) -> int:
        return len(self.arm_joint_names)

    def export(self) -> dict[str, object]:
        data = asdict(self)
        data["dof"] = self.dof
        return data


MODELS: dict[str, RobotModel] = {
    "jolly6": RobotModel(
        id="jolly6",
        name="Jolly-6",
        urdf="jolly6.urdf",
        arm_joint_names=(
            "base_yaw",
            "shoulder_pitch",
            "elbow_pitch",
            "wrist_pitch",
            "wrist_yaw",
            "wrist_roll",
        ),
        gripper_joint_names=("left_finger", "right_finger"),
        end_effector_link="tool_link",
        home_degrees=(0.0, -25.0, 70.0, -45.0, 0.0, 0.0),
        description="Original six-axis educational arm with a parallel gripper.",
        source="Bundled with Jolly",
        license="MIT OR Apache-2.0",
    ),
    "so101": RobotModel(
        id="so101",
        name="SO-101 simplified simulation profile",
        urdf="so101.urdf",
        arm_joint_names=(
            "shoulder_pan",
            "shoulder_lift",
            "elbow_flex",
            "wrist_flex",
            "wrist_roll",
        ),
        gripper_joint_names=("gripper",),
        end_effector_link="tool_link",
        home_degrees=(0.0, 0.0, 0.0, 0.0, 0.0),
        description="Lightweight collision model that follows the open SO-101 five-axis kinematic layout.",
        source="Derived from TheRobotStudio/SO-ARM100 SO-101 URDF metadata",
        license="Apache-2.0",
    ),
}


def get_model(model_id: str) -> RobotModel:
    try:
        return MODELS[model_id]
    except KeyError as exc:
        available = ", ".join(sorted(MODELS))
        raise ConfigurationError(f"Unknown robot model '{model_id}'. Available: {available}") from exc


def model_path(model: RobotModel) -> Path:
    return Path(str(files("jolly").joinpath("assets", model.urdf)))


def list_models() -> list[dict[str, object]]:
    return [MODELS[key].export() for key in sorted(MODELS)]

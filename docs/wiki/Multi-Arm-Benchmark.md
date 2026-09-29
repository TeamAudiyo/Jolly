# Multi-Arm Benchmark

## Explicit controls and measured results

Start plans randomized part/pad layouts. Place physical objects at those coordinates
when using hardware. Start and next send no robot motion. The operator enters
approach, descent, grasp, lift, carry, lower, and release controls.

Score measures XY object-to-pad center distance in meters. Simulation reads
PyBullet body transforms after five seconds of settling. Success requires grasp,
release, correct support height, real pad contact, stability, collision-free motion,
placement tolerance, and command/time budgets. Grasp uses Jolly's constrained-grasp
helper, not a physical finger-contact model.

`success_percentage = 100 * successful_trials / completed_trials`.
A partial report includes `complete: false`. Before scoring, no number exists.
Scores are immutable and idempotent. Controls after scoring are rejected until next.
Reset and scene replacement archive prior sessions, including controls and results.
Old 0.5 benchmark state requires a new start.

## LeRobot configuration

Use Python 3.12 or later. Install `jolly-cli[arms-feetech]` for SO arms or
`jolly-cli[arms-dynamixel]` for Koch. See the README for the NumPy 2 / PyBullet
source-build requirement on platforms with incompatible wheels.

Calibrate through LeRobot before Jolly connects. The following structure is a
configuration template, not physical calibration. Replace all limits, signs,
offsets, gripper endpoints, and workspace bounds with measurements for your arm.
Jolly does not certify the template as safe.

```json
{
  "arm": "so101",
  "port": "/dev/ttyACM0",
  "id": "my-follower",
  "calibration_dir": "/absolute/path/to/lerobot/calibration",
  "use_degrees": true,
  "workspace_meters": [[0.27, 0.33], [-0.17, 0.17], [0, 0.36]],
  "gripper_open_closed": [0, 100],
  "joint_mapping": {
    "shoulder_pan": {"sign": 1, "offset_degrees": 0, "limits_degrees": [-90, 90]},
    "shoulder_lift": {"sign": 1, "offset_degrees": 0, "limits_degrees": [-90, 90]},
    "elbow_flex": {"sign": 1, "offset_degrees": 0, "limits_degrees": [-90, 90]},
    "wrist_flex": {"sign": 1, "offset_degrees": 0, "limits_degrees": [-90, 90]},
    "wrist_roll": {"sign": 1, "offset_degrees": 0, "limits_degrees": [-90, 90]}
  }
}
```

`Jolly degrees = observed LeRobot degrees * sign + offset_degrees`.
The gripper uses LeRobot's 0–100 scale and measured open/closed endpoints.
`send_action` returns an applied command, not feedback. Jolly reads feedback
with `get_observation`. Motor feedback never measures object placement.
Joint moves have a 10-degree per-command cap. Gripper moves have a 0.2 cap.
Cartesian reach also requires a matching URDF and calibrated workspace.

Connection can configure motors and requires `--confirm-hardware`, including state.
Successful disconnect keeps torque enabled. Failures attempt torque disable.
Support the arm before stop. Use a physical power cutoff when transport fails.
Sensor/transport failures during a control preserve attempted inputs and abort
the trial without a numeric score. Restart after safe recovery.

## Tracker contract

Measurement config:

```json
{"provider": "tracker", "document": "/absolute/path/to/live-sensor.json", "max_age_seconds": 2}
```

The real tracker writes an atomic JSON document. Do not create outcome fixtures
and present those fixtures as physical benchmark results. Required fields:

- `trial_id`: session seed, colon, one-based trial index, such as `123:1`.
- `frame`: `robot-base`; `units`: `meters`.
- `objects`: mapping containing `part` and the active generated `place_slot_N`.
- Each object: `position_meters`, `dimensions` (2 or 3), timezone-aware `measured_at`.
- `evidence`: boolean sensor assertions, not motor-derived claims.

Sensor evidence keys:

| Key | Meaning |
| --- | --- |
| `grasped_during_trial` | Sensor observed a grasp during this trial. |
| `released` | Object is released at scoring. |
| `collision_free_during_trial` | Sensor monitored the whole trial without collision. |
| `on_pad` | Sensor confirms object support on the specified pad. |
| `stable` | Sensor confirms stable placement at scoring. |

Controls retain sensor evidence. Grasp requires evidence recorded during controls.
Every control and final measurement must confirm trial-wide collision freedom.
A final assertion cannot erase an earlier recorded collision.
Missing evidence is unknown and cannot produce success. Coordinates must be
finite, fresh, and trial-specific. Moved pads fail the generated-target check.
Planar-only coordinates omit 3D distance and label `verification_scope: planar-only`.
No provider emits a numeric score from commands, IK, or motor positions.

## Calibrated marker pose

Install `jolly-cli[markers]`. Config fields:

- `provider`: `marker-pose`; `camera`: OpenCV capture device or URL.
- `camera_matrix`: calibrated 3×3 intrinsics.
- `distortion_coefficients`: calibrated OpenCV coefficients.
- `camera_to_robot_base`: calibrated rigid 4×4 transform.
- `markers`: mapping for `part` and each required `place_slot_N`.
- Each marker: `id` in ArUco DICT_4X4_50, `size_meters`, `marker_to_object_meters`.
- `max_reprojection_error_pixels`: positive finite limit, default 2.
- Optional `evidence_config`: tracker config path for independent trial-wide evidence.

Jolly uses measured square-marker pose, calibrated rotation/translation, and
marker-to-object offset. It does not use homography-derived or assumed height.
A single image cannot prove trial-wide grasp or collision history. Camera-only
scoring reports measured error but cannot claim a successful verified trial.
No camera or physical tracker was available for release verification.

## Additional arms and kinematic models

Set `JOLLY_ARM_CONFIG` to an absolute JSON path. Register `arms` and
`kinematic_models` lists. An arm contains `id`, `robot_type`, `motor_names`,
`gripper_motor`, and `kinematic_model`. Additional robot types require
`config_module` and `config_class` for a compatible LeRobot config factory.
The config class must accept port, id, calibration_dir, use_degrees,
max_relative_target, and disable_torque_on_disconnect.

A kinematic model contains `id`, existing absolute `urdf`, `joint_names`,
`gripper_joint_names`, `end_effector_link`, `home_degrees`, `source`, and `license`.
Register only a model that matches the physical arm and calibrated motor mapping.
Mock robot types are rejected. No arm receives another arm's model implicitly.

Koch v1.1 has no upstream URDF. Koch hardware joint controls work through the
implemented adapter. Koch simulation and Cartesian controls require a matching
configured model. The different Koch v1.0 model is not bundled or substituted.

All physical integrations are implemented but physically unverified.

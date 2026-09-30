"""Measured object poses, never commanded or kinematic object estimates."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jolly.core.errors import ConfigurationError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"Cannot read configuration {path}: {exc}") from exc


def vector(value: Any, length: int, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != length:
        raise ConfigurationError(f"{label} must contain {length} finite numbers.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ConfigurationError(f"{label} must contain finite numbers, not strings or booleans.")
    try:
        result = [float(v) for v in value]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f"{label} must contain finite numbers.") from exc
    if not all(math.isfinite(v) for v in result):
        raise ConfigurationError(f"{label} must contain finite numbers.")
    return result


def measure_simulation(engine: Any, names: list[str]) -> dict[str, Any]:
    # Read Bullet directly. UI state rounds coordinates and is not the scoring source.
    from jolly.core.physics import p
    timestamp = utc_now()
    result = {}
    for name in names:
        if name not in engine.object_ids:
            raise ConfigurationError(f"Missing measured simulation object: {name}")
        pos, orientation = p.getBasePositionAndOrientation(
            engine.object_ids[name], physicsClientId=engine.client
        )
        result[name] = {
            "position_meters": list(pos), "orientation_quaternion": list(orientation),
            "measured_at": timestamp, "source": "pybullet-world-transform",
            "dimensions": 3, "frame": "robot-base", "units": "meters",
        }
    return result


def hardware_provider(config_path: str | None) -> dict[str, Any]:
    if not config_path:
        raise ConfigurationError(
            "Verified placement scoring requires an object measurement provider. "
            "Commanded coordinates and motor positions are not object measurements. "
            "Use --measurement-config."
        )
    cfg = read_json(config_path)
    if cfg.get("provider") not in ("tracker", "marker-pose"):
        raise ConfigurationError("Measurement provider must be tracker or marker-pose.")
    return cfg


def measure_hardware(config_path: str, names: list[str], *, trial_id: str, not_before: str | None = None) -> dict[str, Any]:
    cfg = hardware_provider(config_path)
    if cfg["provider"] == "marker-pose":
        return _camera_measurements(cfg, names, trial_id, not_before)
    document = read_json(str(cfg.get("document", "")))
    if document.get("trial_id") != trial_id:
        raise ConfigurationError("Tracker trial_id does not match the active trial.")
    if document.get("frame") != "robot-base" or document.get("units") != "meters":
        raise ConfigurationError("Tracker coordinates require frame=robot-base and units=meters.")
    if not isinstance(document.get("objects"), dict):
        raise ConfigurationError("Tracker document needs objects.")
    result = {}
    for name in names:
        item = document["objects"].get(name)
        if not isinstance(item, dict):
            raise ConfigurationError(f"Missing measured object {name}.")
        dimensions = item.get("dimensions", 3)
        if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions not in (2, 3):
            raise ConfigurationError("Measurement dimensions must be 2 or 3.")
        position = vector(item.get("position_meters"), dimensions, name)
        try:
            stamp = datetime.fromisoformat(item["measured_at"])
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if not_before and stamp < datetime.fromisoformat(not_before):
                raise ConfigurationError("Measurement predates the active trial.")
            max_age = vector([cfg.get("max_age_seconds", 2)], 1, "max_age_seconds")[0]
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise ConfigurationError("Measurement timestamp must include UTC offset.") from exc
        if not math.isfinite(max_age) or not 0 < max_age <= 30 or not 0 <= age <= max_age:
            raise ConfigurationError(f"Missing, future, or stale measurement for {name}.")
        result[name] = {**item, "position_meters": position, "dimensions": dimensions,
                        "source": "tracker", "frame": "robot-base", "units": "meters"}
    # Evidence is supplied by the same measured source, not by the motor command.
    evidence = document.get("evidence", {})
    if not isinstance(evidence, dict) or any(not isinstance(v, bool) for v in evidence.values()):
        raise ConfigurationError("Tracker evidence must map sensor check names to booleans.")
    result["evidence"] = evidence
    return result


def _camera_measurements(cfg: dict[str, Any], names: list[str], trial_id: str, not_before: str | None = None) -> dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ConfigurationError("Install camera measurement support: pip install 'jolly-cli[markers]'") from exc
    try:
        matrix = np.asarray(cfg["camera_matrix"], dtype=float).reshape(3, 3)
        distortion = np.asarray(cfg["distortion_coefficients"], dtype=float)
        transform = np.asarray(cfg["camera_to_robot_base"], dtype=float).reshape(4, 4)
        if (not np.isfinite(matrix).all() or not np.isfinite(distortion).all()
                or not np.isfinite(transform).all() or matrix[0, 0] <= 0 or matrix[1, 1] <= 0
                or not np.allclose(transform[3], [0, 0, 0, 1])
                or not np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3), atol=1e-5)
                or np.linalg.det(transform[:3, :3]) < 0.99):
            raise ValueError("Invalid measured camera calibration")
        markers = cfg["markers"]
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(dictionary)
        capture = cv2.VideoCapture(cfg.get("camera", 0))
        try:
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok:
            raise ValueError("Camera did not return a frame")
        corners, ids, _ = detector.detectMarkers(frame)
        found = {} if ids is None else {int(i): c for i, c in zip(ids.flatten(), corners)}
        result = {}
        for name in names:
            marker = markers[name]
            size = vector([marker["size_meters"]], 1, "size_meters")[0]
            if not math.isfinite(size) or size <= 0:
                raise ValueError("Invalid marker size")
            half = size / 2
            points = np.asarray([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], dtype=float)
            detected = found[int(marker["id"])]
            ok, rvec, tvec = cv2.solvePnP(points, detected.reshape(4, 2), matrix, distortion,
                                          flags=cv2.SOLVEPNP_IPPE_SQUARE)
            if not ok or tvec[2, 0] <= 0:
                raise ValueError("Marker pose could not be measured")
            projected, _ = cv2.projectPoints(points, rvec, tvec, matrix, distortion)
            error = float(np.sqrt(np.mean((projected.reshape(4, 2) - detected.reshape(4, 2)) ** 2)))
            tolerance = vector([cfg.get("max_reprojection_error_pixels", 2)], 1, "max_reprojection_error_pixels")[0]
            if not math.isfinite(tolerance) or tolerance <= 0 or not math.isfinite(error) or error > tolerance:
                raise ValueError("Marker reprojection error exceeds calibration tolerance")
            rotation, _ = cv2.Rodrigues(rvec)
            offset = np.asarray(vector(marker["marker_to_object_meters"], 3, name), dtype=float)
            position = transform[:3, :3] @ (tvec.flatten() + rotation @ offset) + transform[:3, 3]
            result[name] = {"position_meters": vector(position.tolist(), 3, name), "dimensions": 3,
                            "source": "camera-marker-pose", "measured_at": utc_now(),
                            "frame": "robot-base", "units": "meters", "reprojection_error_pixels": error}
        # Single camera frame cannot certify an entire grasp/collision history.
        # Hardware benchmark controls collect this evidence from a tracker.
        result["evidence"] = {}
        if cfg.get("evidence_config"):
            evidence_cfg = hardware_provider(cfg["evidence_config"])
            if evidence_cfg["provider"] != "tracker":
                raise ValueError("Camera evidence_config must reference a tracker provider")
            evidence = measure_hardware(cfg["evidence_config"], names, trial_id=trial_id, not_before=not_before)
            result["evidence"] = evidence["evidence"]
        return result
    except (KeyError, ValueError, TypeError, OverflowError, AttributeError, cv2.error) as exc:
        raise ConfigurationError(f"Camera measurement unavailable: {exc}") from exc

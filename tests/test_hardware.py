from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from jolly.cli import main
from jolly.core.errors import ConfigurationError, MotionError
from jolly.hardware.so101 import SO101Calibration, decode_status, encode_packet


def calibration_data() -> dict[str, object]:
    motors = {
        name: {"id": index, "zero_raw": 2048, "direction": 1, "raw_per_degree": 4096 / 360}
        for index, name in enumerate(
            ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"), start=1
        )
    }
    motors["gripper"] = {"id": 6, "open_raw": 1900, "closed_raw": 3000}
    return {"calibrated": True, "motors": motors}


def test_sts3215_packet_codec_uses_real_protocol_checksum() -> None:
    packet = encode_packet(1, 2, bytes((56, 2)))
    assert packet == bytes((0xFF, 0xFF, 1, 4, 2, 56, 2, 190))
    status_without_checksum = bytes((0xFF, 0xFF, 1, 4, 0, 0x34, 0x12))
    checksum = (~sum(status_without_checksum[2:])) & 0xFF
    assert decode_status(status_without_checksum + bytes((checksum,))) == (1, 0, bytes((0x34, 0x12)))
    with pytest.raises(MotionError, match="checksum"):
        decode_status(status_without_checksum + b"\0")


def test_physical_calibration_converts_joint_and_gripper_values(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration_data()), encoding="utf-8")
    calibration = SO101Calibration.load(path)
    shoulder = calibration.motors["shoulder_pan"]
    raw = shoulder.degrees_to_raw(30.0)
    assert shoulder.raw_to_degrees(raw) == pytest.approx(30.0, abs=0.1)
    assert calibration.gripper.value_to_raw(0.0) == 1900
    assert calibration.gripper.value_to_raw(1.0) == 3000


def test_physical_calibration_rejects_duplicate_motor_ids(tmp_path) -> None:
    data = calibration_data()
    data["motors"]["wrist_roll"]["id"] = 1
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="unique ID"):
        SO101Calibration.load(path)


def test_physical_calibration_rejects_broadcast_id_and_unsafe_scale(tmp_path) -> None:
    data = calibration_data()
    data["motors"]["shoulder_pan"]["id"] = 0
    data["motors"]["shoulder_lift"]["raw_per_degree"] = 100
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="between 1 and 253"):
        SO101Calibration.load(path)


def test_hardware_motion_requires_explicit_confirmation(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration_data()), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        [
            "hardware",
            "benchmark",
            "--port",
            "/dev/does-not-open",
            "--calibration",
            str(path),
            "--json",
        ],
    )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "--confirm-hardware" in payload["error"]["message"]


def test_cli_writes_loadable_physical_calibration_template(tmp_path) -> None:
    path = tmp_path / "calibration.json"
    result = CliRunner().invoke(main, ["hardware", "calibration-example", "--output", str(path)])
    assert result.exit_code == 0, result.output
    template = json.loads(path.read_text(encoding="utf-8"))
    assert template["calibrated"] is False
    with pytest.raises(ConfigurationError, match="calibrated"):
        SO101Calibration.load(path)
    template["calibrated"] = True
    path.write_text(json.dumps(template), encoding="utf-8")
    calibration = SO101Calibration.load(path)
    assert [calibration.motors[name].motor_id for name in calibration.motors] == [1, 2, 3, 4, 5]
    assert calibration.gripper.motor_id == 6


def test_unopenable_physical_serial_port_returns_json_error(tmp_path) -> None:
    pytest.importorskip("serial")
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration_data()), encoding="utf-8")
    result = CliRunner().invoke(
        main,
        ["hardware", "state", "--port", "/dev/jolly-port-does-not-exist", "--calibration", str(path), "--json"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert "Could not open" in payload["error"]["message"]

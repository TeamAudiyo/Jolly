from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from jolly.core.errors import ConfigurationError, MotionError

HEADER = b"\xff\xff"
PING = 0x01
READ = 0x02
WRITE = 0x03
SYNC_WRITE = 0x83
TORQUE_ENABLE = 40
GOAL_POSITION = 42
GOAL_SPEED = 46
PRESENT_POSITION = 56
DEFAULT_IDS = (1, 2, 3, 4, 5, 6)
JOINT_NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")


def calibration_example() -> dict[str, object]:
    motors = {
        name: {"id": index, "zero_raw": 2048, "direction": 1, "raw_per_degree": 4096 / 360}
        for index, name in enumerate(JOINT_NAMES, start=1)
    }
    motors["gripper"] = {"id": 6, "open_raw": 2048, "closed_raw": 3072}
    return {
        "warning": "Placeholder values. Measure this physical arm before enabling torque.",
        "calibrated": False,
        "motors": motors,
    }


def encode_packet(motor_id: int, instruction: int, parameters: bytes = b"") -> bytes:
    if not 0 <= motor_id <= 0xFE:
        raise ConfigurationError("Motor ID must be between 0 and 254.")
    length = len(parameters) + 2
    checksum = (~(motor_id + length + instruction + sum(parameters))) & 0xFF
    return HEADER + bytes((motor_id, length, instruction)) + parameters + bytes((checksum,))


def decode_status(packet: bytes) -> tuple[int, int, bytes]:
    if len(packet) < 6 or packet[:2] != HEADER:
        raise MotionError("Invalid STS3215 status header.")
    motor_id, length, error = packet[2], packet[3], packet[4]
    if len(packet) != length + 4:
        raise MotionError("Incomplete STS3215 status packet.")
    expected = (~sum(packet[2:-1])) & 0xFF
    if packet[-1] != expected:
        raise MotionError("STS3215 status checksum failed.")
    return motor_id, error, packet[5:-1]


@dataclass(frozen=True)
class MotorCalibration:
    motor_id: int
    zero_raw: int
    direction: int
    raw_per_degree: float

    def degrees_to_raw(self, degrees: float) -> int:
        raw = round(self.zero_raw + self.direction * degrees * self.raw_per_degree)
        if not 0 <= raw <= 4095:
            raise MotionError(f"Calibrated target {degrees:.2f}° maps outside the STS3215 range.")
        return raw

    def raw_to_degrees(self, raw: int) -> float:
        return (raw - self.zero_raw) / (self.direction * self.raw_per_degree)


@dataclass(frozen=True)
class GripperCalibration:
    motor_id: int
    open_raw: int
    closed_raw: int

    def value_to_raw(self, value: float) -> int:
        if not 0.0 <= value <= 1.0:
            raise MotionError("Gripper must be between 0.0 and 1.0.")
        return round(self.open_raw + value * (self.closed_raw - self.open_raw))


@dataclass(frozen=True)
class SO101Calibration:
    motors: dict[str, MotorCalibration]
    gripper: GripperCalibration

    @classmethod
    def load(cls, path: str | Path) -> "SO101Calibration":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("calibrated") is not True:
            raise ConfigurationError("Calibration must set 'calibrated' to true after physical measurements.")
        raw_motors = data.get("motors", {})
        missing = [name for name in JOINT_NAMES if name not in raw_motors]
        if missing or "gripper" not in raw_motors:
            raise ConfigurationError(f"Calibration is missing motors: {', '.join([*missing, 'gripper'] if 'gripper' not in raw_motors else missing)}")
        motors = {
            name: MotorCalibration(
                motor_id=int(raw_motors[name]["id"]),
                zero_raw=int(raw_motors[name]["zero_raw"]),
                direction=int(raw_motors[name]["direction"]),
                raw_per_degree=float(raw_motors[name].get("raw_per_degree", 4096 / 360)),
            )
            for name in JOINT_NAMES
        }
        for name, motor in motors.items():
            if not 1 <= motor.motor_id <= 253:
                raise ConfigurationError(f"Motor ID for '{name}' must be between 1 and 253.")
            if motor.direction not in (-1, 1) or not 5.0 <= motor.raw_per_degree <= 20.0:
                raise ConfigurationError(f"Invalid calibration for '{name}'.")
        raw_gripper = raw_motors["gripper"]
        gripper = GripperCalibration(
            motor_id=int(raw_gripper["id"]),
            open_raw=int(raw_gripper["open_raw"]),
            closed_raw=int(raw_gripper["closed_raw"]),
        )
        if not 1 <= gripper.motor_id <= 253 or not 0 <= gripper.open_raw <= 4095 or not 0 <= gripper.closed_raw <= 4095:
            raise ConfigurationError("Invalid physical gripper calibration.")
        ids = [motor.motor_id for motor in motors.values()] + [gripper.motor_id]
        if len(set(ids)) != len(ids):
            raise ConfigurationError("Each SO-101 motor must have a unique ID.")
        return cls(motors=motors, gripper=gripper)


class SO101HardwareDriver:
    """Direct STS3215 serial driver for a physical SO-101 arm."""

    name = "SO101HardwareDriver"

    def __init__(self, port: str, calibration: SO101Calibration, *, baudrate: int = 1_000_000, timeout: float = 0.08) -> None:
        try:
            import serial
        except ImportError as exc:
            raise ConfigurationError("Install physical hardware support with: pip install 'jolly-cli[hardware]'") from exc
        self.port = port
        self.calibration = calibration
        try:
            self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout, write_timeout=timeout)
        except (serial.SerialException, OSError) as exc:
            raise ConfigurationError(f"Could not open physical SO-101 serial port '{port}': {exc}") from exc
        self.serial.reset_input_buffer()

    def __enter__(self) -> "SO101HardwareDriver":
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if exc_type is not None:
            try:
                self.emergency_stop()
            except Exception:
                pass
        self.close()

    def close(self) -> None:
        self.serial.close()

    def _transact(self, motor_id: int, instruction: int, parameters: bytes = b"") -> bytes:
        self.serial.reset_input_buffer()
        self.serial.write(encode_packet(motor_id, instruction, parameters))
        self.serial.flush()
        header = self.serial.read(2)
        if header != HEADER:
            raise MotionError(f"Motor {motor_id} did not return a valid status packet.")
        prefix = self.serial.read(2)
        if len(prefix) != 2:
            raise MotionError(f"Motor {motor_id} returned an incomplete status packet.")
        response_id, length = prefix
        tail = self.serial.read(length)
        packet = header + prefix + tail
        parsed_id, error, values = decode_status(packet)
        if parsed_id != response_id or parsed_id != motor_id:
            raise MotionError(f"Received a status packet from unexpected motor {parsed_id}.")
        if error:
            raise MotionError(f"Motor {motor_id} reported STS3215 error bits 0x{error:02x}.")
        return values

    def ping(self, motor_id: int) -> bool:
        try:
            self._transact(motor_id, PING)
            return True
        except MotionError:
            return False

    def scan(self, motor_ids: Sequence[int] = DEFAULT_IDS) -> list[int]:
        return [motor_id for motor_id in motor_ids if self.ping(int(motor_id))]

    def _read_u16(self, motor_id: int, address: int) -> int:
        values = self._transact(motor_id, READ, bytes((address, 2)))
        if len(values) != 2:
            raise MotionError(f"Motor {motor_id} returned {len(values)} bytes for a 2-byte register.")
        return int.from_bytes(values, "little")

    def _write(self, motor_id: int, address: int, values: bytes) -> None:
        self._transact(motor_id, WRITE, bytes((address,)) + values)

    def _sync_write_u16(self, address: int, values: dict[int, int]) -> None:
        parameters = bytearray((address, 2))
        for motor_id, value in values.items():
            parameters.append(motor_id)
            parameters.extend(int(value).to_bytes(2, "little"))
        self.serial.write(encode_packet(0xFE, SYNC_WRITE, bytes(parameters)))
        self.serial.flush()

    def set_torque(self, enabled: bool) -> None:
        for motor_id in [motor.motor_id for motor in self.calibration.motors.values()] + [self.calibration.gripper.motor_id]:
            self._write(motor_id, TORQUE_ENABLE, bytes((1 if enabled else 0,)))

    def emergency_stop(self) -> None:
        self.set_torque(False)

    def state(self) -> dict[str, object]:
        joints = []
        for name in JOINT_NAMES:
            calibration = self.calibration.motors[name]
            raw = self._read_u16(calibration.motor_id, PRESENT_POSITION)
            joints.append({"name": name, "motor_id": calibration.motor_id, "raw": raw, "position_degrees": round(calibration.raw_to_degrees(raw), 4)})
        gripper_raw = self._read_u16(self.calibration.gripper.motor_id, PRESENT_POSITION)
        return {"ok": True, "driver": self.name, "port": self.port, "joints": joints, "gripper": {"motor_id": self.calibration.gripper.motor_id, "raw": gripper_raw}}

    def move(self, joints_degrees: Sequence[float], gripper: float | None, *, max_delta_degrees: float = 20.0, timeout: float = 4.0) -> dict[str, object]:
        if len(joints_degrees) != len(JOINT_NAMES) or not all(math.isfinite(float(value)) for value in joints_degrees):
            raise MotionError("Physical SO-101 movement requires five finite joint angles.")
        before = self.state()
        current = {joint["name"]: float(joint["position_degrees"]) for joint in before["joints"]}
        for name, target in zip(JOINT_NAMES, joints_degrees, strict=True):
            if abs(float(target) - current[name]) > max_delta_degrees:
                raise MotionError(f"Joint '{name}' exceeds the {max_delta_degrees:.1f}° physical step limit.")
        targets = {
            name: self.calibration.motors[name].degrees_to_raw(float(target))
            for name, target in zip(JOINT_NAMES, joints_degrees, strict=True)
        }
        if gripper is not None:
            targets["gripper"] = self.calibration.gripper.value_to_raw(gripper)
        raw_before = {joint["name"]: int(joint["raw"]) for joint in before["joints"]}
        raw_before["gripper"] = int(before["gripper"]["raw"])
        for name, target_raw in targets.items():
            limit = 512 if name == "gripper" else 256
            if abs(int(target_raw) - raw_before[name]) > limit:
                raise MotionError(f"Motor '{name}' exceeds the {limit}-count physical step limit.")
        motor_targets = {
            self.calibration.motors[name].motor_id: int(targets[name]) for name in JOINT_NAMES
        }
        if "gripper" in targets:
            motor_targets[self.calibration.gripper.motor_id] = int(targets["gripper"])
        try:
            self.set_torque(True)
            for motor_id in motor_targets:
                self._write(motor_id, GOAL_SPEED, int(250).to_bytes(2, "little"))
            self._sync_write_u16(GOAL_POSITION, motor_targets)
            deadline = time.monotonic() + timeout
            result = self.state()
            while time.monotonic() < deadline:
                result = self.state()
                errors = [abs(float(joint["position_degrees"]) - float(target)) for joint, target in zip(result["joints"], joints_degrees, strict=True)]
                if max(errors, default=0.0) <= 2.0:
                    break
                time.sleep(0.05)
        except Exception:
            try:
                self.emergency_stop()
            except Exception:
                pass
            raise
        result["targets_degrees"] = [float(value) for value in joints_degrees]
        result["max_error_degrees"] = round(max(abs(float(joint["position_degrees"]) - float(target)) for joint, target in zip(result["joints"], joints_degrees, strict=True)), 4)
        result["torque_enabled"] = True
        result["goal_speed_raw"] = 250
        return result

    def benchmark(self, *, seed: int, cases: int = 3, excursion_degrees: float = 3.0) -> dict[str, object]:
        import random

        if not 1 <= cases <= 10 or not 0.5 <= excursion_degrees <= 5.0:
            raise ConfigurationError("Hardware benchmark requires 1-10 cases and a 0.5-5.0° excursion.")
        rng = random.Random(seed)
        origin = self.state()
        home = [float(joint["position_degrees"]) for joint in origin["joints"]]
        results = []
        try:
            for index in range(cases):
                target = [value + rng.uniform(-excursion_degrees, excursion_degrees) for value in home]
                result = self.move(target, None, max_delta_degrees=5.0)
                error = float(result["max_error_degrees"])
                score = 100.0 * max(0.0, 1.0 - error / 5.0)
                results.append({"case": index + 1, "target_degrees": target, "measured": result["joints"], "max_error_degrees": error, "score": round(score, 2)})
            self.move(home, None, max_delta_degrees=5.0)
        except Exception:
            try:
                self.emergency_stop()
            except Exception:
                pass
            raise
        return {"ok": all(float(item["max_error_degrees"]) <= 2.0 for item in results), "benchmark": "so101-physical-motion-v1", "driver": self.name, "seed": seed, "score": round(sum(float(item["score"]) for item in results) / len(results), 2), "torque_enabled": True, "instruction": "The arm is holding its return pose. Run 'jolly hardware stop' only when the arm is supported.", "cases": results}

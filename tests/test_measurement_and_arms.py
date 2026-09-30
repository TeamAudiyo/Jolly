import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from jolly.core.errors import ConfigurationError
from jolly.core.models import get_model, model_path
from jolly.engine import JollyEngine
from jolly.measurement import hardware_provider, measure_hardware, measure_simulation
from jolly.robots.registry import arm_profile, model_for_arm, workspace_from


def test_simulator_measurements_read_real_rigid_bodies():
    from jolly.core.physics import p
    with JollyEngine("so101", "pickplace") as engine:
        measured = measure_simulation(engine, ["part"])["part"]
        actual, _ = p.getBasePositionAndOrientation(engine.object_ids["part"], physicsClientId=engine.client)
        assert measured["position_meters"] == list(actual)
        assert measured["source"] == "pybullet-world-transform"


def test_hardware_requires_object_sensor():
    with pytest.raises(ConfigurationError, match="object measurement provider"):
        hardware_provider(None)


def test_tracker_document_freshness_frames_and_trial_identity(tmp_path):
    # Parsing fixture only; this data is never used to claim a hardware benchmark pass.
    document = tmp_path / "measurement.json"
    cfg = tmp_path / "provider.json"
    cfg.write_text(json.dumps({"provider": "tracker", "document": str(document), "max_age_seconds": 2}))
    payload = {"trial_id": "123:1", "frame": "robot-base", "units": "meters", "objects": {
        "part": {"dimensions": 2, "position_meters": [.1, .2], "measured_at": datetime.now(timezone.utc).isoformat()}}}
    document.write_text(json.dumps(payload))
    value = measure_hardware(str(cfg), ["part"], trial_id="123:1")["part"]
    assert value["dimensions"] == 2
    assert len(value["position_meters"]) == 2
    with pytest.raises(ConfigurationError, match="trial_id"):
        measure_hardware(str(cfg), ["part"], trial_id="123:2")
    payload["objects"]["part"]["measured_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    document.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match="stale"):
        measure_hardware(str(cfg), ["part"], trial_id="123:1")
    payload["objects"]["part"]["measured_at"] = datetime.now(timezone.utc).isoformat()
    payload["objects"]["part"]["position_meters"] = [float("nan"), 1]
    document.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match="finite"):
        measure_hardware(str(cfg), ["part"], trial_id="123:1")
    payload["objects"]["part"]["position_meters"] = [.1, .2]
    payload["objects"]["part"]["dimensions"] = 2.0
    document.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match="dimensions"):
        measure_hardware(str(cfg), ["part"], trial_id="123:1")
    payload["objects"]["part"]["dimensions"] = 2
    payload["objects"]["part"]["position_meters"] = [".1", True]
    document.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match="strings or booleans"):
        measure_hardware(str(cfg), ["part"], trial_id="123:1")


def test_real_so100_model_and_custom_model_registration(tmp_path, monkeypatch):
    assert arm_profile("so100")["physically_verified"] is False
    with JollyEngine("so100", "empty") as engine:
        point = engine.end_effector_position()
        reached = engine.reach(*point)
        assert reached["ik"]["error_meters"] < .025
    with pytest.raises(ConfigurationError, match="matching configured URDF"):
        model_for_arm("koch")
    model = get_model("so101")
    custom = tmp_path / "arms.json"
    custom.write_text(json.dumps({"arms": [{"id": "configured", "robot_type": "so101_follower", "kinematic_model": "configured"}],
        "kinematic_models": [{"id": "configured", "urdf": str(model_path(model)), "joint_names": list(model.arm_joint_names),
                              "gripper_joint_names": ["gripper"], "end_effector_link": model.end_effector_link,
                              "home_degrees": list(model.home_degrees), "source": model.source, "license": model.license}]}))
    monkeypatch.setenv("JOLLY_ARM_CONFIG", str(custom))
    assert model_for_arm("configured") == "configured"
    with JollyEngine("configured", "empty") as engine:
        assert engine.model.id == "configured"
    custom.write_text(json.dumps({"arms": [{"id": "bad", "robot_type": "mock_robot", "kinematic_model": None}]}))
    with pytest.raises(ConfigurationError, match="Mock"):
        arm_profile("bad")


def test_workspace_validates_units_and_finite_bounds():
    with pytest.raises(ConfigurationError):
        workspace_from({"workspace_meters": [[0, math.inf], [-.2, .2], [0, .5]]})


def test_tracker_rejects_malformed_evidence_and_previous_trial_capture(tmp_path):
    cfg = tmp_path / 'provider.json'
    doc = tmp_path / 'sensor.json'
    cfg.write_text(json.dumps({'provider': 'tracker', 'document': str(doc)}))
    stamp = datetime.now(timezone.utc)
    payload = {'trial_id': '1:1', 'frame': 'robot-base', 'units': 'meters', 'objects': {
        'part': {'position_meters': [.3, -.1, .05], 'dimensions': 3, 'measured_at': stamp.isoformat()}},
        'evidence': []}
    doc.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match='evidence'):
        measure_hardware(str(cfg), ['part'], trial_id='1:1')
    payload['evidence'] = {}
    doc.write_text(json.dumps(payload))
    with pytest.raises(ConfigurationError, match='predates'):
        measure_hardware(str(cfg), ['part'], trial_id='1:1', not_before=(stamp + timedelta(seconds=1)).isoformat())


def test_config_changes_block_controls_and_model_swap(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from jolly.cli import main
    monkeypatch.setenv('JOLLY_STATE_DIR', str(tmp_path / 'state'))
    registry = tmp_path / 'registry.json'
    registry.write_text('{}')
    monkeypatch.setenv('JOLLY_ARM_CONFIG', str(registry))
    runner = CliRunner()
    assert runner.invoke(main, ['benchmark', 'start', '--seed', '1', '--json']).exit_code == 0
    swapped = runner.invoke(main, ['state', '--model', 'so100', '--json'])
    assert swapped.exit_code == 2
    assert 'Cannot change' in swapped.output
    registry.write_text(json.dumps({'arms': []}))
    changed = runner.invoke(main, ['reach', '--x', '.3', '--y', '0', '--z', '.3', '--json'])
    assert changed.exit_code == 2
    assert 'registry changed' in changed.output


@pytest.mark.parametrize('arm', ['so100', 'so101', 'koch'])
def test_actual_lerobot_adapter_factory_without_hardware(tmp_path, arm):
    pytest.importorskip('lerobot')
    pytest.importorskip('scservo_sdk' if arm != 'koch' else 'dynamixel_sdk')
    from jolly.robots.lerobot_driver import LeRobotDriver
    # Calibration-loading fixture only. No port connection or hardware outcome.
    names = ['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll']
    (tmp_path / 'fixture.json').write_text(json.dumps({name: {
        'id': index + 1, 'drive_mode': 0, 'homing_offset': 0, 'range_min': 0, 'range_max': 4095}
        for index, name in enumerate(names + ['gripper'])}))
    cfg = tmp_path / 'arm.json'
    cfg.write_text(json.dumps({'arm': arm, 'port': '/dev/NO_ROBOT', 'id': 'fixture',
        'calibration_dir': str(tmp_path), 'use_degrees': True,
        'workspace_meters': [[.27, .33], [-.17, .17], [0, .36]], 'gripper_open_closed': [0, 100],
        'joint_mapping': {name: {'sign': 1, 'offset_degrees': 0, 'limits_degrees': [-90, 90]} for name in names}}))
    driver = LeRobotDriver(arm, str(cfg))
    assert not driver.robot.is_connected
    assert set(driver.robot.action_features) == {name + '.pos' for name in names + ['gripper']}
    assert driver.robot.config.use_degrees is True
    assert driver.robot.config.disable_torque_on_disconnect is False


def test_hardware_score_sensor_error_aborts_without_numeric_result(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from jolly.cli import main
    from jolly.core.store import load_state
    monkeypatch.setenv('JOLLY_STATE_DIR', str(tmp_path / 'state'))
    cfg = tmp_path / 'sensor.json'
    cfg.write_text(json.dumps({'provider': 'tracker', 'document': str(tmp_path / 'missing-live-sensor.json')}))
    arm = tmp_path / 'arm.json'
    arm.write_text(json.dumps({'arm': 'so101', 'workspace_meters': [[.27, .33], [-.17, .17], [0, .36]]}))
    runner = CliRunner()
    start = runner.invoke(main, ['benchmark', 'start', '--backend', 'hardware', '--arm', 'so101',
                                 '--arm-config', str(arm), '--measurement-config', str(cfg), '--json'])
    assert start.exit_code == 0
    score = runner.invoke(main, ['benchmark', 'score', '--json'])
    assert score.exit_code == 2
    assert 'placement_error_meters' not in score.output
    session = load_state()['benchmark_session']
    assert session['aborted']
    assert session['results'] == []
    control = runner.invoke(main, ['arm', 'reach', '--arm', 'so101', '--config', str(arm),
                                   '--confirm-hardware', '--x', '.3', '--y', '0', '--z', '.3', '--json'])
    assert control.exit_code == 2
    assert 'aborted' in control.output


def test_hardware_config_paths_resolve_before_persistence(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from jolly.cli import main
    monkeypatch.setenv('JOLLY_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'sensor.json').write_text(json.dumps({'provider': 'tracker', 'document': str(tmp_path / 'live.json')}))
    (tmp_path / 'arm.json').write_text(json.dumps({'arm': 'so101', 'workspace_meters': [[.27, .33], [-.17, .17], [0, .36]]}))
    result = CliRunner().invoke(main, ['benchmark', 'start', '--backend', 'hardware', '--arm-config', 'arm.json',
                                      '--measurement-config', 'sensor.json', '--json'])
    assert result.exit_code == 0, result.output
    session = json.loads(result.output)['state']['benchmark_session']
    assert session['arm_config'] == str(tmp_path / 'arm.json')
    assert session['measurement_config'] == str(tmp_path / 'sensor.json')


def test_planar_sensor_contract_reports_limited_scope(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from jolly.cli import main
    from jolly.core.store import load_state
    # Sensor parser contract fixture only. This is not physical performance evidence.
    monkeypatch.setenv('JOLLY_STATE_DIR', str(tmp_path / 'state'))
    sensor = tmp_path / 'live.json'
    cfg = tmp_path / 'sensor.json'
    cfg.write_text(json.dumps({'provider': 'tracker', 'document': str(sensor)}))
    arm = tmp_path / 'arm.json'
    arm.write_text(json.dumps({'arm': 'so101', 'workspace_meters': [[.27, .33], [-.17, .17], [0, .36]]}))
    runner = CliRunner()
    result = runner.invoke(main, ['benchmark', 'start', '--backend', 'hardware', '--arm-config', str(arm),
                                  '--measurement-config', str(cfg), '--seed', '1', '--json'])
    assert result.exit_code == 0
    instance = load_state()['challenge_instance']
    sensor.write_text(json.dumps({'trial_id': '1:1', 'frame': 'robot-base', 'units': 'meters', 'objects': {
        name: {'dimensions': 2, 'position_meters': point[:2], 'measured_at': datetime.now(timezone.utc).isoformat()}
        for name, point in [('part', instance['object_positions']['part']), (instance['place_slot'], instance['target'])]}}))
    scored = runner.invoke(main, ['benchmark', 'score', '--json'])
    assert scored.exit_code == 0, scored.output
    trial = json.loads(scored.output)['trial']
    assert trial['verification_scope'] == 'planar-only'
    assert trial['center_distance_3d_meters'] is None
    assert not trial['success']
    assert 'no_grasp_evidence' in trial['failure_reasons']

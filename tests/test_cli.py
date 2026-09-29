import json

import pytest
from click.testing import CliRunner

from jolly.cli import main


def invoke(runner: CliRunner, args: list[str]):
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output + repr(result.exception)
    return result


def test_cli_state_is_machine_readable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["reset", "--model", "jolly6", "--scene", "blocks", "--json"])
    result = invoke(runner, ["state", "--json"])
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["model"]["id"] == "jolly6"
    assert data["scene"] == "blocks"
    assert len(data["joints"]) == 6


def test_cli_move_persists_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["reset", "--json"])
    result = invoke(
        runner,
        ["move", "--joints", "0,-20,60,-40,0,0", "--gripper", "0.4", "--allow-collision", "--json"],
    )
    moved = json.loads(result.output)
    current = json.loads(invoke(runner, ["state", "--json"]).output)
    assert moved["gripper"] == 0.4
    assert current["gripper"] == 0.4
    assert current["joints"][1]["position_degrees"] == pytest.approx(-20, abs=0.5)


def test_reset_restores_objects_in_same_scene(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    initial = json.loads(invoke(runner, ["reset", "--scene", "blocks", "--json"]).output)
    red = next(item for item in initial["objects"] if item["name"] == "red_block")
    state_path = tmp_path / "state.json"
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    next(item for item in saved["objects"] if item["name"] == "red_block")["position"] = [0.16, -0.27, 0.05]
    state_path.write_text(json.dumps(saved), encoding="utf-8")
    reset = json.loads(invoke(runner, ["reset", "--scene", "blocks", "--json"]).output)
    reset_red = next(item for item in reset["objects"] if item["name"] == "red_block")
    assert reset_red["position"] == pytest.approx(red["position"], abs=1e-4)


def test_cli_lists_scenes_and_challenges(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    scenes = json.loads(invoke(runner, ["scene", "list", "--json"]).output)
    challenges = json.loads(invoke(runner, ["challenge", "list", "--json"]).output)
    assert len(scenes["scenes"]) >= 4
    assert len(challenges["challenges"]) >= 4


def test_cli_benchmark_requires_explicit_pick_and_place_controls(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    started = json.loads(invoke(runner, ["benchmark", "start", "--seed", "1", "--json"]).output)
    assert started["benchmark"] == "jolly-pick-place-trials-v1"
    assert started["motion_executed"] is False
    assert started["state"]["benchmark_controls"] == []
    measured = json.loads(invoke(runner, ["benchmark", "score", "--json"]).output)
    assert measured["trial"]["outcome"] == "FAIL"
    assert measured["summary"]["score"] == 0
    assert measured["trial"]["control_count"] == 0
    assert "no_grasp_evidence" in measured["trial"]["failure_reasons"]


def test_state_cannot_swap_models_during_operator_benchmark(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["benchmark", "start", "--seed", "1", "--model", "so101", "--json"])
    result = runner.invoke(main, ["state", "--model", "jolly6", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["error"]["type"] == "ConfigurationError"
    assert "operator benchmark is active" in data["error"]["message"]


def test_cli_motion_error_is_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["reset", "--json"])
    result = runner.invoke(main, ["move", "--joints", "999,0,0,0,0,0", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["type"] == "MotionError"


def test_cli_reports_corrupt_state_cleanly(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text("not-json", encoding="utf-8")
    result = CliRunner().invoke(main, ["state", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error"]["type"] == "ConfigurationError"


def test_challenge_wrong_scene_is_json_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["reset", "--scene", "empty", "--json"])
    result = runner.invoke(main, ["challenge", "status", "--challenge", "sort-red", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["error"]["type"] == "ConfigurationError"


def test_missing_active_challenge_is_json_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    result = CliRunner().invoke(main, ["challenge", "status", "--json"])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert data["error"]["type"] == "ConfigurationError"


def test_render_preserves_active_challenge(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    invoke(runner, ["challenge", "start", "sort-red", "--json"])
    invoke(runner, ["render", "--json"])
    status = json.loads(invoke(runner, ["challenge", "status", "--json"]).output)
    assert status["challenge"]["id"] == "sort-red"
    assert status["metrics"]["commands"] == 0


def test_public_web_bind_requires_explicit_flag() -> None:
    result = CliRunner().invoke(main, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "--unsafe-public" in result.output


def test_reset_recovers_from_corrupt_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text("{bad", encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(main, ["state", "--json"]).exit_code == 2
    invoke(runner, ["reset", "--json"])
    invoke(runner, ["state", "--json"])

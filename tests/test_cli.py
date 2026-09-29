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


def test_cli_lists_scenes_and_challenges(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    scenes = json.loads(invoke(runner, ["scene", "list", "--json"]).output)
    challenges = json.loads(invoke(runner, ["challenge", "list", "--json"]).output)
    assert len(scenes["scenes"]) >= 4
    assert len(challenges["challenges"]) >= 4


def test_cli_benchmark_passes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    data = json.loads(invoke(runner, ["benchmark", "--json"]).output)
    assert data["ok"] is True
    assert data["score"] == 100.0

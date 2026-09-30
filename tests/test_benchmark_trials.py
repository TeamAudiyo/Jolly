"""Real PyBullet trials: no mocked motion, contacts, or scoring outcomes."""
import json
import math
import statistics

from click.testing import CliRunner
import pytest

from jolly.cli import main


def call(runner, *args):
    result = runner.invoke(main, [*map(str, args), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def place(runner, instance, *, destination=None):
    pickup = instance["object_positions"]["part"]
    target = destination or instance["target"]

    def reach(x, y, z, g):
        return call(runner, "reach", "--x", x, "--y", y, "--z", z, "--gripper", g)

    reach(*pickup[:2], pickup[2] + .1, 0)
    grasp = reach(*pickup[:2], pickup[2] + .055, 1)
    assert grasp["held_object"] == "part"
    reach(*pickup[:2], .34, 1)
    state = reach(*target[:2], .34, 1)
    for height in (.34, .23, .23, .18, .18):
        obj = next(o for o in state["objects"] if o["name"] == "part")
        tool = state["end_effector"]["position"]
        state = reach(tool[0] + target[0] - obj["position"][0],
                      tool[1] + target[1] - obj["position"][1], height, 1)
    tool = state["end_effector"]["position"]
    state = reach(*tool, 0)
    assert state["held_object"] is None


def test_real_three_trial_session_and_numeric_math(tmp_path, monkeypatch):
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    started = call(runner, "benchmark", "start", "--seed", 1, "--trials", 3)
    original_plan = started["state"]["benchmark_session"]["planned_trials"]
    assert len({json.dumps(t["object_positions"]) for t in original_plan}) == 3
    premature = runner.invoke(main, ["benchmark", "next", "--json"])
    assert premature.exit_code == 2
    # Trial 1: actual successful constrained grasp and pad placement.
    place(runner, started["instance"])
    first = call(runner, "benchmark", "score")
    assert first["trial"]["success"], first["trial"]["failure_reasons"]
    assert first["trial"]["checks"]["not_on_pad"]
    assert first["trial"]["placement_error_meters"] < .02
    assert first == call(runner, "benchmark", "score")
    before = (tmp_path / "state.json").read_bytes()
    call(runner, "benchmark", "score")
    assert (tmp_path / "state.json").read_bytes() == before
    rejected = runner.invoke(main, ["reach", "--x", ".3", "--y", "0", "--z", ".3", "--json"])
    assert rejected.exit_code == 2
    assert (tmp_path / "state.json").read_bytes() == before
    # Trial 2: no commands. No grasp evidence, no placement, genuine failed trial.
    second = call(runner, "benchmark", "next")
    assert second["instance"] != started["instance"]
    measured = call(runner, "benchmark", "score")
    assert not measured["trial"]["success"]
    assert measured["summary"]["score"] == 50
    # Trial 3: pick the object up, then place it on the wrong side of the table.
    third = call(runner, "benchmark", "next")
    place(runner, third["instance"], destination=[.30, -.22, .006])
    wrong = call(runner, "benchmark", "score")
    assert not wrong["trial"]["success"]
    assert wrong["trial"]["placement_error_meters"] > .1
    report = call(runner, "benchmark", "report")
    assert report["score"] == pytest.approx(100 / 3)
    assert report["complete"] is True
    errors = [t["placement_error_meters"] for t in report["trials"]]
    assert report["mean_placement_error_meters"] == statistics.mean(errors)
    for trial in report["trials"]:
        obj, target = trial["measurements"]["object"], trial["measurements"]["target"]
        assert obj["source"] == target["source"] == "pybullet-world-transform"
        assert trial["placement_error_meters"] == math.dist(obj["position_meters"][:2], target["position_meters"][:2])
    history = call(runner, "benchmark", "history")
    assert history["trials"] == report["trials"]
    replay = call(runner, "benchmark", "start", "--seed", 1, "--trials", 3)
    assert replay["state"]["benchmark_session"]["planned_trials"] == original_plan


def test_budget_and_reset_invalidation(tmp_path, monkeypatch):
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    started = call(runner, "benchmark", "start", "--seed", 1, "--max-commands", 1)
    place(runner, started["instance"])
    score = call(runner, "benchmark", "score")
    assert "command_budget_exceeded" in score["trial"]["failure_reasons"]
    reset = call(runner, "reset", "--model", "so101")
    assert reset["benchmark_invalidations"]
    assert "active_benchmark" not in reset
    state = call(runner, "state")
    assert state["benchmark_invalidations"] == reset["benchmark_invalidations"]
    history = call(runner, "benchmark", "history")
    assert history["invalidations"] == reset["benchmark_invalidations"]
    assert history["trials"] == []
    assert runner.invoke(main, ["benchmark", "score", "--json"]).exit_code == 2


def test_rejected_collision_is_not_forgotten(tmp_path, monkeypatch):
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    runner = CliRunner()
    started = call(runner, "benchmark", "start", "--seed", 1)
    pickup = started["instance"]["object_positions"]["part"]
    call(runner, "reach", "--x", pickup[0], "--y", pickup[1], "--z", .15)
    bad = runner.invoke(main, ["reach", "--x", str(pickup[0]), "--y", str(pickup[1]), "--z", ".04", "--json"])
    assert bad.exit_code == 2
    state = call(runner, "benchmark", "status")
    assert any(c["measured"]["collision"] for c in state["controls"])
    scored = call(runner, "benchmark", "score")
    assert "collision" in scored["trial"]["failure_reasons"]

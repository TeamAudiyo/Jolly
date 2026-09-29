from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from jolly.benchmark import run_benchmark
from jolly.cli import main
from jolly.driver import JollyDriver
from jolly.engine import JollyEngine


@pytest.mark.parametrize(
    "challenge_id", ["reach-center", "sort-red", "shelf-load", "obstacle-reach"]
)
@pytest.mark.parametrize("seed", [7, 101, 2027])
def test_every_challenge_is_seeded_and_reproducible(challenge_id: str, seed: int) -> None:
    first = JollyDriver(seed).challenge_instance(challenge_id)
    replay = JollyDriver(seed).challenge_instance(challenge_id)
    different = JollyDriver(seed + 1).challenge_instance(challenge_id)
    assert first == replay
    assert first != different


def test_default_driver_uses_fresh_random_seed() -> None:
    first = JollyDriver()
    second = JollyDriver()
    assert first.seed != second.seed
    assert first.challenge_instance("reach-center") != second.challenge_instance("reach-center")


def test_challenge_start_saves_generated_instance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    result = CliRunner().invoke(
        main, ["challenge", "start", "sort-red", "--seed", "12345", "--json"]
    )
    assert result.exit_code == 0, result.output + repr(result.exception)
    data = json.loads(result.output)
    assert data["seed"] == 12345
    assert data["state"]["challenge_instance"] == data["instance"]
    positions = {item["name"]: item["position"] for item in data["state"]["objects"]}
    for name, expected in data["instance"]["object_positions"].items():
        assert positions[name] == pytest.approx(expected, abs=1e-6)


def test_benchmark_randomizes_every_case_and_replays_seed() -> None:
    first = run_benchmark(seed=77, cases=1)
    replay = run_benchmark(seed=77, cases=1)
    different = run_benchmark(seed=78, cases=1)
    first_inputs = [task["instance"] for task in first["tasks"]]
    replay_inputs = [task["instance"] for task in replay["tasks"]]
    different_inputs = [task["instance"] for task in different["tasks"]]
    assert first["engine"] == JollyEngine.name
    assert first["driver"] == JollyDriver.name
    assert first_inputs == replay_inputs
    assert first_inputs != different_inputs
    assert len({item["seed"] for item in first_inputs}) == len(first_inputs)
    assert first["score"] == replay["score"]
    assert all("metrics" in task and "score" in task for task in first["tasks"])


def test_jolly_engine_declares_its_backend_without_external_harness() -> None:
    assert JollyEngine.name == "JollyEngine"
    assert JollyEngine.physics_backend == "PyBullet"

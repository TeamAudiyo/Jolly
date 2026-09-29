import json

from click.testing import CliRunner
from fastapi.testclient import TestClient

from jolly.cli import main
from jolly.web.app import app


def test_web_viewer_and_api(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "JOLLY" in page.text
    reset = client.post("/api/reset", json={"model": "jolly6", "scene": "blocks"})
    assert reset.status_code == 200
    assert reset.json()["scene"] == "blocks"
    state = client.get("/api/state")
    assert state.status_code == 200
    assert len(state.json()["skeleton_points"]) >= 7
    rendered = client.get("/api/render.png?width=320&height=240")
    assert rendered.status_code == 200
    assert rendered.headers["content-type"] == "image/png"
    assert rendered.content.startswith(b"\x89PNG\r\n\x1a\n")
    invalid = client.post("/api/move", json={"joints": [999, 0, 0, 0, 0, 0]})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["type"] == "MotionError"


def test_web_corrupt_state_is_400_and_reset_recovers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    (tmp_path / "state.json").write_text("{bad", encoding="utf-8")
    client = TestClient(app)
    bad = client.get("/api/state")
    assert bad.status_code == 400
    assert bad.json()["detail"]["type"] == "ConfigurationError"
    assert client.post("/api/reset", json={}).status_code == 200
    assert client.get("/api/state").status_code == 200


def test_web_preserves_and_records_operator_benchmark(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JOLLY_STATE_DIR", str(tmp_path))
    started_result = CliRunner().invoke(
        main, ["benchmark", "start", "--seed", "1", "--model", "so101", "--json"]
    )
    assert started_result.exit_code == 0, started_result.output
    started = json.loads(started_result.output)
    peg = started["instance"]["object_positions"]["part"]

    client = TestClient(app)
    read_state = client.get("/api/state")
    assert read_state.status_code == 200
    assert read_state.json()["active_benchmark"] == "jolly-pick-place-trials-v1"
    assert read_state.json()["benchmark_controls"] == []

    reached = client.post(
        "/api/reach",
        json={
            "x": peg[0],
            "y": peg[1],
            "z": peg[2] + 0.10,
            "gripper": 0.0,
            "allow_collision": False,
        },
    )
    assert reached.status_code == 200, reached.text
    control = reached.json()["benchmark_controls"][0]
    assert control["source"] == "web-api"
    assert control["command"] == "reach"
    assert control["requested"]["allow_collision"] is False

    score = CliRunner().invoke(main, ["benchmark", "score", "--json"])
    assert score.exit_code == 0, score.output
    measured = json.loads(score.output)
    assert measured["trial"]["control_count"] == 1
    assert measured["trial"]["outcome"] == "FAIL"

from fastapi.testclient import TestClient

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

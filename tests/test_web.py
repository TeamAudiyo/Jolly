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
    invalid = client.post("/api/move", json={"joints": [999, 0, 0, 0, 0, 0]})
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["type"] == "MotionError"

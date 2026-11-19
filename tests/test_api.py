import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

PAYLOADS = Path(__file__).resolve().parent.parent / "example_payloads"

client = TestClient(app)


def load_json(name):
    return json.loads((PAYLOADS / name).read_text())


@pytest.mark.parametrize("name", ["payload1.json", "payload2.json", "payload3.json"])
def test_example_payloads_give_a_balanced_plan(name):
    payload = load_json(name)
    response = client.post("/productionplan", json=payload)

    assert response.status_code == 200
    plan = response.json()
    assert sorted(item["name"] for item in plan) == sorted(p["name"] for p in payload["powerplants"])
    assert all(abs(item["p"] * 10 - round(item["p"] * 10)) < 1e-6 for item in plan)
    assert sum(round(item["p"] * 10) for item in plan) == round(payload["load"] * 10)


def test_payload3_gives_the_expected_response():
    response = client.post("/productionplan", json=load_json("payload3.json"))
    assert response.json() == load_json("response3.json")


def test_invalid_payload_is_rejected():
    payload = load_json("payload1.json")
    payload["fuels"]["wind(%)"] = 150
    assert client.post("/productionplan", json=payload).status_code == 422


def test_nan_is_rejected():
    payload = load_json("payload1.json")
    payload["load"] = float("nan")
    response = client.post(
        "/productionplan",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_duplicate_names_are_rejected():
    payload = load_json("payload1.json")
    payload["powerplants"][1]["name"] = payload["powerplants"][0]["name"]
    assert client.post("/productionplan", json=payload).status_code == 422


def test_unreachable_load_returns_the_reason():
    payload = load_json("payload1.json")
    payload["load"] = 10_000
    response = client.post("/productionplan", json=payload)
    assert response.status_code == 422
    assert "capacity" in response.json()["detail"]


def test_unexpected_errors_are_logged_and_return_500(monkeypatch, caplog):
    def broken(_):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.compute_production_plan", broken)
    response = client.post("/productionplan", json=load_json("payload1.json"))

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "boom" in caplog.text

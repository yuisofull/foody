from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import main as app_main
from app.models.menu import MenuItem
from app.models.nutrition import NutritionConfidence, NutritionEstimate
from app.models.restaurant import Location, Restaurant


def _discover_payload() -> dict:
    return {
        "location": {"lat": -37.8136, "lng": 144.9631},
        "radius": 1500,
        "profile": {
            "user_id": "job_user_1",
            "goal_type": "muscle_gain",
            "cal_target": 2200,
            "macro_splits": {"protein": 0.3, "carbs": 0.4, "fat": 0.3},
            "restrictions": [],
            "budget_max": 30,
            "cuisine_preferences": [],
            "liked_items": [],
            "disliked_items": [],
        },
        "top_n": 3,
    }


def _poll_until_terminal(client: TestClient, job_id: str, timeout_s: float = 3.0) -> dict:
    deadline = time.time() + timeout_s
    last_payload: dict = {}
    while time.time() < deadline:
        resp = client.get(f"/discover/jobs/{job_id}")
        assert resp.status_code == 200
        last_payload = resp.json()
        if last_payload["status"] in {"completed", "failed"}:
            return last_payload
        time.sleep(0.05)

    raise AssertionError(f"Job did not finish in time. Last payload: {last_payload}")


def _reset_discover_state() -> None:
    app_main._discover_jobs.clear()
    if app_main._discover_queue is None:
        return
    while not app_main._discover_queue.empty():
        app_main._discover_queue.get_nowait()
        app_main._discover_queue.task_done()


def test_discover_job_queue_and_poll_success(monkeypatch):
    _reset_discover_state()

    async def fake_nearby(location: Location, radius: float) -> list[Restaurant]:
        return [
            Restaurant(
                id="r1",
                name="Alpha Diner",
                address="1 Main St",
                location=Location(lat=location.lat, lng=location.lng),
                website=None,
            )
        ]

    async def fake_get_menu_items(restaurant: Restaurant) -> list[MenuItem]:
        return [
            MenuItem(
                id="m1",
                name="Protein Bowl",
                price=12.0,
                description="High protein bowl",
                category="Bowls",
                tags=["high-protein"],
            )
        ]

    async def fake_recommend_for_items(profile, items, top_n):
        estimate = NutritionEstimate(
            calories=620,
            protein=45,
            carbs=50,
            fat=20,
            confidence=NutritionConfidence.estimated,
        )
        first_item = items[0]
        return [(first_item.id, 98.5, estimate, first_item.name)][:top_n]

    monkeypatch.setattr(app_main._restaurant_service, "get_nearby_restaurants", fake_nearby)
    monkeypatch.setattr(app_main._menu_service, "get_menu_items", fake_get_menu_items)
    monkeypatch.setattr(app_main._recommendation_service, "recommend_for_items", fake_recommend_for_items)

    with TestClient(app_main.app) as client:
        enqueue_resp = client.post("/discover", json=_discover_payload())
        assert enqueue_resp.status_code == 202
        enqueue_payload = enqueue_resp.json()
        assert enqueue_payload["status"] == "queued"
        assert "job_id" in enqueue_payload
        assert enqueue_payload["poll_url"].endswith(enqueue_payload["job_id"])

        job_payload = _poll_until_terminal(client, enqueue_payload["job_id"])
        assert job_payload["status"] == "completed"
        result = job_payload["result"]
        assert result is not None
        assert len(result["recommendations"]) == 1
        assert result["recommendations"][0]["name"] == "Protein Bowl"
        assert result["recommendations"][0]["restaurant_id"] == "r1"


def test_discover_job_queue_and_poll_failure(monkeypatch):
    _reset_discover_state()

    async def fake_nearby(location: Location, radius: float) -> list[Restaurant]:
        return []

    monkeypatch.setattr(app_main._restaurant_service, "get_nearby_restaurants", fake_nearby)

    with TestClient(app_main.app) as client:
        enqueue_resp = client.post("/discover", json=_discover_payload())
        assert enqueue_resp.status_code == 202
        job_id = enqueue_resp.json()["job_id"]

        # Nearby returns empty, so job should complete with empty recommendations.
        job_payload = _poll_until_terminal(client, job_id)
        assert job_payload["status"] == "completed"
        assert job_payload["result"]["recommendations"] == []


def test_discover_job_poll_not_found():
    _reset_discover_state()
    with TestClient(app_main.app) as client:
        resp = client.get("/discover/jobs/does-not-exist")
        assert resp.status_code == 404

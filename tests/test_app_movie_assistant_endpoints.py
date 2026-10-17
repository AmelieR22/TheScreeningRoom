from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app, get_movie_assistant_service


@pytest.fixture
def mock_lifespan_services(monkeypatch):
    recommendation_service = MagicMock()
    recommendation_service.driver = MagicMock()
    recommendation_service.driver.close = MagicMock()

    analytics_service = MagicMock()
    analytics_service.driver = MagicMock()
    analytics_service.driver.close = MagicMock()

    assistant_service = MagicMock()
    assistant_service.driver = MagicMock()
    assistant_service.driver.close = MagicMock()

    monkeypatch.setattr(app_main, "MovieRecommendationService", lambda: recommendation_service)
    monkeypatch.setattr(app_main, "GraphAnalyticsService", lambda: analytics_service)
    monkeypatch.setattr(app_main, "MovieAssistantService", lambda: assistant_service)

    yield recommendation_service, analytics_service, assistant_service

    app.dependency_overrides.clear()


def test_movie_assistant_endpoint_uses_service(mock_lifespan_services):
    _, _, service = mock_lifespan_services
    service.ask.return_value = {
        "question": "Find five highly rated comedy movies",
        "generated_cypher": "MATCH (m:Movie) RETURN m.title AS title LIMIT 5",
        "results": [{"title": "Toy Story"}],
        "explanation": "Safe fallback",
    }

    app.dependency_overrides[get_movie_assistant_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.post(
                "/assistant/ask",
                json={"question": "Find five highly rated comedy movies"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["question"] == "Find five highly rated comedy movies"
    assert response.json()["results"][0]["title"] == "Toy Story"


def test_movie_assistant_endpoint_rejects_bad_question(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    with TestClient(app) as client:
        response = client.post("/assistant/ask", json={"question": "   "})

    assert response.status_code == 400

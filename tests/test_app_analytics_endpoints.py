from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app, get_graph_analytics_service


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


def test_similar_users_endpoint_uses_service(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    service = MagicMock()
    service.get_similar_users.return_value = [
        {"user_id": 2, "score": 0.92, "source": "gds-node-similarity"},
        {"user_id": 3, "score": 0.87, "source": "gds-node-similarity"},
    ]
    app.dependency_overrides[get_graph_analytics_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/analytics/similar-users/1?limit=2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["user_id"] == 2
    assert response.json()["items"][0]["score"] == 0.92


def test_user_communities_endpoint_uses_service(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    service = MagicMock()
    service.get_user_communities.return_value = [
        {"community_id": 1, "user_count": 3, "user_ids": [10, 11, 12]},
    ]
    app.dependency_overrides[get_graph_analytics_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/analytics/communities?limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["community_id"] == 1
    assert response.json()["items"][0]["user_count"] == 3


def test_similar_users_endpoint_validates_positive_id(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    with TestClient(app) as client:
        response = client.get("/analytics/similar-users/0")
    assert response.status_code == 422


def test_user_communities_endpoint_validates_limit(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    with TestClient(app) as client:
        response = client.get("/analytics/communities?limit=0")
    assert response.status_code == 422


def test_user_path_endpoint_uses_service(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    service = MagicMock()
    service.find_user_path.return_value = {
        "found": True,
        "path": {"nodes": [{"type": "User", "id": 1, "title": None}, {"type": "Movie", "id": 10, "title": "Toy Story"}, {"type": "User", "id": 2, "title": None}], "relationships": [{"type": "RATED", "from": 1, "to": 10}, {"type": "RATED", "from": 10, "to": 2}], "hop_count": 2},
    }
    app.dependency_overrides[get_graph_analytics_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/analytics/path/users/1/2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["found"] is True
    assert response.json()["path"]["hop_count"] == 2


def test_user_movie_path_endpoint_returns_no_path(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    service = MagicMock()
    service.find_user_movie_path.return_value = {
        "found": False,
        "path": {"nodes": [], "relationships": [], "hop_count": 0},
        "message": "No path found between the user and the movie.",
    }
    app.dependency_overrides[get_graph_analytics_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/analytics/path/user-movie/1/999")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["found"] is False
    assert response.json()["path"]["hop_count"] == 0


def test_path_endpoints_reject_invalid_ids(mock_lifespan_services):
    _, _, _ = mock_lifespan_services
    with TestClient(app) as client:
        response = client.get("/analytics/path/users/0/1")
    assert response.status_code == 422

    with TestClient(app) as client:
        response = client.get("/analytics/path/user-movie/1/0")
    assert response.status_code == 422

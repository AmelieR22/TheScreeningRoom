from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app, get_recommendation_service


def test_root_endpoint_serves_html():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '/static/styles.css' in response.text
    assert '/static/script.js' in response.text


def test_static_assets_are_served():
    with TestClient(app) as client:
        stylesheet = client.get("/static/styles.css")
        script = client.get("/static/script.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")

    assert script.status_code == 200
    assert script.headers["content-type"].startswith(("application/javascript", "text/javascript"))


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_popular_endpoint_uses_service():
    service = MagicMock()
    service.get_popular_movies.return_value = [{"movie_id": 1, "title": "Movie A"}]
    app.dependency_overrides[get_recommendation_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/recommendations/popular?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["movie_id"] == 1


def test_similar_endpoint_validates_positive_id():
    with TestClient(app) as client:
        response = client.get("/recommendations/similar/0")
    assert response.status_code == 422


def test_personalized_endpoint_uses_service():
    service = MagicMock()
    service.get_personalized_recommendations.return_value = [{"movie_id": 99, "title": "Movie Z", "source": "collaborative"}]
    app.dependency_overrides[get_recommendation_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/recommendations/personalized/7?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["source"] == "collaborative"


def test_invalid_limit_returns_422():
    with TestClient(app) as client:
        response = client.get("/recommendations/popular?limit=0")
    assert response.status_code == 422

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_tmdb_service
from app.tmdb_service import TMDbService


def test_dockerfile_copies_movie_metadata_data():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY data ./data" in dockerfile


def test_tmdb_service_loads_movie_mapping():
    movie_id = 1
    tmdb_id = TMDbService().get_tmdb_id(movie_id)
    assert isinstance(tmdb_id, int)
    assert tmdb_id > 0


def test_tmdb_service_returns_metadata_payload(monkeypatch):
    service = TMDbService()

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 123,
                "title": "Example Movie",
                "overview": "A film.",
                "poster_path": "/poster.jpg",
                "backdrop_path": "/backdrop.jpg",
                "release_date": "2024-01-01",
                "vote_average": 8.7,
                "vote_count": 42,
            }

    monkeypatch.setenv("TMDB_API_KEY", "demo-key")
    monkeypatch.setattr("app.tmdb_service.httpx.get", lambda *args, **kwargs: DummyResponse())

    result = service.get_movie_metadata(1)
    assert result["movieId"] == 1
    assert result["tmdbId"] == 123
    assert result["poster_url"].endswith("/w500/poster.jpg")
    assert result["backdrop_url"].endswith("/w1280/backdrop.jpg")
    assert result["title"] == "Example Movie"


def test_tmdb_endpoint_uses_service_override():
    service = MagicMock()
    service.get_movie_metadata.return_value = {
        "movieId": 42,
        "tmdbId": 987,
        "title": "Endpoint Movie",
        "overview": "Hello",
        "release_date": "2023-12-25",
        "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
        "backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
        "vote_average": 7.5,
        "vote_count": 77,
    }
    app.dependency_overrides[get_tmdb_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.get("/movies/42/metadata")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["title"] == "Endpoint Movie"


def test_tmdb_endpoint_rejects_invalid_movie_id():
    with TestClient(app) as client:
        response = client.get("/movies/0/metadata")
    assert response.status_code == 422

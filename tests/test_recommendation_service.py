from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.recommendation_service import MovieRecommendationService


@pytest.fixture
def service_with_mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = None

    service = MovieRecommendationService(driver=driver, database="neo4j")
    return service, session


def test_get_popular_movies_returns_expected_fields(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = [
        {"movie_id": 1, "title": "Toy Story", "average_rating": 4.5, "rating_count": 120},
        {"movie_id": 2, "title": "Jumanji", "average_rating": 4.2, "rating_count": 99},
    ]

    results = service.get_popular_movies(limit=2)

    assert len(results) == 2
    assert results[0]["movie_id"] == 1
    assert results[0]["title"] == "Toy Story"
    assert results[0]["average_rating"] == 4.5
    assert results[0]["rating_count"] == 120


def test_get_hidden_gems_returns_expected_fields(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = [
        {"movie_id": 42, "title": "Hidden gem", "average_rating": 4.8, "rating_count": 8},
    ]

    results = service.get_hidden_gems(limit=1)

    assert len(results) == 1
    assert results[0]["movie_id"] == 42
    assert results[0]["average_rating"] == 4.8
    assert results[0]["rating_count"] == 8


def test_get_similar_movies_returns_usable_result(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = [
        {
            "movie_id": 10,
            "title": "Similar Movie",
            "genre_similarity": 0.5,
            "audience_similarity": 0.4,
            "score": 0.45,
        }
    ]

    results = service.get_similar_movies(movie_id=5, limit=5)

    assert len(results) == 1
    assert results[0]["title"] == "Similar Movie"
    assert results[0]["genre_similarity"] == 0.5
    assert results[0]["audience_similarity"] == 0.4
    assert "Shared genre similarity" in results[0]["explanation"]


def test_get_personalized_recommendations_returns_collaborative_result(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = [
        {
            "movie_id": 99,
            "title": "Recommended Movie",
            "score": 17.6,
            "supporter_count": 4,
            "similar_users": [1, 2, 3, 4],
            "source": "collaborative",
        }
    ]

    results = service.get_personalized_recommendations(user_id=5, limit=5)

    assert len(results) == 1
    assert results[0]["movie_id"] == 99
    assert results[0]["title"] == "Recommended Movie"
    assert results[0]["score"] == 17.6
    assert results[0]["source"] == "collaborative"
    assert "Collaborative recommendation" in results[0]["explanation"]


def test_get_personalized_recommendations_returns_fallback_when_no_collaboration(service_with_mock_driver):
    service, session = service_with_mock_driver

    first_result = MagicMock()
    first_result.data.return_value = []

    second_result = MagicMock()
    second_result.data.return_value = [
        {"movie_id": 77, "title": "Strong fallback", "average_rating": 4.6, "rating_count": 40, "source": "fallback"},
    ]

    session.run.side_effect = [first_result, second_result]

    results = service.get_personalized_recommendations(user_id=99, limit=5)

    assert len(results) == 1
    assert results[0]["source"] == "fallback"
    assert "Fallback recommendation" in results[0]["explanation"]


def test_missing_or_invalid_ids_raise_value_error(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError):
        service.get_similar_movies(movie_id=0)

    with pytest.raises(ValueError):
        service.get_personalized_recommendations(user_id=0)

    with pytest.raises(ValueError):
        service.get_popular_movies(limit=0)

    with pytest.raises(ValueError):
        service.get_hidden_gems(limit=-5)


def test_empty_result_is_handled_gracefully(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = []

    assert service.get_popular_movies(limit=10) == []
    assert service.get_hidden_gems(limit=10) == []
    assert service.get_similar_movies(movie_id=999, limit=10) == []
    assert service.get_personalized_recommendations(user_id=999, limit=10) == []


def test_personalized_recommendations_handles_mocked_result_objects(service_with_mock_driver):
    service, session = service_with_mock_driver

    collaborative_result = MagicMock()
    collaborative_result.data.return_value = [
        {"movie_id": 88, "title": "Collaborative choice", "score": 16.5, "supporter_count": 2, "similar_users": [2, 3], "source": "collaborative"},
    ]

    session.run.return_value = collaborative_result

    results = service.get_personalized_recommendations(user_id=5, limit=5)

    assert len(results) == 1
    assert results[0]["source"] == "collaborative"
    assert results[0]["movie_id"] == 88


def test_personalized_recommendations_groups_supporters_by_candidate(service_with_mock_driver):
    service, session = service_with_mock_driver

    collaborative_result = MagicMock()
    collaborative_result.data.return_value = [
        {
            "movie_id": 88,
            "title": "Grouped candidate",
            "score": 4.5,
            "supporter_count": 2,
            "similar_users": [2, 5],
            "source": "collaborative",
        }
    ]

    session.run.return_value = collaborative_result

    results = service.get_personalized_recommendations(user_id=1, limit=5)

    assert len(results) == 1
    assert results[0]["movie_id"] == 88
    assert results[0]["supporter_count"] == 2
    assert set(results[0]["similar_users"]) == {2, 5}
    assert results[0]["source"] == "collaborative"

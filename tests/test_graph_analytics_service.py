from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.graph_analytics_service import GraphAnalyticsService


@pytest.fixture
def service_with_mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = None

    service = GraphAnalyticsService(driver=driver, database="neo4j")
    return service, session


def test_get_similar_users_returns_expected_values(service_with_mock_driver):
    service, session = service_with_mock_driver

    projection_exists = MagicMock()
    projection_exists.data.return_value = [{"projection_exists": True}]

    similarity_result = MagicMock()
    similarity_result.data.return_value = [
        {"user_id": 2, "score": 0.92},
        {"user_id": 3, "score": 0.87},
    ]

    session.run.side_effect = [projection_exists, similarity_result]

    results = service.get_similar_users(user_id=1, limit=2)

    assert len(results) == 2
    assert results[0]["user_id"] == 2
    assert results[0]["score"] == 0.92
    assert results[0]["source"] == "gds-node-similarity"


def test_get_similar_users_deduplicates_reverse_similarity_pairs(service_with_mock_driver):
    service, session = service_with_mock_driver

    projection_exists = MagicMock()
    projection_exists.data.return_value = [{"projection_exists": True}]

    similarity_result = MagicMock()
    similarity_result.data.return_value = [
        {"user_id": 145, "score": 0.7},
        {"user_id": 574, "score": 0.7},
        {"user_id": 145, "score": 0.6},
        {"user_id": 574, "score": 0.5},
        {"user_id": 130, "score": 1.0},
    ]

    session.run.side_effect = [projection_exists, similarity_result]

    results = service.get_similar_users(user_id=130, limit=5)

    assert len(results) == 2
    assert [item["user_id"] for item in results] == [145, 574]
    assert results[0]["score"] == 0.7
    assert results[1]["score"] == 0.7
    assert all(item["source"] == "gds-node-similarity" for item in results)


def test_get_user_communities_returns_community_data(service_with_mock_driver):
    service, session = service_with_mock_driver

    projection_exists = MagicMock()
    projection_exists.data.return_value = [{"projection_exists": True}]

    community_result = MagicMock()
    community_result.data.return_value = [
        {"community_id": 1, "user_count": 2, "user_ids": [10, 11]},
        {"community_id": 2, "user_count": 1, "user_ids": [42]},
    ]

    session.run.side_effect = [projection_exists, community_result]

    results = service.get_user_communities(limit=2)

    assert len(results) == 2
    assert results[0]["community_id"] == 1
    assert results[0]["user_count"] == 2
    assert results[0]["user_ids"] == [10, 11]


def test_get_similar_users_handles_missing_projection(service_with_mock_driver):
    service, session = service_with_mock_driver

    exists_result = MagicMock()
    exists_result.data.return_value = [{"projection_exists": False}]

    session.run.side_effect = [exists_result, RuntimeError("projection creation failed")]

    result = service.get_similar_users(user_id=1, limit=5)

    assert result == []


def test_get_user_communities_handles_missing_projection(service_with_mock_driver):
    service, session = service_with_mock_driver

    exists_result = MagicMock()
    exists_result.data.return_value = [{"projection_exists": False}]

    session.run.side_effect = [exists_result, RuntimeError("projection creation failed")]

    result = service.get_user_communities(limit=5)

    assert result == []


def test_find_user_path_returns_shortest_path(service_with_mock_driver):
    service, session = service_with_mock_driver

    path_result = MagicMock()
    path_result.data.return_value = [
        {
            "nodes": [
                {"type": "User", "id": 1, "title": None},
                {"type": "Movie", "id": 10, "title": "Toy Story"},
                {"type": "User", "id": 2, "title": None},
            ],
            "relationships": [
                {"type": "RATED", "from": 1, "to": 10},
                {"type": "RATED", "from": 10, "to": 2},
            ],
            "hop_count": 2,
        }
    ]
    session.run.return_value = path_result

    result = service.find_user_path(user_id_1=1, user_id_2=2)

    assert result["found"] is True
    assert result["path"]["hop_count"] == 2
    assert result["path"]["nodes"][1]["title"] == "Toy Story"


def test_find_user_movie_path_handles_no_path(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = []

    result = service.find_user_movie_path(user_id=1, movie_id=99)

    assert result["found"] is False
    assert result["path"]["nodes"] == []
    assert result["path"]["hop_count"] == 0


def test_path_validation_rejects_invalid_ids(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError):
        service.find_user_path(user_id_1=0, user_id_2=1)

    with pytest.raises(ValueError):
        service.find_user_movie_path(user_id=1, movie_id=-1)

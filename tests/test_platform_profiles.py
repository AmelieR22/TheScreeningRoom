from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_platform_profile_service, get_recommendation_service
from app.platform_profile_service import PlatformProfileService


@pytest.fixture
def service_with_mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = None
    service = PlatformProfileService(driver=driver, database="neo4j")
    return service, session


def test_create_platform_profile_returns_expected_fields(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.return_value = [
        {
            "platformUserId": "pf_123",
            "username": "alice",
            "createdAt": "2026-10-18T00:00:00Z",
        }
    ]

    result = service.create_platform_profile(username="alice")

    assert result["platformUserId"] == "pf_123"
    assert result["username"] == "alice"
    assert result["createdAt"] == "2026-10-18T00:00:00Z"


def test_create_platform_profile_rejects_invalid_username(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError):
        service.create_platform_profile(username="")

    with pytest.raises(ValueError):
        service.create_platform_profile(username="   ")

    with pytest.raises(ValueError):
        service.create_platform_profile(username="a" * 41)


def test_rating_validation_accepts_half_star_steps_and_rejects_invalid_values(service_with_mock_driver):
    service, _ = service_with_mock_driver

    assert service._validate_rating(0.5) == 0.5
    assert service._validate_rating(5.0) == 5.0
    assert service._validate_rating(3.5) == 3.5

    with pytest.raises(ValueError):
        service._validate_rating(0.0)

    with pytest.raises(ValueError):
        service._validate_rating(5.1)

    with pytest.raises(ValueError):
        service._validate_rating(1.25)


def test_watchlist_and_watched_methods_are_idempotent(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.side_effect = [
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"status": "ok"}],
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"status": "ok"}],
        [{"profile_count": 1}],
        [{"removed_count": 1}],
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"status": "ok"}],
    ]

    result = service.save_to_watchlist(profile_id="pf_123", movie_id=42)
    assert result["status"] == "added"

    result = service.mark_watched(profile_id="pf_123", movie_id=42)
    assert result["status"] == "watched"

    result = service.mark_unwatched(profile_id="pf_123", movie_id=42)
    assert result["status"] == "unwatched"

    result = service.remove_from_watchlist(profile_id="pf_123", movie_id=42)
    assert result["status"] == "removed"


def test_reaction_methods_clear_conflicts_and_support_like_dislike(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.side_effect = [
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"reaction": "LIKED", "movie_id": 7}],
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"reaction": "DISLIKED", "movie_id": 7}],
        [{"profile_count": 1}],
        [{"removed_count": 1}],
    ]

    result = service.set_reaction(profile_id="pf_123", movie_id=7, reaction="liked")
    assert result["reaction"] == "LIKED"

    result = service.set_reaction(profile_id="pf_123", movie_id=7, reaction="disliked")
    assert result["reaction"] == "DISLIKED"

    result = service.clear_reaction(profile_id="pf_123", movie_id=7)
    assert result["reaction"] == "cleared"


def test_set_rating_and_remove_rating_use_platform_relationship(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.side_effect = [
        [{"profile_count": 1}],
        [{"movie_count": 1}],
        [{"movie_id": 9, "rating": 4.5}],
        [{"profile_count": 1}],
        [{"status": "ok"}],
    ]

    result = service.set_rating(profile_id="pf_123", movie_id=9, rating=4.5)
    assert result["rating"] == 4.5

    remove_result = service.remove_rating(profile_id="pf_123", movie_id=9)
    assert remove_result["movie_id"] == 9


def test_platform_profile_endpoints_create_list_get_and_validate_inputs():
    service = MagicMock()
    service.list_platform_profiles.return_value = [{"platformUserId": "pf_1", "username": "alice"}]
    service.get_platform_profile.return_value = {"platformUserId": "pf_1", "username": "alice"}
    service.get_profile_activity.return_value = {
        "platformUserId": "pf_1",
        "username": "alice",
        "watchlist": [{"movie_id": 12, "title": "Moonlight"}],
        "watched": [{"movie_id": 9, "title": "Arrival"}],
        "reactions": [{"movie_id": 7, "title": "Parasite", "reaction": "liked"}],
        "ratings": [{"movie_id": 5, "title": "HER", "rating": 4.5}],
    }
    service.create_platform_profile.return_value = {"platformUserId": "pf_1", "username": "alice"}
    service.save_to_watchlist.return_value = {"status": "added"}
    service.remove_from_watchlist.return_value = {"status": "removed"}
    service.mark_watched.return_value = {"status": "watched"}
    service.mark_unwatched.return_value = {"status": "unwatched"}
    service.set_reaction.return_value = {"reaction": "liked", "movie_id": 12}
    service.clear_reaction.return_value = {"reaction": "cleared", "movie_id": 12}
    service.set_rating.return_value = {"movie_id": 12, "rating": 4.0}
    service.remove_rating.return_value = {"movie_id": 12, "rating": None}

    app.dependency_overrides[get_platform_profile_service] = lambda: service
    try:
        with TestClient(app) as client:
            create_response = client.post("/platform-users", json={"username": "alice"})
            list_response = client.get("/platform-users")
            get_response = client.get("/platform-users/pf_1")
            activity_response = client.get("/platform-users/pf_1/activity")
            watchlist_add = client.post("/platform-users/pf_1/watchlist", json={"movie_id": 12})
            watchlist_remove = client.delete("/platform-users/pf_1/watchlist/12")
            watched_add = client.post("/platform-users/pf_1/watched", json={"movie_id": 12})
            watched_remove = client.delete("/platform-users/pf_1/watched/12")
            liked = client.post("/platform-users/pf_1/reactions", json={"movie_id": 12, "reaction": "liked"})
            cleared = client.delete("/platform-users/pf_1/reactions/12")
            rated = client.post("/platform-users/pf_1/ratings", json={"movie_id": 12, "rating": 4.0})
            removed_rating = client.delete("/platform-users/pf_1/ratings/12")
            invalid = client.post("/platform-users", json={"username": ""})
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 200
    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert activity_response.status_code == 200
    assert activity_response.json()["watchlist"][0]["movie_id"] == 12
    assert watchlist_add.status_code == 200
    assert watchlist_remove.status_code == 200
    assert watched_add.status_code == 200
    assert watched_remove.status_code == 200
    assert liked.status_code == 200
    assert cleared.status_code == 200
    assert rated.status_code == 200
    assert removed_rating.status_code == 200
    assert invalid.status_code == 422


def test_platform_lookup_route_and_numeric_recommendation_route_stay_distinct():
    platform_service = MagicMock()
    platform_service.get_platform_profile_by_username.return_value = {
        "platformUserId": "pf_a9916765f2a4b978",
        "username": "amelie",
        "createdAt": "2026-10-18T00:00:00Z",
    }
    platform_service.get_platform_profile.return_value = {
        "platformUserId": "pf_a9916765f2a4b978",
        "username": "amelie",
        "createdAt": "2026-10-18T00:00:00Z",
    }

    recommendation_service = MagicMock()
    recommendation_service.get_personalized_recommendations.return_value = [
        {"movie_id": 1, "title": "Toy Story", "score": 0.91, "source": "collaborative"},
    ]
    recommendation_service.get_platform_profile_recommendations.return_value = [
        {"movie_id": 2, "title": "Profile pick", "score": 0.88, "source": "platform_profile"},
    ]

    app.dependency_overrides[get_platform_profile_service] = lambda: platform_service
    app.dependency_overrides[get_recommendation_service] = lambda: recommendation_service

    try:
        with TestClient(app) as client:
            lookup_response = client.get("/platform-users/lookup", params={"username": "amelie"})
            direct_response = client.get("/platform-users/pf_a9916765f2a4b978")
            numeric_response = client.get("/recommendations/personalized/1?limit=6")
    finally:
        app.dependency_overrides.clear()

    assert lookup_response.status_code == 200
    assert lookup_response.json()["username"] == "amelie"
    assert lookup_response.json()["platformUserId"] == "pf_a9916765f2a4b978"

    assert direct_response.status_code == 200
    assert direct_response.json()["platformUserId"] == "pf_a9916765f2a4b978"

    assert numeric_response.status_code == 200
    assert numeric_response.json()["items"][0]["movie_id"] == 1
    recommendation_service.get_personalized_recommendations.assert_called_once_with(user_id=1, limit=6)
    recommendation_service.get_platform_profile_recommendations.assert_not_called()


def test_film_community_join_leave_behaves_idempotently(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.run.return_value.data.side_effect = [
        [{"profile_count": 1}],
        [{"community_count": 0}],
        [{"communityId": 7, "communityKey": "community-7", "joined": True, "join_count": 1, "inferred_member_count": 12}],
        [{"profile_count": 1}],
        [{"communityId": 7, "communityName": "Community 7", "description": "Inferred audience cluster.", "dominantGenres": [], "inferredMemberCount": 12, "join_count": 1, "joined": True, "profile_id": "pf_123"}],
        [{"profile_count": 1}],
        [{"community_count": 0}],
        [{"communityId": 7, "communityName": "Community 7", "description": "Inferred audience cluster.", "dominantGenres": [], "inferredMemberCount": 12, "join_count": 0, "joined": False, "profile_id": "pf_123"}],
    ]

    joined = service.join_community(profile_id="pf_123", community_id=7)
    assert joined["communityId"] == 7
    assert joined["joined"] is True
    assert joined["join_count"] == 1

    membership = service.get_community_membership(profile_id="pf_123", community_id=7)
    assert membership["joined"] is True

    left = service.leave_community(profile_id="pf_123", community_id=7)
    assert left["joined"] is False
    assert left["join_count"] == 0


def test_platform_community_endpoints_expose_join_counts_and_louvain_membership():
    service = MagicMock()
    service.join_community.return_value = {
        "communityId": 7,
        "joined": True,
        "join_count": 1,
        "inferred_member_count": 12,
        "profile_id": "pf_123",
    }
    service.leave_community.return_value = {
        "communityId": 7,
        "joined": False,
        "join_count": 0,
        "inferred_member_count": 12,
        "profile_id": "pf_123",
    }
    service.get_community_membership.return_value = {
        "communityId": 7,
        "profile_id": "pf_123",
        "joined": True,
    }

    app.dependency_overrides[get_platform_profile_service] = lambda: service
    try:
        with TestClient(app) as client:
            join_response = client.post("/platform-users/pf_123/communities/7/join")
            membership_response = client.get("/platform-users/pf_123/communities/7/membership")
            leave_response = client.delete("/platform-users/pf_123/communities/7/leave")
    finally:
        app.dependency_overrides.clear()

    assert join_response.status_code == 200
    assert join_response.json()["joined"] is True
    assert join_response.json()["join_count"] == 1
    assert join_response.json()["inferred_member_count"] == 12
    assert membership_response.status_code == 200
    assert membership_response.json()["joined"] is True
    assert leave_response.status_code == 200
    assert leave_response.json()["joined"] is False
    assert leave_response.json()["join_count"] == 0


def test_platform_profile_endpoint_lists_joined_communities_for_my_profile():
    service = MagicMock()
    service.get_joined_communities.return_value = [
        {
            "communityId": 7,
            "communityName": "Action Fans",
            "description": "High-energy action movie enthusiasts.",
            "dominantGenres": ["Action"],
            "inferredMemberCount": 12,
            "joined": True,
        }
    ]

    app.dependency_overrides[get_platform_profile_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.get("/platform-users/pf_123/communities")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"][0]["communityName"] == "Action Fans"
    assert response.json()["items"][0]["joined"] is True


def test_platform_profile_service_preserves_movielens_data_modeling(service_with_mock_driver):
    service, _ = service_with_mock_driver

    assert service.PLATFORM_RATED_RELATIONSHIP == "PLATFORM_RATED"
    assert service.WANTS_TO_WATCH_RELATIONSHIP == "WANTS_TO_WATCH"
    assert service.WATCHED_RELATIONSHIP == "WATCHED"
    assert service.LIKED_RELATIONSHIP == "LIKED"
    assert service.DISLIKED_RELATIONSHIP == "DISLIKED"
    assert service.WANTS_TO_WATCH_RELATIONSHIP != "RATED"
    assert service.JOINED_RELATIONSHIP == "JOINED"

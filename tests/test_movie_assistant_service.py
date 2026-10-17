from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.movie_assistant_service import MovieAssistantService


@pytest.fixture
def service_with_mock_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = None
    session.execute_read.return_value = [{"movie_id": 1, "title": "Toy Story"}]

    service = MovieAssistantService(driver=driver, database="neo4j")
    return service, session


def test_popular_movies_intent_uses_allowlisted_template(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 1, "title": "Toy Story"}]

    result = service.ask("Show the most popular movies")

    assert result["question"] == "Show the most popular movies"
    assert "MATCH (m:Movie)<-[r:RATED]-(:User)" in result["generated_cypher"]
    assert "LIMIT $limit" in result["generated_cypher"]
    assert result["results"][0]["title"] == "Toy Story"


def test_ollama_classification_uses_allowlisted_top_genre_movies(service_with_mock_driver, monkeypatch):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 1, "title": "Toy Story"}]

    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": '{"intent": "top_genre_movies", "parameters": {"genre": "Comedy", "limit": 5}}'}

        return Response()

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    result = service.ask("Can you recommend five highly rated comedy films?")

    assert result["generated_cypher"].startswith("MATCH (:User)-[r:RATED]->(m:Movie)-[:IN_GENRE]->(:Genre {name: $genre})")
    assert result["results"][0]["title"] == "Toy Story"


def test_ollama_wrong_intent_is_corrected_for_genre_without_user_id(service_with_mock_driver, monkeypatch):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 2, "title": "Shrek"}]

    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": '{"intent": "user_recommendations", "parameters": {"limit": 5, "genre": "Comedy"}}'}

        return Response()

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    result = service.ask("Can you recommend five highly rated comedy films?")

    assert "top_genre_movies" in result["generated_cypher"] or "MATCH (:User)-[r:RATED]->(m:Movie)-[:IN_GENRE]->(:Genre {name: $genre})" in result["generated_cypher"]
    assert result["results"][0]["title"] == "Shrek"


def test_ollama_invalid_output_falls_back_to_deterministic_matcher(service_with_mock_driver, monkeypatch):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 3, "title": "Finding Nemo"}]

    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": '{"intent": "unknown"'}

        return Response()

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    result = service.ask("Show the most popular movies")

    assert result["generated_cypher"].startswith("MATCH (m:Movie)<-[r:RATED]-(:User)")
    assert result["results"][0]["title"] == "Finding Nemo"


def test_ollama_unavailable_falls_back_to_deterministic_matcher(service_with_mock_driver, monkeypatch):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 4, "title": "Cars"}]

    def fake_post(url, json, timeout):
        raise RuntimeError("not reachable")

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    result = service.ask("List the most common movie tags")

    assert "MATCH (:User)-[t:TAGGED]->(m:Movie)" in result["generated_cypher"]
    assert result["results"][0]["title"] == "Cars"


def test_attempted_ollama_injection_is_rejected(service_with_mock_driver, monkeypatch):
    service, _ = service_with_mock_driver

    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": '{"intent": "user_recommendations", "parameters": {"user_id": "bad", "limit": 5}}'}

        return Response()

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    with pytest.raises(ValueError):
        service.ask("Recommend movies for user bad")


def test_top_genre_movies_intent_supports_comedy_and_limit_five(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 1, "title": "Toy Story"}]

    result = service.ask("Find five highly rated comedy movies")

    assert result["question"] == "Find five highly rated comedy movies"
    assert "Genre {name: $genre}" in result["generated_cypher"]
    assert "LIMIT $limit" in result["generated_cypher"]
    assert result["results"][0]["title"] == "Toy Story"


def test_movie_details_intent_uses_parameterized_movie_id(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 42, "title": "The Matrix"}]

    result = service.ask("Show details for movie 42")

    assert result["generated_cypher"].startswith("MATCH (m:Movie {movieId: $movie_id})")
    assert result["results"][0]["title"] == "The Matrix"


def test_user_recommendations_intent_uses_parameterized_user_id(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 10, "title": "The Lion King"}]

    result = service.ask("Recommend movies for user 7")

    assert "MATCH (target:User {userId: $user_id})" in result["generated_cypher"]
    assert "LIMIT $limit" in result["generated_cypher"]
    assert result["results"][0]["title"] == "The Lion King"


def test_popular_tags_intent_uses_allowlist(service_with_mock_driver):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"tag": "funny", "movie_count": 15}]

    result = service.ask("List the most common movie tags")

    assert "MATCH (:User)-[t:TAGGED]->(m:Movie)" in result["generated_cypher"]
    assert result["results"][0]["tag"] == "funny"


def test_exact_incorrect_ollama_payload_is_corrected_to_top_genre_movies(service_with_mock_driver, monkeypatch):
    service, session = service_with_mock_driver
    session.execute_read.return_value = [{"movie_id": 1, "title": "Toy Story"}]

    def fake_post(url, json, timeout):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"content": '{"intent":"user_recommendations","genre":"comedy","limit":5}' }

        return Response()

    monkeypatch.setattr("app.movie_assistant_service.httpx.post", fake_post)

    result = service.ask("Can you recommend five highly rated comedy films?")

    assert result["generated_cypher"].startswith("MATCH (:User)-[r:RATED]->(m:Movie)-[:IN_GENRE]->(:Genre {name: $genre})")
    assert result["results"][0]["title"] == "Toy Story"


def test_invalid_limit_is_rejected():
    service = MovieAssistantService(driver=MagicMock(), database="neo4j")

    with pytest.raises(ValueError):
        service._normalize_limit(0)

    with pytest.raises(ValueError):
        service._normalize_limit(26)

    with pytest.raises(ValueError):
        service._normalize_limit("bad")


def test_invalid_movie_and_user_ids_are_rejected():
    service = MovieAssistantService(driver=MagicMock(), database="neo4j")

    with pytest.raises(ValueError):
        service._validate_positive_int(0, field_name="movie_id")

    with pytest.raises(ValueError):
        service._validate_positive_int(-1, field_name="user_id")


def test_invalid_genre_is_rejected():
    service = MovieAssistantService(driver=MagicMock(), database="neo4j")

    with pytest.raises(ValueError):
        service._validate_genre("Fantasy Fiction")


def test_unknown_question_is_rejected_before_execution(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError, match="Unknown question"):
        service.ask("Tell me a joke about the database")


def test_attempted_injection_is_rejected_by_allowlist(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError, match="allowlist|Multiple Cypher statements|comments"):
        service._validate_cypher("MATCH (m:Movie) RETURN m.title; CREATE (:Movie {title: 'bad'})")

    with pytest.raises(ValueError, match="allowlist|Multiple Cypher statements"):
        service._validate_cypher("MATCH (m:Movie) WHERE m.title = 'Comedy' RETURN m TITLE; CALL dbms.info()")


def test_ask_rejects_empty_question(service_with_mock_driver):
    service, _ = service_with_mock_driver

    with pytest.raises(ValueError):
        service.ask("   ")

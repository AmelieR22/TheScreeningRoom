"""Allowlisted movie assistant for safe, read-only MovieLens queries."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from neo4j import GraphDatabase, READ_ACCESS


class MovieAssistantService:
    """Allowlisted movie assistant for safe, read-only MovieLens queries.

    The future LLM will choose an intent and supply normalized parameters. It will
    never produce raw Cypher. All executable Cypher lives in fixed templates that
    the application owns and validates before execution.
    """

    DEFAULT_LIMIT = 10
    MAX_LIMIT = 25
    OLLAMA_TIMEOUT_SECONDS = 10.0

    GENRE_NAMES = [
        "Action",
        "Adventure",
        "Animation",
        "Children's",
        "Comedy",
        "Crime",
        "Documentary",
        "Drama",
        "Fantasy",
        "Film-Noir",
        "Horror",
        "Musical",
        "Mystery",
        "Romance",
        "Sci-Fi",
        "Thriller",
        "War",
        "Western",
    ]

    GENRE_LOOKUP = {
        "action": "Action",
        "adventure": "Adventure",
        "animation": "Animation",
        "children": "Children's",
        "children's": "Children's",
        "comedy": "Comedy",
        "crime": "Crime",
        "documentary": "Documentary",
        "drama": "Drama",
        "fantasy": "Fantasy",
        "film-noir": "Film-Noir",
        "film noir": "Film-Noir",
        "horror": "Horror",
        "musical": "Musical",
        "mystery": "Mystery",
        "romance": "Romance",
        "sci-fi": "Sci-Fi",
        "scifi": "Sci-Fi",
        "science fiction": "Sci-Fi",
        "thriller": "Thriller",
        "war": "War",
        "western": "Western",
    }

    QUERY_TEMPLATES = {
        "popular_movies": {
            "query": (
                "MATCH (m:Movie)<-[r:RATED]-(:User) "
                "WITH m, avg(toFloat(r.rating)) AS average_rating, "
                "count(r) AS rating_count "
                "WHERE rating_count >= 20 "
                "RETURN m.movieId AS movie_id, m.title AS title, "
                "round(average_rating, 2) AS average_rating, "
                "rating_count AS rating_count "
                "ORDER BY average_rating DESC, rating_count DESC "
                "LIMIT $limit"
            ),
            "description": "Return popular movies by rating count and average rating.",
        },
        "top_genre_movies": {
            "query": (
                "MATCH (:User)-[r:RATED]->(m:Movie)-[:IN_GENRE]->(:Genre {name: $genre}) "
                "WITH m, avg(toFloat(r.rating)) AS average_rating, "
                "count(r) AS rating_count "
                "WHERE rating_count >= 5 "
                "RETURN m.movieId AS movie_id, m.title AS title, "
                "round(average_rating, 2) AS average_rating, "
                "rating_count AS rating_count "
                "ORDER BY average_rating DESC, rating_count DESC "
                "LIMIT $limit"
            ),
            "description": "Return highly rated movies in a specific genre.",
        },
        "movie_details": {
            "query": (
                "MATCH (m:Movie {movieId: $movie_id}) "
                "OPTIONAL MATCH (m)-[:IN_GENRE]->(g:Genre) "
                "OPTIONAL MATCH (:User)-[r:RATED]->(m) "
                "WITH m, collect(DISTINCT g.name) AS genres, "
                "avg(toFloat(r.rating)) AS average_rating, "
                "count(r) AS rating_count "
                "RETURN m.movieId AS movie_id, m.title AS title, m.year AS year, "
                "genres AS genres, "
                "round(coalesce(average_rating, 0.0), 2) AS average_rating, "
                "coalesce(rating_count, 0) AS rating_count "
                "LIMIT $limit"
            ),
            "description": "Return a movie's metadata and aggregate rating summary.",
        },
        "user_recommendations": {
            "query": (
                "MATCH (target:User {userId: $user_id})-[target_rating:RATED]->"
                "(shared_movie:Movie)<-[other_rating:RATED]-(other:User) "
                "WHERE other.userId <> target.userId "
                "WITH other, "
                "collect({movieId: shared_movie.movieId, "
                "targetRating: toFloat(target_rating.rating), "
                "otherRating: toFloat(other_rating.rating)}) AS shared_ratings, "
                "count(DISTINCT shared_movie) AS overlap_count "
                "WHERE overlap_count >= 3 "
                "UNWIND shared_ratings AS item "
                "WITH other, avg(abs(item.targetRating - item.otherRating)) AS avg_rating_gap "
                "WITH other, 1.0 - (avg_rating_gap / 5.0) AS similarity "
                "MATCH (other)-[orating:RATED]->(candidate:Movie) "
                "WHERE NOT EXISTS { MATCH (:User {userId: $user_id})-[:RATED]->(candidate) } "
                "WITH candidate, "
                "collect({userId: other.userId, similarity: similarity, "
                "rating: toFloat(orating.rating)}) AS support_rows "
                "WITH candidate, support_rows, "
                "reduce(totalWeightedRating = 0.0, row IN support_rows | "
                "totalWeightedRating + row.similarity * row.rating) AS weighted_sum, "
                "reduce(totalSimilarity = 0.0, row IN support_rows | "
                "totalSimilarity + row.similarity) AS total_similarity "
                "WITH candidate, CASE WHEN total_similarity = 0 THEN 0.0 "
                "ELSE weighted_sum / total_similarity END AS normalized_score "
                "RETURN candidate.movieId AS movie_id, candidate.title AS title, "
                "round(normalized_score, 4) AS score "
                "ORDER BY score DESC, candidate.movieId ASC "
                "LIMIT $limit"
            ),
            "description": "Return collaborative recommendations for a user.",
        },
        "popular_tags": {
            "query": (
                "MATCH (:User)-[t:TAGGED]->(m:Movie) "
                "WITH t.tag AS tag, count(DISTINCT m) AS movie_count "
                "RETURN tag AS tag, movie_count AS movie_count "
                "ORDER BY movie_count DESC, tag ASC "
                "LIMIT $limit"
            ),
            "description": "Return the most common movie tags.",
        },
    }

    def __init__(self, driver: Any | None = None, database: str | None = None) -> None:
        if driver is not None:
            self.driver = driver
            self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
        else:
            self.database = os.getenv("NEO4J_DATABASE", "neo4j")
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            username = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "change_me")

            if not password:
                raise ValueError(
                    "NEO4J_PASSWORD is not set. Add it to your environment before running the movie assistant."
                )

            self.driver = GraphDatabase.driver(
                uri,
                auth=(username, password),
                max_connection_pool_size=20,
            )

        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

    def _validate_question(self, question: str) -> str:
        if not isinstance(question, str):
            raise ValueError("Question must be a string.")

        cleaned = question.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty.")

        if len(cleaned) > 500:
            raise ValueError("Question is too long. Use at most 500 characters.")

        return cleaned

    def _normalize_limit(self, limit: int) -> int:
        try:
            normalized = int(limit)
        except (TypeError, ValueError) as exc:  # pragma: no cover - simple validation path
            raise ValueError("limit must be an integer from 1 to 25.") from exc

        if normalized < 1 or normalized > self.MAX_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {self.MAX_LIMIT}.")

        return normalized

    def _validate_positive_int(self, value: int, *, field_name: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - simple validation path
            raise ValueError(f"{field_name} must be a positive integer.") from exc

        if normalized <= 0:
            raise ValueError(f"{field_name} must be a positive integer.")

        return normalized

    def _validate_genre(self, genre: str) -> str:
        if not isinstance(genre, str):
            raise ValueError("genre must be a string.")

        normalized = genre.strip()
        if not normalized:
            raise ValueError("genre cannot be empty.")

        key = normalized.lower()
        if key not in self.GENRE_LOOKUP:
            allowed = ", ".join(self.GENRE_NAMES)
            raise ValueError(f"Unsupported genre '{genre}'. Allowed values: {allowed}.")

        return self.GENRE_LOOKUP[key]

    def _canonicalize_query(self, query: str) -> str:
        return re.sub(r"\s+", " ", query.strip())

    def _validate_cypher(self, cypher: str) -> str:
        if not isinstance(cypher, str):
            raise ValueError("Generated Cypher must be a string.")

        cleaned = cypher.strip()
        if not cleaned:
            raise ValueError("Generated Cypher is empty.")

        if ";" in cleaned:
            raise ValueError("Multiple Cypher statements are not allowed.")

        if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
            raise ValueError("Cypher comments are not allowed.")

        if not re.match(r"(?is)^\s*(OPTIONAL\s+MATCH|MATCH)\b", cleaned):
            raise ValueError("Queries must start with MATCH or OPTIONAL MATCH.")

        normalized = self._canonicalize_query(cleaned)
        allowed_queries = {
            self._canonicalize_query(details["query"]) for details in self.QUERY_TEMPLATES.values()
        }
        if normalized not in allowed_queries:
            raise ValueError("Query is not in the approved allowlist.")

        limit_match = re.search(r"(?is)\bLIMIT\s+(\$?\w+|\d+)\b", cleaned)
        if limit_match:
            limit_value = limit_match.group(1)
            if limit_value.startswith("$"):
                pass
            else:
                if int(limit_value) > self.MAX_LIMIT:
                    raise ValueError(f"LIMIT must be at most {self.MAX_LIMIT}.")

        return cleaned

    def _extract_limit(self, question: str) -> int:
        match = re.search(r"\b(\d+)\b", question)
        if match:
            candidate = int(match.group(1))
            if 1 <= candidate <= self.MAX_LIMIT:
                return candidate
        return self.DEFAULT_LIMIT

    def _extract_movie_id(self, question: str) -> int:
        match = re.search(r"\bmovie\s*(?:id\s*)?(\d+)\b|\b(\d+)\b", question, flags=re.IGNORECASE)
        if match:
            candidate = next(group for group in match.groups() if group is not None)
            return self._validate_positive_int(candidate, field_name="movie_id")
        raise ValueError("Movie details questions must include a positive movie_id.")

    def _extract_user_id(self, question: str) -> int:
        patterns = [
            r"\buser\s*(?:id)?\s*(?:#|=)?\s*(\d+)\b",
            r"\bfor\s+user\s+(\d+)\b",
            r"\buser\s+(\d+)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1)
                return self._validate_positive_int(candidate, field_name="user_id")
        raise ValueError("Recommendation questions must include a positive user_id.")

    def _extract_genre(self, question: str) -> str:
        normalized = question.lower()
        for key, value in self.GENRE_LOOKUP.items():
            if key in normalized:
                return value
        raise ValueError("No valid MovieLens genre was found in the question.")

    def _normalize_genre_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        normalized = value.strip()
        if not normalized:
            return None
        return self.GENRE_LOOKUP.get(normalized.lower()) or self.GENRE_LOOKUP.get(normalized.lower().replace("_", " "))

    def _detect_genre_in_question(self, question: str) -> str | None:
        normalized = question.lower()
        for key in self.GENRE_LOOKUP:
            if key in normalized:
                return self.GENRE_LOOKUP[key]
        return None

    def _resolve_intent(self, question: str) -> tuple[str, dict[str, Any]]:
        """Resolve a natural-language question to an allowlisted template intent."""
        normalized = question.lower()
        detected_genre = self._detect_genre_in_question(question)

        explicit_user_id_match = re.search(
            r"\buser\s*(?:id)?\s*(?:#|=)?\s*(\d+)\b|\bfor\s+user\s+(\d+)\b|\buser\s+(\d+)\b",
            question,
            flags=re.IGNORECASE,
        )
        explicit_user_id = None
        if explicit_user_id_match:
            groups = explicit_user_id_match.groups()
            explicit_user_id = next(group for group in groups if group is not None)

        limit = self._normalize_limit(self._extract_limit(question))

        if detected_genre is not None and explicit_user_id is None:
            return "top_genre_movies", {"genre": detected_genre, "limit": limit}

        if "popular" in normalized or "top movies" in normalized:
            return "popular_movies", {"limit": limit}

        if "tag" in normalized and (
            "popular" in normalized
            or "most common" in normalized
            or "top tag" in normalized
        ):
            return "popular_tags", {"limit": limit}

        if "recommend" in normalized or "for user" in normalized or (
            "user" in normalized and "movie" in normalized
        ):
            if explicit_user_id is None:
                raise ValueError("Recommendation questions must include a positive user_id.")
            normalized_user_id = self._validate_positive_int(
                explicit_user_id,
                field_name="user_id",
            )
            return "user_recommendations", {"user_id": normalized_user_id, "limit": limit}

        if "detail" in normalized or "info" in normalized:
            return "movie_details", {"movie_id": self._extract_movie_id(question), "limit": 1}

        if "movie" in normalized and re.search(r"\b\d+\b", question):
            return "movie_details", {"movie_id": self._extract_movie_id(question), "limit": 1}

        if detected_genre is not None:
            return "top_genre_movies", {
                "genre": self._validate_genre(detected_genre),
                "limit": limit,
            }

        if "tag" in normalized:
            return "popular_tags", {"limit": limit}

        raise ValueError(
            "Unknown question. Supported intents are: popular_movies, "
            "top_genre_movies, movie_details, user_recommendations, and "
            "popular_tags."
        )

    def _normalize_ollama_intent(self, question: str, payload: Any) -> tuple[str, dict[str, Any]]:
        """Normalize and validate a JSON intent payload from Ollama."""
        if not isinstance(payload, dict):
            raise ValueError("Ollama response must be a JSON object.")

        raw_intent = payload.get("intent")
        if not isinstance(raw_intent, str):
            raise ValueError("Ollama response is missing an intent.")

        intent = raw_intent.strip().lower()
        if intent not in self.QUERY_TEMPLATES:
            raise ValueError(f"Unsupported intent from Ollama: {raw_intent!r}")

        parameters = payload.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError("Ollama parameters must be a JSON object.")

        detected_genre = self._detect_genre_in_question(question)
        normalized_genre = self._normalize_genre_value(parameters.get("genre"))
        normalized_genre = normalized_genre or detected_genre

        if intent == "user_recommendations":
            user_id_value = parameters.get("user_id")
            if normalized_genre is not None and user_id_value is None:
                limit = self._normalize_limit(parameters.get("limit", self.DEFAULT_LIMIT))
                return "top_genre_movies", {"genre": normalized_genre, "limit": limit}

            if user_id_value is None:
                raise ValueError("user_recommendations requires a valid user_id.")

            user_id = self._validate_positive_int(user_id_value, field_name="user_id")
            limit = self._normalize_limit(parameters.get("limit", self.DEFAULT_LIMIT))
            return "user_recommendations", {"user_id": user_id, "limit": limit}

        if intent == "top_genre_movies":
            genre_value = normalized_genre or parameters.get("genre")
            if genre_value is None:
                raise ValueError("top_genre_movies requires a valid genre.")
            genre = self._validate_genre(str(genre_value))
            limit = self._normalize_limit(parameters.get("limit", self.DEFAULT_LIMIT))
            return "top_genre_movies", {"genre": genre, "limit": limit}

        if intent == "movie_details":
            movie_id_value = parameters.get("movie_id")
            if movie_id_value is None:
                movie_id_value = self._extract_movie_id(question)
            movie_id = self._validate_positive_int(movie_id_value, field_name="movie_id")
            limit = self._normalize_limit(parameters.get("limit", 1))
            return "movie_details", {"movie_id": movie_id, "limit": limit}

        if intent == "popular_movies":
            limit = self._normalize_limit(parameters.get("limit", self.DEFAULT_LIMIT))
            return "popular_movies", {"limit": limit}

        if intent == "popular_tags":
            limit = self._normalize_limit(parameters.get("limit", self.DEFAULT_LIMIT))
            return "popular_tags", {"limit": limit}

        raise ValueError(f"Unsupported intent: {intent}")

    def _call_ollama(self, question: str) -> Any:
        prompt = (
            "Return JSON only. Do not generate Cypher. "
            "Classify the question into one of these intents and return parameters: "
            "popular_movies, top_genre_movies, movie_details, user_recommendations, popular_tags. "
            "Use JSON like {'intent': 'top_genre_movies', 'parameters': {'genre': 'Comedy', 'limit': 5}}. "
            "If a genre is mentioned and no valid user_id is supplied, prefer top_genre_movies. "
            "Ensure valid positive integer IDs, limit between 1 and 25. "
            f"Question: {question}"
        )

        try:
            response = httpx.post(
                f"{self.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0, "top_p": 0.2},
                },
                timeout=self.OLLAMA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except (httpx.HTTPError, OSError, ValueError):
            raise RuntimeError("Ollama is unavailable.") from None

        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError("Malformed JSON response from Ollama.") from exc

        content = data.get("content")
        if not isinstance(content, str):
            if isinstance(data, dict) and any(key in data for key in ("intent", "parameters")):
                return data
            raise ValueError("Malformed JSON response from Ollama.")

        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Ollama returned an empty response.")

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("Malformed JSON response from Ollama.") from exc

        return parsed

    def _classify_with_ollama(self, question: str) -> tuple[str, dict[str, Any]]:
        """Classify the question using the configured Ollama model."""
        payload = self._call_ollama(question)
        return self._normalize_ollama_intent(question, payload)

    def _generate_safe_cypher(self, intent: str, parameters: dict[str, Any]) -> str:
        """Return an allowlisted Cypher query for the selected intent."""
        _ = parameters
        template = self.QUERY_TEMPLATES.get(intent)
        if template is None:
            raise ValueError(f"Unsupported intent '{intent}'.")

        query = template["query"]
        self._validate_cypher(query)
        return query

    def _run_read_query(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            with self.driver.session(database=self.database, default_access_mode=READ_ACCESS) as session:
                def _transaction(tx):
                    return tx.run(query, parameters or {}, timeout=5).data()

                return session.execute_read(_transaction)
        except Exception as exc:  # pragma: no cover - runtime integration path
            raise RuntimeError("Movie assistant is currently unavailable.") from exc

    def get_supported_intents(self) -> list[str]:
        """Return the supported allowlisted assistant intents."""
        return sorted(self.QUERY_TEMPLATES)

    def ask(self, question: str) -> dict[str, Any]:
        """Answer a question using the allowlisted movie assistant queries."""
        cleaned_question = self._validate_question(question)

        try:
            intent, parameters = self._classify_with_ollama(cleaned_question)
        except (RuntimeError, ValueError):
            intent, parameters = self._resolve_intent(cleaned_question)

        generated_cypher = self._generate_safe_cypher(intent, parameters)
        self._validate_cypher(generated_cypher)

        results = self._run_read_query(generated_cypher, parameters)

        explanation = (
            "This answer is produced from a fixed, allowlisted MovieLens query "
            "template and a read-only Neo4j session. The assistant does not "
            "modify the database."
        )

        return {
            "question": cleaned_question,
            "generated_cypher": generated_cypher,
            "results": results,
            "explanation": explanation,
        }

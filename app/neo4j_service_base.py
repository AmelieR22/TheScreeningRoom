"""Shared Neo4j service helpers used by recommendation and analytics modules."""

from __future__ import annotations

import os
from typing import Any

from neo4j import GraphDatabase


class Neo4jServiceBase:
    """Common validation and query execution helpers for Neo4j-backed services."""

    def __init__(
        self,
        driver: Any | None = None,
        database: str | None = None,
        *,
        service_name: str,
    ) -> None:
        if driver is not None:
            self.driver = driver
            self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")
            return

        self.database = os.getenv("NEO4J_DATABASE", "neo4j")
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        username = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "change_me")

        if not password:
            raise ValueError(
                f"NEO4J_PASSWORD is not set. Add it to your environment before "
                f"running the {service_name} service."
            )

        self.driver = GraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_pool_size=20,
        )

    def _normalize_limit(self, limit: int, *, minimum: int = 1) -> int:
        try:
            normalized = int(limit)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("Limit must be an integer value.") from exc

        if normalized < minimum:
            raise ValueError(f"Limit must be at least {minimum}.")

        return normalized

    def _validate_movie_id(self, movie_id: int) -> int:
        try:
            normalized = int(movie_id)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("movie_id must be an integer.") from exc

        if normalized <= 0:
            raise ValueError("movie_id must be greater than zero.")

        return normalized

    def _validate_user_id(self, user_id: int) -> int:
        try:
            normalized = int(user_id)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("user_id must be an integer.") from exc

        if normalized <= 0:
            raise ValueError("user_id must be greater than zero.")

        return normalized

    def _run_read_query(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, parameters or {})
                rows = result.data()
            return rows
        except Exception as exc:  # pragma: no cover - runtime integration path
            raise RuntimeError(f"Neo4j query failed: {exc}") from exc

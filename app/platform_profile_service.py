"""Persistent platform profile interactions in Neo4j, separate from imported MovieLens users."""

from __future__ import annotations

import hashlib
from typing import Any

from app.neo4j_service_base import Neo4jServiceBase


class PlatformProfileService(Neo4jServiceBase):
    """Manage personal platform profiles and profile-specific movie interactions."""

    WANTS_TO_WATCH_RELATIONSHIP = "WANTS_TO_WATCH"
    WATCHED_RELATIONSHIP = "WATCHED"
    LIKED_RELATIONSHIP = "LIKED"
    DISLIKED_RELATIONSHIP = "DISLIKED"
    PLATFORM_RATED_RELATIONSHIP = "PLATFORM_RATED"
    JOINED_RELATIONSHIP = "JOINED"

    def __init__(self, driver: Any | None = None, database: str | None = None) -> None:
        super().__init__(driver, database, service_name="platform profile")

    def _validate_username(self, username: str) -> str:
        if not isinstance(username, str):
            raise ValueError("Username must be a string.")

        cleaned = username.strip()
        if not cleaned:
            raise ValueError("Username cannot be blank.")
        if len(cleaned) < 3 or len(cleaned) > 40:
            raise ValueError("Username must be between 3 and 40 characters.")
        if not all(char.isalnum() or char in "._-" for char in cleaned):
            raise ValueError("Username may only contain letters, numbers, dots, underscores, and hyphens.")
        if not cleaned[0].isalnum():
            raise ValueError("Username must start with a letter or number.")
        return cleaned

    def _validate_profile_id(self, profile_id: str) -> str:
        if not isinstance(profile_id, str):
            raise ValueError("profile_id must be a string.")
        cleaned = profile_id.strip()
        if not cleaned:
            raise ValueError("profile_id cannot be blank.")
        return cleaned

    def _validate_movie_id(self, movie_id: int) -> int:
        try:
            normalized = int(movie_id)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("movie_id must be an integer.") from exc

        if normalized <= 0:
            raise ValueError("movie_id must be greater than zero.")
        return normalized

    def _validate_rating(self, rating: float) -> float:
        try:
            normalized = float(rating)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("rating must be a numeric value.") from exc

        if normalized < 0.5 or normalized > 5.0:
            raise ValueError("rating must be between 0.5 and 5.0.")
        if abs((normalized * 2) - round(normalized * 2)) > 1e-9:
            raise ValueError("rating must be in 0.5 increments.")
        return normalized

    def _format_parameterized_profile_response(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "platformUserId": row.get("platformUserId"),
            "username": row.get("username"),
            "createdAt": row.get("createdAt"),
        }

    def ensure_platform_profile_constraints(self) -> None:
        queries = [
            "CREATE CONSTRAINT platform_user_id IF NOT EXISTS FOR (p:PlatformUser) REQUIRE p.platformUserId IS UNIQUE",
            "CREATE CONSTRAINT platform_user_username IF NOT EXISTS FOR (p:PlatformUser) REQUIRE p.username IS UNIQUE",
            "CREATE CONSTRAINT movie_movieId IF NOT EXISTS FOR (m:Movie) REQUIRE m.movieId IS UNIQUE",
            "CREATE CONSTRAINT film_community_id IF NOT EXISTS FOR (c:FilmCommunity) REQUIRE c.communityId IS UNIQUE",
        ]
        for query in queries:
            try:
                self._run_write_query(query)
            except RuntimeError:
                continue

    def _validate_community_id(self, community_id: int) -> int:
        try:
            normalized = int(community_id)
        except (TypeError, ValueError) as exc:  # pragma: no cover - validation path
            raise ValueError("community_id must be an integer.") from exc

        if normalized <= 0:
            raise ValueError("community_id must be greater than zero.")
        return normalized

    def ensure_film_community(
        self,
        community_id: int,
        *,
        inferred_name: str | None = None,
        description: str | None = None,
        dominant_genres: list[str] | None = None,
        inferred_member_count: int | None = None,
    ) -> dict[str, Any]:
        normalized_community_id = self._validate_community_id(community_id)
        normalized_name = (inferred_name or f"Community {normalized_community_id}").strip() or f"Community {normalized_community_id}"
        normalized_description = (description or "Inferred audience cluster.").strip() or "Inferred audience cluster."
        normalized_genres = []
        if dominant_genres is not None:
            normalized_genres = [str(genre).strip() for genre in dominant_genres if str(genre or "").strip()]
            normalized_genres = list(dict.fromkeys(normalized_genres))
        normalized_count = int(inferred_member_count) if inferred_member_count is not None else 0

        query = """
        MERGE (c:FilmCommunity {communityId: $community_id})
        ON CREATE SET c.communityKey = $community_key,
                      c.createdAt = datetime()
        SET c.communityKey = $community_key,
            c.communityName = $inferred_name,
            c.description = $description,
            c.dominantGenres = $dominant_genres,
            c.inferredMemberCount = $inferred_member_count
        RETURN c.communityId AS communityId,
               c.communityName AS communityName,
               c.description AS description,
               c.dominantGenres AS dominantGenres,
               c.inferredMemberCount AS inferredMemberCount
        """
        rows = self._run_write_query(
            query,
            {
                "community_id": normalized_community_id,
                "community_key": f"community-{normalized_community_id}",
                "inferred_name": normalized_name,
                "description": normalized_description,
                "dominant_genres": normalized_genres,
                "inferred_member_count": normalized_count,
            },
        )
        if not rows:
            raise RuntimeError("Failed to ensure FilmCommunity node exists.")
        row = rows[0]
        return {
            "communityId": int(row.get("communityId") or normalized_community_id),
            "communityName": row.get("communityName") or normalized_name,
            "description": row.get("description") or normalized_description,
            "dominantGenres": row.get("dominantGenres") or normalized_genres,
            "inferredMemberCount": int(row.get("inferredMemberCount") or normalized_count),
        }

    def join_community(self, profile_id: str, community_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_community_id = self._validate_community_id(community_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")

        self.ensure_film_community(
            normalized_community_id,
            inferred_name=f"Community {normalized_community_id}",
            description="Inferred audience cluster.",
            dominant_genres=[],
            inferred_member_count=0,
        )

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id}), (c:FilmCommunity {communityId: $community_id})
        MERGE (p)-[r:JOINED]->(c)
        WITH p, c
        OPTIONAL MATCH (c)<-[all:JOINED]-(:PlatformUser)
        RETURN c.communityId AS communityId,
               c.communityName AS communityName,
               c.description AS description,
               c.dominantGenres AS dominantGenres,
               coalesce(c.inferredMemberCount, 0) AS inferredMemberCount,
               count(all) AS join_count,
               true AS joined,
               p.platformUserId AS profile_id
        """
        rows = self._run_write_query(
            query,
            {"profile_id": cleaned_id, "community_id": normalized_community_id},
        )
        if not rows:
            raise RuntimeError(f"Failed to join community {normalized_community_id}.")

        row = rows[0]
        return {
            "communityId": int(row.get("communityId") or normalized_community_id),
            "profile_id": row.get("profile_id") or cleaned_id,
            "joined": bool(row.get("joined")),
            "join_count": int(row.get("join_count") or 0),
            "inferred_member_count": int(row.get("inferredMemberCount") or 0),
            "communityName": row.get("communityName") or f"Community {normalized_community_id}",
            "description": row.get("description") or "Inferred audience cluster.",
            "dominantGenres": row.get("dominantGenres") or [],
        }

    def leave_community(self, profile_id: str, community_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_community_id = self._validate_community_id(community_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")

        self.ensure_film_community(
            normalized_community_id,
            inferred_name=f"Community {normalized_community_id}",
            description="Inferred audience cluster.",
            dominant_genres=[],
            inferred_member_count=0,
        )

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[r:JOINED]->(c:FilmCommunity {communityId: $community_id})
        DELETE r
        WITH c
        OPTIONAL MATCH (c)<-[remaining:JOINED]-(:PlatformUser)
        RETURN c.communityId AS communityId,
               c.communityName AS communityName,
               c.description AS description,
               c.dominantGenres AS dominantGenres,
               coalesce(c.inferredMemberCount, 0) AS inferredMemberCount,
               count(remaining) AS join_count,
               false AS joined,
               $profile_id AS profile_id
        """
        rows = self._run_write_query(
            query,
            {"profile_id": cleaned_id, "community_id": normalized_community_id},
        )
        if not rows:
            rows = [{
                "communityId": normalized_community_id,
                "communityName": f"Community {normalized_community_id}",
                "description": "Inferred audience cluster.",
                "dominantGenres": [],
                "inferredMemberCount": 0,
                "join_count": 0,
                "joined": False,
                "profile_id": cleaned_id,
            }]

        row = rows[0]
        return {
            "communityId": int(row.get("communityId") or normalized_community_id),
            "profile_id": row.get("profile_id") or cleaned_id,
            "joined": bool(row.get("joined")),
            "join_count": int(row.get("join_count") or 0),
            "inferred_member_count": int(row.get("inferredMemberCount") or 0),
            "communityName": row.get("communityName") or f"Community {normalized_community_id}",
            "description": row.get("description") or "Inferred audience cluster.",
            "dominantGenres": row.get("dominantGenres") or [],
        }

    def get_community_membership(self, profile_id: str, community_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_community_id = self._validate_community_id(community_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})
        OPTIONAL MATCH (p)-[joined:JOINED]->(c:FilmCommunity {communityId: $community_id})
        OPTIONAL MATCH (c)<-[all:JOINED]-(:PlatformUser)
        RETURN c.communityId AS communityId,
               c.communityName AS communityName,
               c.description AS description,
               c.dominantGenres AS dominantGenres,
               coalesce(c.inferredMemberCount, 0) AS inferredMemberCount,
               count(all) AS join_count,
               CASE WHEN joined IS NOT NULL THEN true ELSE false END AS joined,
               p.platformUserId AS profile_id
        """
        rows = self._run_read_query(
            query,
            {"profile_id": cleaned_id, "community_id": normalized_community_id},
        )
        if not rows:
            return {
                "communityId": normalized_community_id,
                "profile_id": cleaned_id,
                "joined": False,
                "join_count": 0,
                "inferred_member_count": 0,
                "communityName": f"Community {normalized_community_id}",
                "description": "Inferred audience cluster.",
                "dominantGenres": [],
            }

        row = rows[0]
        return {
            "communityId": int(row.get("communityId") or normalized_community_id),
            "profile_id": row.get("profile_id") or cleaned_id,
            "joined": bool(row.get("joined")),
            "join_count": int(row.get("join_count") or 0),
            "inferred_member_count": int(row.get("inferredMemberCount") or 0),
            "communityName": row.get("communityName") or f"Community {normalized_community_id}",
            "description": row.get("description") or "Inferred audience cluster.",
            "dominantGenres": row.get("dominantGenres") or [],
        }

    def get_joined_communities(self, profile_id: str) -> list[dict[str, Any]]:
        cleaned_id = self._validate_profile_id(profile_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[:JOINED]->(c:FilmCommunity)
        RETURN c.communityId AS communityId,
               c.communityName AS communityName,
               c.description AS description,
               c.dominantGenres AS dominantGenres,
               coalesce(c.inferredMemberCount, 0) AS inferredMemberCount
        ORDER BY c.communityName ASC, c.communityId ASC
        """
        rows = self._run_read_query(query, {"profile_id": cleaned_id})
        return [
            {
                "communityId": int(row.get("communityId") or 0),
                "communityName": row.get("communityName") or "Community",
                "description": row.get("description") or "Inferred audience cluster.",
                "dominantGenres": row.get("dominantGenres") or [],
                "inferredMemberCount": int(row.get("inferredMemberCount") or 0),
                "joined": True,
            }
            for row in rows
        ]

    def create_platform_profile(self, username: str) -> dict[str, Any]:
        cleaned_username = self._validate_username(username)
        digest = hashlib.sha256(cleaned_username.encode("utf-8")).hexdigest()[:16]
        profile_id = f"pf_{digest}"
        query = """
        MERGE (p:PlatformUser {username: $username})
        ON CREATE SET p.platformUserId = $platform_user_id,
                      p.createdAt = datetime()
        WITH p
        RETURN p.platformUserId AS platformUserId,
               p.username AS username,
               p.createdAt AS createdAt
        """
        rows = self._run_write_query(
            query,
            {"username": cleaned_username, "platform_user_id": profile_id},
        )
        if not rows:
            raise RuntimeError("Failed to create platform profile.")
        return self._format_parameterized_profile_response(rows[0])

    def _profile_exists(self, profile_id: str) -> bool:
        cleaned_id = self._validate_profile_id(profile_id)
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})
        RETURN count(p) AS profile_count
        """
        rows = self._run_read_query(query, {"profile_id": cleaned_id})
        return bool(rows and int(rows[0].get("profile_count") or 0) > 0)

    def list_platform_profiles(self) -> list[dict[str, Any]]:
        query = """
        MATCH (p:PlatformUser)
        RETURN p.platformUserId AS platformUserId,
               p.username AS username,
               p.createdAt AS createdAt
        ORDER BY p.username ASC
        """
        rows = self._run_read_query(query)
        return [self._format_parameterized_profile_response(row) for row in rows]

    def get_platform_profile(self, profile_id: str) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})
        RETURN p.platformUserId AS platformUserId,
               p.username AS username,
               p.createdAt AS createdAt
        """
        rows = self._run_read_query(query, {"profile_id": cleaned_id})
        if not rows:
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        return self._format_parameterized_profile_response(rows[0])

    def get_platform_profile_by_username(self, username: str) -> dict[str, Any]:
        cleaned_username = self._validate_username(username)
        query = """
        MATCH (p:PlatformUser {username: $username})
        RETURN p.platformUserId AS platformUserId,
               p.username AS username,
               p.createdAt AS createdAt
        """
        rows = self._run_read_query(query, {"username": cleaned_username})
        if not rows:
            raise ValueError(f"Platform profile '{cleaned_username}' was not found.")
        return self._format_parameterized_profile_response(rows[0])

    def get_profile_activity(self, profile_id: str) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})
        OPTIONAL MATCH (p)-[watchlist:WANTS_TO_WATCH]->(watchMovie:Movie)
        OPTIONAL MATCH (p)-[watched:WATCHED]->(watchedMovie:Movie)
        OPTIONAL MATCH (p)-[liked:LIKED]->(likedMovie:Movie)
        OPTIONAL MATCH (p)-[disliked:DISLIKED]->(dislikedMovie:Movie)
        OPTIONAL MATCH (p)-[rated:PLATFORM_RATED]->(ratedMovie:Movie)
        RETURN collect(DISTINCT {movie_id: watchMovie.movieId, title: watchMovie.title}) AS watchlist,
               collect(DISTINCT {movie_id: watchedMovie.movieId, title: watchedMovie.title}) AS watched,
               collect(DISTINCT {movie_id: likedMovie.movieId, title: likedMovie.title, reaction: 'liked'}) AS liked,
               collect(DISTINCT {movie_id: dislikedMovie.movieId, title: dislikedMovie.title, reaction: 'disliked'}) AS disliked,
               collect(DISTINCT {movie_id: ratedMovie.movieId, title: ratedMovie.title, rating: toFloat(rated.rating)}) AS ratings
        """
        rows = self._run_read_query(query, {"profile_id": cleaned_id})
        row = rows[0] if rows else {}

        def normalize_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
            normalized: list[dict[str, Any]] = []
            for item in items or []:
                if item is None:
                    continue
                movie_id = item.get("movie_id")
                if movie_id is None:
                    continue
                normalized.append({
                    "movie_id": int(movie_id),
                    "title": item.get("title") or f"Movie {movie_id}",
                    **({"reaction": item.get("reaction")} if "reaction" in item else {}),
                    **({"rating": float(item.get("rating"))} if "rating" in item else {}),
                })
            return normalized

        activities = self.get_platform_profile(cleaned_id)
        return {
            "platformUserId": cleaned_id,
            "username": activities.get("username"),
            "watchlist": normalize_items(row.get("watchlist") or []),
            "watched": normalize_items(row.get("watched") or []),
            "reactions": normalize_items((row.get("liked") or []) + (row.get("disliked") or [])),
            "ratings": normalize_items(row.get("ratings") or []),
        }

    def _movie_exists(self, movie_id: int) -> bool:
        normalized_movie_id = self._validate_movie_id(movie_id)
        query = """
        MATCH (m:Movie {movieId: $movie_id})
        RETURN count(m) AS movie_count
        """
        rows = self._run_read_query(query, {"movie_id": normalized_movie_id})
        return bool(rows and int(rows[0].get("movie_count") or 0) > 0)

    def save_to_watchlist(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        if not self._movie_exists(normalized_movie_id):
            raise ValueError(f"Movie {normalized_movie_id} does not exist.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id}), (m:Movie {movieId: $movie_id})
        MERGE (p)-[r:WANTS_TO_WATCH]->(m)
        RETURN p.platformUserId AS platformUserId, m.movieId AS movie_id, type(r) AS relationship
        """
        self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"status": "added", "platformUserId": cleaned_id, "movie_id": normalized_movie_id}

    def remove_from_watchlist(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[r:WANTS_TO_WATCH]->(m:Movie {movieId: $movie_id})
        DELETE r
        RETURN count(r) AS removed_count
        """
        rows = self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"status": "removed", "platformUserId": cleaned_id, "movie_id": normalized_movie_id, "removed_count": int((rows[0].get("removed_count") if rows else 0) or 0)}

    def mark_watched(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        if not self._movie_exists(normalized_movie_id):
            raise ValueError(f"Movie {normalized_movie_id} does not exist.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id}), (m:Movie {movieId: $movie_id})
        WITH p, m
        OPTIONAL MATCH (p)-[old:WANTS_TO_WATCH]->(m)
        DELETE old
        WITH p, m
        MERGE (p)-[r:WATCHED]->(m)
        RETURN p.platformUserId AS platformUserId, m.movieId AS movie_id, type(r) AS relationship
        """
        self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"status": "watched", "platformUserId": cleaned_id, "movie_id": normalized_movie_id}

    def mark_unwatched(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[r:WATCHED]->(m:Movie {movieId: $movie_id})
        DELETE r
        RETURN count(r) AS removed_count
        """
        rows = self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"status": "unwatched", "platformUserId": cleaned_id, "movie_id": normalized_movie_id, "removed_count": int((rows[0].get("removed_count") if rows else 0) or 0)}

    def set_reaction(self, profile_id: str, movie_id: int, reaction: str) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        cleaned_reaction = reaction.strip().lower()
        if cleaned_reaction not in {"liked", "disliked"}:
            raise ValueError("Reaction must be 'liked' or 'disliked'.")
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        if not self._movie_exists(normalized_movie_id):
            raise ValueError(f"Movie {normalized_movie_id} does not exist.")

        query = f"""
        MATCH (p:PlatformUser {{platformUserId: $profile_id}}), (m:Movie {{movieId: $movie_id}})
        WITH p, m
        OPTIONAL MATCH (p)-[existing:LIKED]->(m)
        OPTIONAL MATCH (p)-[other:DISLIKED]->(m)
        DELETE existing, other
        WITH p, m
        MERGE (p)-[r:{cleaned_reaction.upper()}]->(m)
        RETURN p.platformUserId AS platformUserId, m.movieId AS movie_id, type(r) AS reaction
        """

        rows = self._run_write_query(
            query,
            {"profile_id": cleaned_id, "movie_id": normalized_movie_id},
        )
        relation = rows[0].get("reaction") if rows else cleaned_reaction
        return {"platformUserId": cleaned_id, "movie_id": normalized_movie_id, "reaction": relation}

    def clear_reaction(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[r]->(m:Movie {movieId: $movie_id})
        WHERE type(r) IN ['LIKED', 'DISLIKED']
        DELETE r
        RETURN count(r) AS removed_count
        """
        rows = self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"platformUserId": cleaned_id, "movie_id": normalized_movie_id, "reaction": "cleared", "removed_count": int((rows[0].get("removed_count") if rows else 0) or 0)}

    def set_rating(self, profile_id: str, movie_id: int, rating: float) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        normalized_rating = self._validate_rating(rating)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        if not self._movie_exists(normalized_movie_id):
            raise ValueError(f"Movie {normalized_movie_id} does not exist.")

        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id}), (m:Movie {movieId: $movie_id})
        WITH p, m
        OPTIONAL MATCH (p)-[existing:PLATFORM_RATED]->(m)
        DELETE existing
        WITH p, m
        MERGE (p)-[r:PLATFORM_RATED {rating: $rating}]->(m)
        RETURN p.platformUserId AS platformUserId, m.movieId AS movie_id, r.rating AS rating
        """
        rows = self._run_write_query(
            query,
            {"profile_id": cleaned_id, "movie_id": normalized_movie_id, "rating": normalized_rating},
        )
        if not rows:
            raise RuntimeError("Failed to set platform rating.")
        return {"platformUserId": cleaned_id, "movie_id": normalized_movie_id, "rating": float(rows[0].get("rating") or 0.0)}

    def remove_rating(self, profile_id: str, movie_id: int) -> dict[str, Any]:
        cleaned_id = self._validate_profile_id(profile_id)
        normalized_movie_id = self._validate_movie_id(movie_id)
        if not self._profile_exists(cleaned_id):
            raise ValueError(f"Platform profile '{cleaned_id}' was not found.")
        query = """
        MATCH (p:PlatformUser {platformUserId: $profile_id})-[r:PLATFORM_RATED]->(m:Movie {movieId: $movie_id})
        DELETE r
        RETURN p.platformUserId AS platformUserId, m.movieId AS movie_id
        """
        self._run_write_query(query, {"profile_id": cleaned_id, "movie_id": normalized_movie_id})
        return {"platformUserId": cleaned_id, "movie_id": normalized_movie_id, "rating": None}

"""Graph analytics queries for the MovieLens graph using Neo4j GDS."""

from __future__ import annotations

from typing import Any

from app.neo4j_service_base import Neo4jServiceBase


class GraphAnalyticsService(Neo4jServiceBase):
    """Graph analytics queries for the MovieLens graph using Neo4j GDS.

    The service keeps the Neo4j connection pattern consistent with the existing
    recommendation service and creates an in-memory projection only when needed.
    """

    PROJECTION_NAME = "screening-room-ratings"

    def __init__(self, driver: Any | None = None, database: str | None = None) -> None:
        """Initialize the analytics service with a Neo4j driver and database name."""
        super().__init__(driver, database, service_name="graph analytics")

    def _ensure_projection_exists(self) -> bool:
        """Create the in-memory projection if it does not exist.

        We intentionally return False instead of raising when GDS is unavailable,
        which keeps the API useful even if the plugin is not installed yet.
        """
        try:
            rows = self._run_read_query(
                """
                CALL gds.graph.exists($projection_name) YIELD exists
                RETURN exists AS projection_exists
                """,
                {"projection_name": self.PROJECTION_NAME},
            )
        except RuntimeError:
            return False

        if not rows:
            return False

        if rows[0].get("projection_exists"):
            return True

        try:
            self._run_read_query(
                """
                CALL gds.graph.project(
                    $projection_name,
                    ['User', 'Movie'],
                    {RATED: {type: 'RATED', orientation: 'UNDIRECTED'}}
                )
                YIELD graphName, nodeCount, relationshipCount
                RETURN graphName AS graph_name,
                       nodeCount AS node_count,
                       relationshipCount AS relationship_count
                """,
                {"projection_name": self.PROJECTION_NAME},
            )
            return True
        except RuntimeError:
            return False

    def get_similar_users(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Return the most similar users using GDS Node Similarity.

        The projected graph contains both User and Movie nodes but we filter the
        output back to User nodes only. We intentionally do not use sourceNodeFilter
        or targetNodeFilter because GDS 2.12.0 rejects those parameters.

        GDS returns both directions of a similarity pair, so we deduplicate by
        retaining the highest similarity score for each other user before applying
        the caller's limit.
        """
        normalized_user_id = self._validate_user_id(user_id)
        normalized_limit = self._normalize_limit(limit, minimum=1)

        if not self._ensure_projection_exists():
            return []

        query = """
        MATCH (source:User {userId: $user_id})
        CALL gds.nodeSimilarity.stream($projection_name) YIELD node1, node2, similarity
        WITH source, node1, node2, similarity
        WHERE node1 = id(source) OR node2 = id(source)
        WITH source, node1, node2, similarity
        MATCH (other:User)
        WHERE id(other) = CASE WHEN node1 = id(source) THEN node2 ELSE node1 END
          AND other.userId <> $user_id
        RETURN other.userId AS user_id,
               similarity AS score
        ORDER BY score DESC, other.userId ASC
        """

        rows = self._run_read_query(
            query,
            {
                "user_id": normalized_user_id,
                "projection_name": self.PROJECTION_NAME,
            },
        )

        best_scores: dict[int, float] = {}
        for row in rows:
            other_user_id = int(row["user_id"])
            if other_user_id == normalized_user_id:
                continue

            score = float(row["score"])
            if other_user_id not in best_scores or score > best_scores[other_user_id]:
                best_scores[other_user_id] = score

        ranked_users = sorted(best_scores.items(), key=lambda item: (-item[1], item[0]))
        limited_users = ranked_users[:normalized_limit]

        return [
            {
                "user_id": user_id,
                "score": round(float(score), 4),
                "source": "gds-node-similarity",
            }
            for user_id, score in limited_users
        ]

    def _build_community_summary(self, community_id: int, user_ids: list[int], dominant_genres: list[str]) -> dict[str, str | list[str]]:
        """Create a brief, evidence-driven summary for a community."""
        cleaned_genres = [str(genre).strip() for genre in dominant_genres if str(genre or "").strip()]
        normalized_genres = list(dict.fromkeys(cleaned_genres))[:3]

        if normalized_genres:
            if len(normalized_genres) == 1:
                title = f"{normalized_genres[0]}-leaning cluster"
                description = (
                    f"This group skews toward {normalized_genres[0]} based on the films its members rated. "
                    f"{len(user_ids)} members are represented in this inferred interest cluster."
                )
            else:
                title = f"{normalized_genres[0]} + {normalized_genres[1]} cluster"
                description = (
                    f"This community shows a clear mix of {normalized_genres[0]} and {normalized_genres[1]} "
                    f"among its {len(user_ids)} members, based on shared movie ratings."
                )
            return {
                "title": title,
                "description": description,
                "dominant_genres": normalized_genres,
            }

        title = f"Sparse viewer cluster #{community_id}"
        description = (
            "This community has no genre evidence yet; it may be small or lightly connected. "
            "The members are preserved as numeric MovieLens users only."
        )
        return {
            "title": title,
            "description": description,
            "dominant_genres": [],
        }

    def _get_community_genres(self, user_ids: list[int]) -> list[str]:
        """Collect the dominant genres among a community's members from their ratings."""
        if not user_ids:
            return []

        query = """
        MATCH (user:User)
        WHERE user.userId IN $user_ids
        MATCH (user)-[:RATED]->(movie:Movie)-[:IN_GENRE]->(genre:Genre)
        WITH genre.name AS genre, count(DISTINCT movie.movieId) AS genre_count
        RETURN genre AS genre,
               genre_count AS genre_count
        ORDER BY genre_count DESC, genre ASC
        LIMIT 3
        """

        rows = self._run_read_query(query, {"user_ids": user_ids})
        genres = [row.get("genre") for row in rows if row.get("genre")]
        return [str(genre) for genre in genres]

    def get_user_communities(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return user communities using GDS Louvain.

        The community IDs are returned from the GDS projection, then filtered so
        only User nodes contribute to the final result set.
        """
        normalized_limit = self._normalize_limit(limit, minimum=1)

        if not self._ensure_projection_exists():
            return []

        query = """
        CALL gds.louvain.stream($projection_name)
        YIELD nodeId, communityId
        WITH communityId AS community_id, collect(nodeId) AS node_ids
        UNWIND node_ids AS node_id
        MATCH (user:User)
        WHERE id(user) = node_id
        WITH community_id, collect(user.userId) AS user_ids
        WHERE size(user_ids) > 0
        RETURN community_id AS community_id,
               size(user_ids) AS user_count,
               user_ids AS user_ids
        ORDER BY user_count DESC, community_id ASC
        LIMIT $limit
        """

        rows = self._run_read_query(
            query,
            {
                "projection_name": self.PROJECTION_NAME,
                "limit": normalized_limit,
            },
        )

        results: list[dict[str, Any]] = []
        for row in rows:
            user_ids = [int(user_id) for user_id in (row.get("user_ids") or [])]
            dominant_genres = self._get_community_genres(user_ids)
            summary = self._build_community_summary(int(row["community_id"]), user_ids, dominant_genres)
            results.append(
                {
                    "community_id": int(row["community_id"]),
                    "user_count": int(row["user_count"]),
                    "user_ids": user_ids,
                    "dominant_genres": summary["dominant_genres"],
                    "title": summary["title"],
                    "description": summary["description"],
                }
            )

        return results

    def resolve_platform_user_identifier(self, identifier: str) -> dict[str, Any]:
        """Resolve a username or platform ID to a PlatformUser node."""
        cleaned = (identifier or "").strip()
        if not cleaned:
            raise ValueError("User identifier cannot be blank.")

        query = """
        MATCH (p:PlatformUser)
        WHERE p.platformUserId = $identifier OR p.username = $identifier
        RETURN p.platformUserId AS platformUserId,
               p.username AS username
        LIMIT 1
        """
        rows = self._run_read_query(query, {"identifier": cleaned})
        if not rows:
            raise ValueError(f"No platform profile matched '{cleaned}'.")
        row = rows[0]
        return {
            "platformUserId": row.get("platformUserId"),
            "username": row.get("username"),
        }

    def get_similar_platform_users(self, identifier: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return platform users with the most overlapping liked films."""
        normalized_limit = self._normalize_limit(limit, minimum=1)
        source = self.resolve_platform_user_identifier(identifier)
        profile_id = source.get("platformUserId")
        username = source.get("username")

        if not profile_id:
            return []

        query = """
        MATCH (source:PlatformUser {platformUserId: $profile_id})-[:LIKED]->(movie:Movie)
        WITH source, collect(DISTINCT movie.movieId) AS source_liked
        MATCH (other:PlatformUser)-[:LIKED]->(shared:Movie)
        WHERE other.platformUserId <> $profile_id AND shared.movieId IN source_liked
        WITH other, collect(DISTINCT shared.movieId) AS shared_movies, size(source_liked) AS source_like_count
        MATCH (other)-[:LIKED]->(other_movie:Movie)
        WITH other, shared_movies, source_like_count, count(DISTINCT other_movie) AS other_like_count
        WITH other,
             size(shared_movies) AS shared_count,
             source_like_count,
             other_like_count,
             CASE
                 WHEN source_like_count + other_like_count = 0 THEN 0.0
                 ELSE toFloat(size(shared_movies)) / toFloat(source_like_count + other_like_count - size(shared_movies))
             END AS score
        WHERE score > 0
        RETURN other.platformUserId AS platformUserId,
               other.username AS username,
               round(score, 4) AS score
        ORDER BY score DESC, other.username ASC
        LIMIT $limit
        """

        rows = self._run_read_query(
            query,
            {"profile_id": profile_id, "limit": normalized_limit},
        )

        return [
            {
                "user_id": row.get("platformUserId"),
                "username": row.get("username") or row.get("platformUserId"),
                "score": round(float(row.get("score") or 0.0), 4),
                "source": "platform-like-overlap",
                "label": row.get("username") or f"Platform profile {row.get('platformUserId')}",
            }
            for row in rows
        ]

    def get_similar_users_by_identifier(self, identifier: str | int, limit: int = 5) -> list[dict[str, Any]]:
        """Return similar users for numeric MovieLens IDs or platform user identifiers."""
        if isinstance(identifier, int):
            return self.get_similar_users(identifier, limit=limit)

        cleaned = str(identifier).strip()
        if not cleaned:
            raise ValueError("User identifier cannot be blank.")

        if cleaned.isdigit():
            return self.get_similar_users(int(cleaned), limit=limit)

        return self.get_similar_platform_users(cleaned, limit=limit)

    def find_user_path(self, user_id_1: int, user_id_2: int) -> dict[str, Any]:
        """Find a shortest path between two users via shared movie ratings."""
        normalized_user_id_1 = self._validate_user_id(user_id_1)
        normalized_user_id_2 = self._validate_user_id(user_id_2)

        query = """
        MATCH (start:User {userId: $user_id_1}), (end:User {userId: $user_id_2})
        MATCH p = shortestPath((start)-[:RATED*..6]-(end))
        WITH p,
             nodes(p) AS path_nodes,
             relationships(p) AS path_relationships
        RETURN [node IN path_nodes | {
            type: CASE WHEN 'Movie' IN labels(node) THEN 'Movie' ELSE 'User' END,
            id: CASE WHEN 'Movie' IN labels(node) THEN node.movieId ELSE node.userId END,
            title: CASE WHEN 'Movie' IN labels(node) THEN node.title ELSE null END
        }] AS nodes,
        [rel IN path_relationships | {
            type: type(rel),
            from: CASE WHEN 'Movie' IN labels(startNode(rel)) THEN startNode(rel).movieId ELSE startNode(rel).userId END,
            to: CASE WHEN 'Movie' IN labels(endNode(rel)) THEN endNode(rel).movieId ELSE endNode(rel).userId END
        }] AS relationships,
        length(p) AS hop_count
        """

        rows = self._run_read_query(
            query,
            {
                "user_id_1": normalized_user_id_1,
                "user_id_2": normalized_user_id_2,
            },
        )

        if not rows:
            return {
                "found": False,
                "path": {"nodes": [], "relationships": [], "hop_count": 0},
                "message": "No path found between the two users.",
            }

        row = rows[0]
        return {
            "found": True,
            "path": {
                "nodes": row.get("nodes") or [],
                "relationships": row.get("relationships") or [],
                "hop_count": int(row.get("hop_count") or 0),
            },
        }

    def find_user_movie_path(self, user_id: int, movie_id: int) -> dict[str, Any]:
        """Find a shortest path between a user and a movie using rated connections."""
        normalized_user_id = self._validate_user_id(user_id)
        normalized_movie_id = self._validate_movie_id(movie_id)

        query = """
        MATCH (start:User {userId: $user_id}), (end:Movie {movieId: $movie_id})
        MATCH p = shortestPath((start)-[:RATED*..6]-(end))
        WITH p,
             nodes(p) AS path_nodes,
             relationships(p) AS path_relationships
        RETURN [node IN path_nodes | {
            type: CASE WHEN 'Movie' IN labels(node) THEN 'Movie' ELSE 'User' END,
            id: CASE WHEN 'Movie' IN labels(node) THEN node.movieId ELSE node.userId END,
            title: CASE WHEN 'Movie' IN labels(node) THEN node.title ELSE null END
        }] AS nodes,
        [rel IN path_relationships | {
            type: type(rel),
            from: CASE WHEN 'Movie' IN labels(startNode(rel)) THEN startNode(rel).movieId ELSE startNode(rel).userId END,
            to: CASE WHEN 'Movie' IN labels(endNode(rel)) THEN endNode(rel).movieId ELSE endNode(rel).userId END
        }] AS relationships,
        length(p) AS hop_count
        """

        rows = self._run_read_query(
            query,
            {
                "user_id": normalized_user_id,
                "movie_id": normalized_movie_id,
            },
        )

        if not rows:
            return {
                "found": False,
                "path": {"nodes": [], "relationships": [], "hop_count": 0},
                "message": "No path found between the user and the movie.",
            }

        row = rows[0]
        return {
            "found": True,
            "path": {
                "nodes": row.get("nodes") or [],
                "relationships": row.get("relationships") or [],
                "hop_count": int(row.get("hop_count") or 0),
            },
        }

    def find_user_path_by_identifier(self, user_identifier_1: str | int, user_identifier_2: str | int) -> dict[str, Any]:
        """Find a shortest path for either MovieLens or PlatformUser identifiers."""
        if isinstance(user_identifier_1, int):
            normalized_a = self._validate_user_id(user_identifier_1)
            if isinstance(user_identifier_2, int):
                return self.find_user_path(normalized_a, self._validate_user_id(user_identifier_2))
            return self.find_platform_user_path_by_identifier(str(user_identifier_2), normalized_a)

        if isinstance(user_identifier_2, int):
            return self.find_platform_user_path_by_identifier(str(user_identifier_1), self._validate_user_id(user_identifier_2))

        cleaned_a = str(user_identifier_1).strip()
        cleaned_b = str(user_identifier_2).strip()
        if not cleaned_a or not cleaned_b:
            raise ValueError("User identifiers cannot be blank.")

        if cleaned_a.isdigit() and cleaned_b.isdigit():
            return self.find_user_path(int(cleaned_a), int(cleaned_b))

        if cleaned_a.isdigit() and not cleaned_b.isdigit():
            return self.find_platform_user_path_by_identifier(cleaned_b, int(cleaned_a))

        if cleaned_b.isdigit() and not cleaned_a.isdigit():
            return self.find_platform_user_path_by_identifier(cleaned_a, int(cleaned_b))

        return self.find_platform_user_path_by_identifier(cleaned_a, cleaned_b)

    def find_platform_user_path_by_identifier(self, first_identifier: str | int, second_identifier: str | int) -> dict[str, Any]:
        """Find the shortest path between two platform users via shared likes and watched films."""
        if isinstance(first_identifier, int):
            first = self._validate_user_id(first_identifier)
            second = self._validate_user_id(second_identifier)
            if isinstance(second_identifier, int):
                return self.find_user_path(first, second)
            second_profile = self.resolve_platform_user_identifier(str(second_identifier))
            return self.find_platform_user_path_by_identifier(first_profile_id := second_profile.get("platformUserId"), first)

        if isinstance(second_identifier, int):
            second_profile = self.resolve_platform_user_identifier(str(first_identifier))
            return self.find_platform_user_path_by_identifier(second_profile.get("platformUserId"), second_identifier)

        first_profile = self.resolve_platform_user_identifier(str(first_identifier))
        second_profile = self.resolve_platform_user_identifier(str(second_identifier))
        first_id = first_profile.get("platformUserId")
        second_id = second_profile.get("platformUserId")

        query = """
        MATCH (start:PlatformUser {platformUserId: $first_id}), (end:PlatformUser {platformUserId: $second_id})
        MATCH p = shortestPath((start)-[:LIKED|WATCHED|WANTS_TO_WATCH*..6]-(end))
        WITH p,
             nodes(p) AS path_nodes,
             relationships(p) AS path_relationships
        RETURN [node IN path_nodes | {
            type: CASE WHEN 'Movie' IN labels(node) THEN 'Movie' ELSE 'PlatformUser' END,
            id: CASE WHEN 'Movie' IN labels(node) THEN node.movieId ELSE node.platformUserId END,
            title: CASE WHEN 'Movie' IN labels(node) THEN node.title ELSE node.username END,
            username: CASE WHEN 'PlatformUser' IN labels(node) THEN node.username ELSE null END
        }] AS nodes,
        [rel IN path_relationships | {
            type: type(rel),
            from: CASE WHEN 'Movie' IN labels(startNode(rel)) THEN startNode(rel).movieId ELSE startNode(rel).platformUserId END,
            to: CASE WHEN 'Movie' IN labels(endNode(rel)) THEN endNode(rel).movieId ELSE endNode(rel).platformUserId END
        }] AS relationships,
        length(p) AS hop_count
        """

        rows = self._run_read_query(
            query,
            {
                "first_id": first_id,
                "second_id": second_id,
            },
        )

        if not rows:
            return {
                "found": False,
                "path": {"nodes": [], "relationships": [], "hop_count": 0},
                "message": "No connection was found between those platform profiles.",
            }

        row = rows[0]
        return {
            "found": True,
            "path": {
                "nodes": row.get("nodes") or [],
                "relationships": row.get("relationships") or [],
                "hop_count": int(row.get("hop_count") or 0),
            },
        }

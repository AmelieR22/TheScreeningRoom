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

        return [
            {
                "community_id": int(row["community_id"]),
                "user_count": int(row["user_count"]),
                "user_ids": [int(user_id) for user_id in (row.get("user_ids") or [])],
            }
            for row in rows
        ]

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

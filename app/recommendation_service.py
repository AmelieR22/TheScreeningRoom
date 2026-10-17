"""Movie recommendation queries against the Neo4j MovieLens graph."""

from __future__ import annotations

from typing import Any

from app.neo4j_service_base import Neo4jServiceBase


class MovieRecommendationService(Neo4jServiceBase):
    """Recommendation queries for the MovieLens graph stored in Neo4j.

    The service is designed for beginner-friendly graph querying and keeps all
    database access behind parameterized Cypher queries.
    """

    def __init__(self, driver: Any | None = None, database: str | None = None) -> None:
        """Initialize the recommendation service with a Neo4j driver and database."""
        super().__init__(driver, database, service_name="recommendation")

    def get_popular_movies(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return historically popular movies based on average rating and rating count.

        Popularity is based on historical MovieLens ratings, not live trends.
        """
        normalized_limit = self._normalize_limit(limit, minimum=1)

        query = """
        MATCH (m:Movie)<-[r:RATED]-(:User)
        WITH m, count(r) AS rating_count, avg(toFloat(r.rating)) AS average_rating
        WHERE rating_count >= 20
        RETURN m.movieId AS movie_id,
               m.title AS title,
               round(average_rating, 2) AS average_rating,
               rating_count AS rating_count
        ORDER BY average_rating DESC, rating_count DESC
        LIMIT $limit
        """

        rows = self._run_read_query(query, {"limit": normalized_limit})
        return [
            {
                "movie_id": int(row["movie_id"]),
                "title": row["title"],
                "average_rating": round(float(row["average_rating"]), 2),
                "rating_count": int(row["rating_count"]),
            }
            for row in rows
        ]

    def get_hidden_gems(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return high-quality movies with relatively few ratings.

        A minimum rating count avoids unstable recommendations caused by tiny sample sizes.
        """
        normalized_limit = self._normalize_limit(limit, minimum=1)

        query = """
        MATCH (m:Movie)<-[r:RATED]-(:User)
        WITH m, count(r) AS rating_count, avg(toFloat(r.rating)) AS average_rating
        WHERE rating_count >= 5 AND rating_count <= 50 AND average_rating >= 4.3
        RETURN m.movieId AS movie_id,
               m.title AS title,
               round(average_rating, 2) AS average_rating,
               rating_count AS rating_count
        ORDER BY average_rating DESC, rating_count ASC
        LIMIT $limit
        """

        rows = self._run_read_query(query, {"limit": normalized_limit})
        return [
            {
                "movie_id": int(row["movie_id"]),
                "title": row["title"],
                "average_rating": round(float(row["average_rating"]), 2),
                "rating_count": int(row["rating_count"]),
            }
            for row in rows
        ]

    def get_similar_movies(self, movie_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Return movies similar to the target movie using normalized graph similarity.

        The score blends Jaccard-style genre similarity with normalized audience overlap,
        so highly popular movies do not dominate the ranking purely because they have many viewers.
        """
        normalized_movie_id = self._validate_movie_id(movie_id)
        normalized_limit = self._normalize_limit(limit, minimum=1)

        query = """
        MATCH (source:Movie {movieId: $movie_id})
        MATCH (source)<-[:RATED]-(source_user:User)
        WITH source, count(DISTINCT source_user) AS source_rater_count

        MATCH (source)-[:IN_GENRE]->(source_genre)
        WITH source, source_rater_count, collect(DISTINCT source_genre.name) AS source_genres

        MATCH (candidate:Movie)
        WHERE candidate.movieId <> $movie_id

        OPTIONAL MATCH (candidate)-[:IN_GENRE]->(candidate_genre)
        WITH source, candidate, source_rater_count, source_genres,
             coalesce(collect(DISTINCT candidate_genre.name), []) AS candidate_genres
        WITH source, candidate, source_rater_count, source_genres, candidate_genres,
             size([g IN source_genres WHERE g IN candidate_genres]) AS shared_genre_count,
             size(source_genres) AS source_genre_total,
             size(candidate_genres) AS candidate_genre_total

        WITH candidate,
             CASE
                 WHEN source_genre_total + candidate_genre_total - shared_genre_count = 0 THEN 0.0
                 ELSE toFloat(shared_genre_count) / toFloat(source_genre_total + candidate_genre_total - shared_genre_count)
             END AS genre_similarity,
             source_rater_count,
             candidate_genre_total

        OPTIONAL MATCH (candidate)<-[:RATED]-(candidate_user:User)
        WITH candidate, genre_similarity, source_rater_count, count(DISTINCT candidate_user) AS candidate_rater_count

        OPTIONAL MATCH (source)<-[:RATED]-(shared_user:User)-[:RATED]->(candidate)
        WITH candidate, genre_similarity, source_rater_count, candidate_rater_count,
             count(DISTINCT shared_user) AS shared_user_count
        WITH candidate,
             genre_similarity,
             source_rater_count,
             candidate_rater_count,
             shared_user_count,
             CASE
                 WHEN source_rater_count = 0 OR candidate_rater_count = 0 THEN 0.0
                 ELSE toFloat(shared_user_count) / sqrt(toFloat(source_rater_count) * toFloat(candidate_rater_count))
             END AS audience_similarity
        WITH candidate,
             genre_similarity,
             audience_similarity,
             (0.55 * genre_similarity + 0.45 * audience_similarity) AS score
        RETURN candidate.movieId AS movie_id,
               candidate.title AS title,
               round(genre_similarity, 4) AS genre_similarity,
               round(audience_similarity, 4) AS audience_similarity,
               round(score, 4) AS score
        ORDER BY score DESC, candidate.movieId ASC
        LIMIT $limit
        """

        rows = self._run_read_query(query, {"movie_id": normalized_movie_id, "limit": normalized_limit})

        recommendations: list[dict[str, Any]] = []
        for row in rows:
            genre_similarity = float(row.get("genre_similarity") or 0.0)
            audience_similarity = float(row.get("audience_similarity") or 0.0)
            score = float(row.get("score") or 0.0)

            if genre_similarity > 0 and audience_similarity > 0:
                explanation = (
                    f"Shared genre similarity {genre_similarity:.3f} and audience overlap {audience_similarity:.3f} "
                    f"suggest these movies are closely related to the target film."
                )
            elif genre_similarity > 0:
                explanation = (
                    f"Shared genre similarity {genre_similarity:.3f} makes this a strong thematic match."
                )
            elif audience_similarity > 0:
                explanation = (
                    f"Audience overlap {audience_similarity:.3f} suggests viewers liked similar titles."
                )
            else:
                explanation = "Weak similarity signal from genres and audience overlap."

            recommendations.append(
                {
                    "movie_id": int(row["movie_id"]),
                    "title": row["title"],
                    "score": round(score, 4),
                    "genre_similarity": round(genre_similarity, 4),
                    "audience_similarity": round(audience_similarity, 4),
                    "explanation": explanation,
                }
            )

        return recommendations

    def get_personalized_recommendations(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Recommend unseen movies using collaborative filtering with fallback.

        The collaborative score compares the target user to other users on shared ratings,
        then weights unseen movies by the similarity-adjusted rating from those users.
        """
        normalized_user_id = self._validate_user_id(user_id)
        normalized_limit = self._normalize_limit(limit, minimum=1)

        min_overlap = 3
        collaborative_query = """
        MATCH (target:User {userId: $user_id})-[target_rating:RATED]->(shared_movie:Movie)<-[other_rating:RATED]-(other:User)
        WHERE other.userId <> target.userId
        WITH other,
             collect({movieId: shared_movie.movieId,
                     targetRating: toFloat(target_rating.rating),
                     otherRating: toFloat(other_rating.rating)}) AS shared_ratings,
             count(DISTINCT shared_movie) AS overlap_count
        WHERE overlap_count >= $min_overlap

        UNWIND shared_ratings AS item
        WITH other,
             overlap_count,
             avg(abs(item.targetRating - item.otherRating)) AS avg_rating_gap
        WITH other,
             overlap_count,
             1.0 - (avg_rating_gap / 5.0) AS similarity

        MATCH (other)-[orating:RATED]->(candidate:Movie)
        WHERE NOT EXISTS {
            MATCH (:User {userId: $user_id})-[:RATED]->(candidate)
        }

        WITH candidate,
             other,
             similarity,
             toFloat(orating.rating) AS candidate_rating

        WITH candidate,
             collect({userId: other.userId, similarity: similarity, rating: candidate_rating}) AS support_rows,
             count(DISTINCT other) AS supporter_count,
             collect(DISTINCT other.userId) AS similar_users
        WHERE supporter_count >= 2

        WITH candidate,
             support_rows,
             supporter_count,
             similar_users,
             reduce(totalWeightedRating = 0.0, row IN support_rows | totalWeightedRating + row.similarity * row.rating) AS weighted_sum,
             reduce(totalSimilarity = 0.0, row IN support_rows | totalSimilarity + row.similarity) AS total_similarity
        WITH candidate,
             supporter_count,
             similar_users,
             CASE
                 WHEN total_similarity = 0 THEN 0.0
                 ELSE weighted_sum / total_similarity
             END AS normalized_score
        RETURN candidate.movieId AS movie_id,
               candidate.title AS title,
               round(normalized_score, 4) AS score,
               supporter_count AS supporter_count,
               similar_users AS similar_users,
               'collaborative' AS source
        ORDER BY score DESC, candidate.movieId ASC
        LIMIT $limit
        """

        collaborative_rows = self._run_read_query(
            collaborative_query,
            {"user_id": normalized_user_id, "limit": normalized_limit, "min_overlap": min_overlap},
        )

        if collaborative_rows:
            return [
                {
                    "movie_id": int(row["movie_id"]),
                    "title": row["title"],
                    "score": round(float(row["score"]), 4),
                    "supporter_count": int(row["supporter_count"]),
                    "similar_users": row.get("similar_users") or [],
                    "source": "collaborative",
                    "explanation": (
                        "Collaborative recommendation based on rating agreement with users who have similar tastes."
                    ),
                }
                for row in collaborative_rows
            ]

        fallback_query = """
        MATCH (m:Movie)<-[r:RATED]-(:User)
        WHERE NOT EXISTS { MATCH (:User {userId: $user_id})-[:RATED]->(m) }
        WITH m, count(r) AS rating_count, avg(toFloat(r.rating)) AS average_rating
        WHERE rating_count >= 20 AND average_rating >= 4.0
        RETURN m.movieId AS movie_id,
               m.title AS title,
               round(average_rating, 2) AS average_rating,
               rating_count AS rating_count,
               'fallback' AS source
        ORDER BY average_rating DESC, rating_count DESC
        LIMIT $limit
        """

        fallback_rows = self._run_read_query(
            fallback_query,
            {"user_id": normalized_user_id, "limit": normalized_limit},
        )

        return [
            {
                "movie_id": int(row["movie_id"]),
                "title": row["title"],
                "score": round(float(row["average_rating"]), 4),
                "rating_count": int(row["rating_count"]),
                "source": "fallback",
                "explanation": (
                    "Fallback recommendation: highly rated popular movies the user has not rated yet."
                ),
            }
            for row in fallback_rows
        ]

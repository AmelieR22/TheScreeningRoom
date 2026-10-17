from __future__ import annotations

import os

from app.recommendation_service import MovieRecommendationService


def main() -> None:
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise ValueError(
            "NEO4J_PASSWORD is not set. Add it to your environment before running this demo."
        )

    service = MovieRecommendationService()

    print("Popular movies:")
    for item in service.get_popular_movies(limit=5):
        print(item)

    print("\nHidden gems:")
    for item in service.get_hidden_gems(limit=5):
        print(item)

    print("\nSimilar movies to movie 1:")
    for item in service.get_similar_movies(movie_id=1, limit=5):
        print(item)

    print("\nPersonalized recommendations for user 1:")
    for item in service.get_personalized_recommendations(user_id=1, limit=5):
        print(item)


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase


def get_config() -> dict[str, str]:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise ValueError(
            "NEO4J_PASSWORD is not set. Set it in your PowerShell session before running this script."
        )
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    return {"uri": uri, "user": user, "password": password, "database": database}


def get_driver(config: dict[str, str]):
    try:
        driver = GraphDatabase.driver(
            config["uri"],
            auth=(config["user"], config["password"]),
            max_connection_pool_size=20,
        )
        driver.verify_connectivity()
        return driver
    except Exception as exc:  # pragma: no cover - runtime integration path
        raise RuntimeError(
            f"Unable to connect to Neo4j at {config['uri']}. "
            "Make sure Neo4j is running and the environment variables are correct."
        ) from exc


def main():
    print("Checking The Screening Room data in Neo4j...")

    try:
        config = get_config()
        driver = get_driver(config)
        database = config["database"]

        with driver.session(database=database) as session:
            counts = session.run(
                """
                MATCH (u:User)
                RETURN count(u) AS user_count
                """
            ).single()
            movie_count = session.run("MATCH (m:Movie) RETURN count(m) AS movie_count").single()
            genre_count = session.run("MATCH (g:Genre) RETURN count(g) AS genre_count").single()
            rated_count = session.run("MATCH (:User)-[r:RATED]->(:Movie) RETURN count(r) AS rated_count").single()
            tagged_count = session.run("MATCH (:User)-[:TAGGED]->(:Movie) RETURN count(*) AS tagged_count").single()
            genre_edges = session.run("MATCH (:Movie)-[:IN_GENRE]->(:Genre) RETURN count(*) AS genre_edge_count").single()

            sample_movies = session.run(
                """
                MATCH (m:Movie)
                RETURN m.movieId AS movieId, m.title AS title, m.year AS year
                ORDER BY m.movieId
                LIMIT 5
                """
            ).data()

        print(f"Users: {counts['user_count']}")
        print(f"Movies: {movie_count['movie_count']}")
        print(f"Genres: {genre_count['genre_count']}")
        print(f"Rated relationships: {rated_count['rated_count']}")
        print(f"Tagged relationships: {tagged_count['tagged_count']}")
        print(f"Genre relationships: {genre_edges['genre_edge_count']}")

        print("Sample movies:")
        for movie in sample_movies:
            print(f"  - {movie['movieId']}: {movie['title']} ({movie['year']})")

        print("Verification complete.")
    except Exception as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        raise
    finally:
        if "driver" in locals():
            driver.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "ml-latest-small"


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
            max_connection_pool_size=50,
        )
        driver.verify_connectivity()
        return driver
    except Exception as exc:  # pragma: no cover - runtime integration path
        raise RuntimeError(
            f"Unable to connect to Neo4j at {config['uri']}. "
            "Check that Docker Desktop is running and the Neo4j container is available."
        ) from exc


def clean_movie_title(title: str) -> tuple[str, int | None]:
    raw_title = str(title).strip()
    match = re.search(r"\s*\((\d{4})\)\s*$", raw_title)
    year = int(match.group(1)) if match else None
    cleaned = re.sub(r"\s*\(\d{4}\)\s*$", "", raw_title).strip()
    return cleaned, year


def ensure_schema(tx):
    schema_queries = [
        "CREATE CONSTRAINT user_userId IF NOT EXISTS FOR (u:User) REQUIRE u.userId IS UNIQUE",
        "CREATE CONSTRAINT movie_movieId IF NOT EXISTS FOR (m:Movie) REQUIRE m.movieId IS UNIQUE",
        "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
        "CREATE INDEX user_userId_lookup IF NOT EXISTS FOR (u:User) ON (u.userId)",
        "CREATE INDEX movie_title_lookup IF NOT EXISTS FOR (m:Movie) ON (m.title)",
        "CREATE INDEX movie_year_lookup IF NOT EXISTS FOR (m:Movie) ON (m.year)",
    ]
    for query in schema_queries:
        tx.run(query)


def ensure_constraints_and_indexes(driver, database: str):
    print("Checking Neo4j schema...")
    with driver.session(database=database) as session:
        session.execute_write(ensure_schema)
    print("Neo4j schema is ready.")


def import_movies_batch(tx, rows: list[dict]):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (m:Movie {movieId: row.movieId})
        SET m.title = row.title,
            m.year = row.year

        WITH m, row.genres AS genres
        UNWIND CASE
            WHEN genres IS NULL OR size(genres) = 0 THEN [null]
            ELSE genres
        END AS genreName
        WITH m, genreName
        WHERE genreName IS NOT NULL
        MERGE (g:Genre {name: genreName})
        MERGE (m)-[:IN_GENRE]->(g)
        """,
        rows=rows,
    )


def import_movies(driver, database: str, csv_path: Path, batch_size: int = 5000):
    if not csv_path.exists():
        raise FileNotFoundError(f"Movie CSV not found: {csv_path}")

    print(f"Reading movies from {csv_path}")
    df = pd.read_csv(csv_path)
    total = len(df)
    print(f"Found {total} movie records.")

    for start in range(0, total, batch_size):
        batch = df.iloc[start : start + batch_size]
        rows = []
        for _, row in batch.iterrows():
            title, year = clean_movie_title(row["title"])
            genres = [item.strip() for item in str(row.get("genres", "")).split("|") if item and item.strip()]
            rows.append({
                "movieId": int(row["movieId"]),
                "title": title,
                "year": year,
                "genres": genres,
            })

        with driver.session(database=database) as session:
            session.execute_write(import_movies_batch, rows)

        processed = min(start + batch_size, total)
        print(f"Movie batch imported: {processed}/{total}")

    print("Movie import complete.")


def import_ratings_batch(tx, rows: list[dict]):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (u:User {userId: row.userId})
        MERGE (m:Movie {movieId: row.movieId})
        MERGE (u)-[r:RATED {rating: row.rating, timestamp: row.timestamp}]->(m)
        """,
        rows=rows,
    )


def import_ratings(driver, database: str, csv_path: Path, batch_size: int = 5000):
    if not csv_path.exists():
        raise FileNotFoundError(f"Ratings CSV not found: {csv_path}")

    print(f"Reading ratings from {csv_path}")
    df = pd.read_csv(csv_path)
    total = len(df)
    print(f"Found {total} rating records.")

    for start in range(0, total, batch_size):
        batch = df.iloc[start : start + batch_size]
        rows = [
            {
                "userId": int(row["userId"]),
                "movieId": int(row["movieId"]),
                "rating": float(row["rating"]),
                "timestamp": int(row["timestamp"]),
            }
            for _, row in batch.iterrows()
        ]

        with driver.session(database=database) as session:
            session.execute_write(import_ratings_batch, rows)

        processed = min(start + batch_size, total)
        print(f"Rating batch imported: {processed}/{total}")

    print("Rating import complete.")


def import_tags_batch(tx, rows: list[dict]):
    tx.run(
        """
        UNWIND $rows AS row
        MERGE (u:User {userId: row.userId})
        MERGE (m:Movie {movieId: row.movieId})
        MERGE (u)-[t:TAGGED {tag: row.tag, timestamp: row.timestamp}]->(m)
        """,
        rows=rows,
    )


def import_tags(driver, database: str, csv_path: Path, batch_size: int = 5000):
    if not csv_path.exists():
        raise FileNotFoundError(f"Tags CSV not found: {csv_path}")

    print(f"Reading tags from {csv_path}")
    df = pd.read_csv(csv_path)
    total = len(df)
    print(f"Found {total} tag records.")

    for start in range(0, total, batch_size):
        batch = df.iloc[start : start + batch_size]
        rows = [
            {
                "userId": int(row["userId"]),
                "movieId": int(row["movieId"]),
                "tag": str(row["tag"]).strip(),
                "timestamp": int(row["timestamp"]),
            }
            for _, row in batch.iterrows()
        ]

        with driver.session(database=database) as session:
            session.execute_write(import_tags_batch, rows)

        processed = min(start + batch_size, total)
        print(f"Tag batch imported: {processed}/{total}")

    print("Tag import complete.")


def main():
    print("Starting MovieLens ingestion for The Screening Room...")

    try:
        config = get_config()
        driver = get_driver(config)
        database = config["database"]

        ensure_constraints_and_indexes(driver, database)
        import_movies(driver, database, DATA_DIR / "movies.csv")
        import_ratings(driver, database, DATA_DIR / "ratings.csv")
        import_tags(driver, database, DATA_DIR / "tags.csv")

        print("All MovieLens data imported successfully.")
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        raise
    finally:
        if "driver" in locals():
            driver.close()


if __name__ == "__main__":
    main()

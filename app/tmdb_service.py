"""TMDb metadata lookups for MovieLens movie IDs."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

import httpx


class TMDbService:
    """Resolve MovieLens movie IDs to TMDb metadata and provide cache support."""

    TIMEOUT_SECONDS = 10.0
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    def __init__(self) -> None:
        self._cache: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _movie_links_path() -> Path:
        """Return the local MovieLens links file, including Docker and local runs."""
        candidate_paths = [
            Path(__file__).resolve().parent.parent / "data" / "ml-latest-small" / "links.csv",
            Path.cwd() / "data" / "ml-latest-small" / "links.csv",
        ]

        for path in candidate_paths:
            if path.exists():
                return path

        return candidate_paths[0]

    @classmethod
    def _load_tmdb_id_map(cls) -> dict[int, int]:
        """Load tmdbId mapping once from the MovieLens links CSV."""
        path = cls._movie_links_path()
        mapping: dict[int, int] = {}

        if not path.exists():
            return mapping

        with path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                movie_id_raw = (row.get("movieId") or "").strip()
                tmdb_id_raw = (row.get("tmdbId") or "").strip()

                if not movie_id_raw or not tmdb_id_raw:
                    continue

                try:
                    movie_id = int(movie_id_raw)
                    tmdb_id = int(tmdb_id_raw)
                except ValueError:
                    continue

                if movie_id > 0 and tmdb_id > 0:
                    mapping[movie_id] = tmdb_id

        return mapping

    def get_tmdb_id(self, movie_id: int) -> int:
        """Map a MovieLens movieId to the corresponding TMDb tmdbId."""
        try:
            normalized_movie_id = int(movie_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("movie_id must be an integer.") from exc

        if normalized_movie_id <= 0:
            raise ValueError("movie_id must be greater than zero.")

        tmdb_id = self._load_tmdb_id_map().get(normalized_movie_id)
        if tmdb_id is None:
            raise ValueError(f"No TMDb ID found for movie_id {normalized_movie_id}.")

        return tmdb_id

    @staticmethod
    def _image_url(image_path: str | None, *, size: str = "w500") -> str | None:
        """Build a TMDb image URL using the documented image base format."""
        if not image_path:
            return None

        return f"{TMDbService.IMAGE_BASE_URL}/{size}{image_path}"

    def get_movie_metadata(self, movie_id: int) -> dict[str, Any]:
        """Fetch a single movie's metadata from TMDb for a MovieLens movie ID."""
        try:
            normalized_movie_id = int(movie_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("movie_id must be an integer.") from exc

        if normalized_movie_id <= 0:
            raise ValueError("movie_id must be greater than zero.")

        if normalized_movie_id in self._cache:
            return dict(self._cache[normalized_movie_id])

        tmdb_id = self.get_tmdb_id(normalized_movie_id)
        api_key = os.getenv("TMDB_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("TMDB_API_KEY is not configured.")

        url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
        try:
            response = httpx.get(
                url,
                params={"api_key": api_key, "language": "en-US"},
                timeout=self.TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError("TMDb service is unavailable.") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("TMDb service returned an invalid payload.")

        result: dict[str, Any] = {
            "movieId": normalized_movie_id,
            "tmdbId": int(payload.get("id") or tmdb_id),
            "title": payload.get("title") or payload.get("original_title") or "",
            "overview": payload.get("overview") or "",
            "release_date": payload.get("release_date") or None,
            "poster_url": self._image_url(payload.get("poster_path"), size="w500"),
            "backdrop_url": self._image_url(payload.get("backdrop_path"), size="w1280"),
            "vote_average": payload.get("vote_average"),
            "vote_count": payload.get("vote_count"),
        }

        self._cache[normalized_movie_id] = result
        return dict(result)

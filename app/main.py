"""FastAPI application for The Screening Room."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path as PathlibPath
from typing import Any

import re

from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.graph_analytics_service import GraphAnalyticsService
from app.movie_assistant_service import MovieAssistantService
from app.platform_profile_service import PlatformProfileService
from app.recommendation_service import MovieRecommendationService
from app.tmdb_service import TMDbService


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """Initialize services for the app lifespan and close Neo4j drivers on shutdown."""
    fastapi_app.state.recommendation_service = MovieRecommendationService()
    fastapi_app.state.graph_analytics_service = GraphAnalyticsService()
    fastapi_app.state.movie_assistant_service = MovieAssistantService()
    fastapi_app.state.platform_profile_service = PlatformProfileService()
    fastapi_app.state.platform_profile_service.ensure_platform_profile_constraints()
    fastapi_app.state.tmdb_service = TMDbService()
    try:
        yield
    finally:
        recommendation_service = getattr(fastapi_app.state, "recommendation_service", None)
        if recommendation_service is not None and hasattr(recommendation_service, "driver"):
            recommendation_service.driver.close()

        analytics_service = getattr(fastapi_app.state, "graph_analytics_service", None)
        if analytics_service is not None and hasattr(analytics_service, "driver"):
            analytics_service.driver.close()

        assistant_service = getattr(fastapi_app.state, "movie_assistant_service", None)
        if assistant_service is not None and hasattr(assistant_service, "driver"):
            assistant_service.driver.close()

        platform_profile_service = getattr(fastapi_app.state, "platform_profile_service", None)
        if platform_profile_service is not None and hasattr(platform_profile_service, "driver"):
            platform_profile_service.driver.close()

        tmdb_service = getattr(fastapi_app.state, "tmdb_service", None)
        if tmdb_service is not None:
            tmdb_service._cache.clear()


app = FastAPI(title="The Screening Room", lifespan=lifespan)

BASE_DIR = PathlibPath(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_homepage() -> FileResponse:
    """Serve the homepage template for the movie-club frontend."""
    return FileResponse(BASE_DIR / "templates" / "index.html")


def get_recommendation_service() -> MovieRecommendationService:
    """Return the recommendation service configured on the app state."""
    override = app.dependency_overrides.get(get_recommendation_service)
    if override is not None:
        return override()

    service = getattr(app.state, "recommendation_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is unavailable.",
        )
    return service


def get_graph_analytics_service() -> GraphAnalyticsService:
    """Return the graph analytics service configured on the app state."""
    override = app.dependency_overrides.get(get_graph_analytics_service)
    if override is not None:
        return override()

    service = getattr(app.state, "graph_analytics_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph analytics service is unavailable.",
        )
    return service


def get_movie_assistant_service() -> MovieAssistantService:
    """Return the movie assistant service configured on the app state."""
    override = app.dependency_overrides.get(get_movie_assistant_service)
    if override is not None:
        return override()

    service = getattr(app.state, "movie_assistant_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Movie assistant service is unavailable.",
        )
    return service


def get_tmdb_service() -> TMDbService:
    """Return the TMDb metadata service configured on the app state."""
    override = app.dependency_overrides.get(get_tmdb_service)
    if override is not None:
        return override()

    service = getattr(app.state, "tmdb_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TMDb service is unavailable.",
        )
    return service


def get_platform_profile_service() -> PlatformProfileService:
    """Return the platform profile service configured on the app state."""
    override = app.dependency_overrides.get(get_platform_profile_service)
    if override is not None:
        return override()

    service = getattr(app.state, "platform_profile_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform profile service is unavailable.",
        )
    return service


class PlatformUserCreateRequest(BaseModel):
    """Request payload for creating a platform profile."""

    username: str = Field(..., min_length=3, max_length=40)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Username cannot be blank.")
        if len(cleaned) < 3 or len(cleaned) > 40:
            raise ValueError("Username must be between 3 and 40 characters.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cleaned):
            raise ValueError("Username may only contain letters, numbers, dots, underscores, and hyphens.")
        return cleaned


class PlatformMovieRequest(BaseModel):
    """Common movie identifier payload for profile interactions."""

    movie_id: int = Field(..., gt=0)


class PlatformReactionRequest(BaseModel):
    """Payload for liking or disliking a movie."""

    movie_id: int = Field(..., gt=0)
    reaction: str

    @field_validator("reaction")
    @classmethod
    def validate_reaction(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if cleaned not in {"liked", "disliked"}:
            raise ValueError("Reaction must be either 'liked' or 'disliked'.")
        return cleaned


class PlatformRatingRequest(BaseModel):
    """Payload for rating a movie on a platform profile."""

    movie_id: int = Field(..., gt=0)
    rating: float = Field(..., gt=0)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: float) -> float:
        numeric = float(value)
        if numeric < 0.5 or numeric > 5.0:
            raise ValueError("Rating must be between 0.5 and 5.0.")
        if abs((numeric * 2) - round(numeric * 2)) > 1e-9:
            raise ValueError("Rating must be in 0.5 increments.")
        return numeric


def _build_response(limit: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a consistent recommendation payload."""
    return {"limit": limit, "items": items}


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return the health status for the service."""
    return {"status": "ok"}


@app.get("/recommendations/popular")
def get_popular_movies(
    limit: int = Query(default=10, ge=1, le=50),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Return historically popular movies by rating aggregate."""
    try:
        items = service.get_popular_movies(limit=limit)
        return _build_response(limit=limit, items=items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is currently unavailable.",
        ) from exc


@app.get("/recommendations/hidden-gems")
def get_hidden_gems(
    limit: int = Query(default=10, ge=1, le=50),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Return high-ranked movies with fewer ratings."""
    try:
        items = service.get_hidden_gems(limit=limit)
        return _build_response(limit=limit, items=items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is currently unavailable.",
        ) from exc


@app.get("/recommendations/similar/{movie_id}")
def get_similar_movies(
    movie_id: int = Path(..., gt=0),
    limit: int = Query(default=10, ge=1, le=50),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Return movies similar to a selected movie by genre and audience overlap."""
    try:
        items = service.get_similar_movies(movie_id=movie_id, limit=limit)
        return _build_response(limit=limit, items=items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is currently unavailable.",
        ) from exc


@app.get("/recommendations/personalized/{user_id}")
def get_personalized_recommendations(
    user_id: int = Path(..., gt=0),
    limit: int = Query(default=10, ge=1, le=50),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Return personalized recommendations for a given user."""
    try:
        items = service.get_personalized_recommendations(user_id=user_id, limit=limit)
        return _build_response(limit=limit, items=items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is currently unavailable.",
        ) from exc


@app.get("/recommendations/platform/{profile_id}")
def get_platform_profile_recommendations(
    profile_id: str = Path(..., min_length=3),
    limit: int = Query(default=10, ge=1, le=50),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Return profile-based recommendations for a PlatformUser using their watched, liked, and disliked state."""
    try:
        items = service.get_platform_profile_recommendations(profile_id=profile_id, limit=limit)
        return _build_response(limit=limit, items=items)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation service is currently unavailable.",
        ) from exc


@app.get("/analytics/similar-users/{user_identifier}")
def get_similar_users(
    user_identifier: str = Path(..., min_length=1),
    limit: int = Query(default=5, ge=1, le=50),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return users with the most similar taste profile for MovieLens or PlatformUser identifiers."""
    try:
        cleaned = user_identifier.strip()
        if cleaned.isdigit():
            numeric_user_id = int(cleaned)
            if numeric_user_id <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="User ID must be a positive integer.",
                )
            items = service.get_similar_users(user_id=numeric_user_id, limit=limit)
            return {"user_id": numeric_user_id, "limit": limit, "items": items}

        items = service.get_similar_platform_users(identifier=cleaned, limit=limit)
        return {"user_id": cleaned, "limit": limit, "items": items}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph analytics service is currently unavailable.",
        ) from exc


@app.get("/analytics/communities")
def get_user_communities(
    limit: int = Query(default=10, ge=1, le=50),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return the top user communities discovered by GDS Louvain."""
    try:
        items = service.get_user_communities(limit=limit)
        return {"limit": limit, "items": items}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph analytics service is currently unavailable.",
        ) from exc


@app.get("/analytics/path/users/{user_id_1}/{user_id_2}")
def get_user_path(
    user_id_1: str = Path(..., min_length=1),
    user_id_2: str = Path(..., min_length=1),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return the shortest user-to-user connection path for numeric or platform identifiers."""
    try:
        cleaned_1 = user_id_1.strip()
        cleaned_2 = user_id_2.strip()

        if cleaned_1.isdigit() and cleaned_2.isdigit():
            numeric_1 = int(cleaned_1)
            numeric_2 = int(cleaned_2)
            if numeric_1 <= 0 or numeric_2 <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="User IDs must be positive integers.",
                )
            result = service.find_user_path(user_id_1=numeric_1, user_id_2=numeric_2)
            return result

        if cleaned_1.isdigit() and int(cleaned_1) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="User IDs must be positive integers.",
            )
        if cleaned_2.isdigit() and int(cleaned_2) <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="User IDs must be positive integers.",
            )

        result = service.find_user_path_by_identifier(user_identifier_1=cleaned_1, user_identifier_2=cleaned_2)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph analytics service is currently unavailable.",
        ) from exc


@app.get("/analytics/path/user-movie/{user_id}/{movie_id}")
def get_user_movie_path(
    user_id: int = Path(..., gt=0),
    movie_id: int = Path(..., gt=0),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return the shortest user-to-movie connection path."""
    try:
        result = service.find_user_movie_path(user_id=user_id, movie_id=movie_id)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph analytics service is currently unavailable.",
        ) from exc


@app.get("/movies/search")
def search_movies(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=20),
    service: MovieRecommendationService = Depends(get_recommendation_service),
):
    """Search the imported MovieLens catalog by partial title match."""
    try:
        cleaned_query = q.strip()
        items = service.search_movies(cleaned_query, limit=limit)
        return {"q": cleaned_query, "limit": limit, "items": items}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Movie search is currently unavailable.",
        ) from exc


@app.post("/assistant/ask")
def ask_movie_assistant(
    payload: dict[str, Any],
    service: MovieAssistantService = Depends(get_movie_assistant_service),
):
    """Answer a question using the allowlisted movie assistant queries."""
    try:
        question = payload.get("question", "")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Question cannot be empty.")
        result = service.ask(question)
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Movie assistant service is currently unavailable.",
        ) from exc


@app.get("/movies/{movie_id}/metadata")
def get_movie_metadata(
    movie_id: int = Path(..., gt=0),
    service: TMDbService = Depends(get_tmdb_service),
):
    """Return TMDb movie metadata for a MovieLens movie identifier."""
    try:
        return service.get_movie_metadata(movie_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@app.post("/platform-users")
def create_platform_user(
    payload: PlatformUserCreateRequest,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Create a persistent PlatformUser node distinct from imported MovieLens users."""
    try:
        return service.create_platform_profile(payload.username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/platform-users")
def list_platform_users(
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """List all platform profile users."""
    try:
        return {"items": service.list_platform_profiles()}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/platform-users/lookup")
def lookup_platform_user(
    username: str = Query(..., min_length=3, max_length=40),
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Resolve a platform username to its real PlatformUser profile data."""
    try:
        return service.get_platform_profile_by_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/platform-users/{profile_id}")
def get_platform_user(
    profile_id: str,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Get a single platform profile by its stable profile ID."""
    try:
        return service.get_platform_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/platform-users/{profile_id}/activity")
def get_platform_user_activity(
    profile_id: str,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Return the selected platform profile's read-only film activity."""
    try:
        return service.get_profile_activity(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/platform-users/{profile_id}/watchlist")
def add_to_watchlist(
    profile_id: str,
    payload: PlatformMovieRequest,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Add a movie to a profile watchlist using a separate relationship."""
    try:
        return service.save_to_watchlist(profile_id, payload.movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.delete("/platform-users/{profile_id}/watchlist/{movie_id}")
def remove_from_watchlist(
    profile_id: str,
    movie_id: int = Path(..., gt=0),
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Remove a movie from a profile watchlist."""
    try:
        return service.remove_from_watchlist(profile_id, movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/platform-users/{profile_id}/watched")
def mark_movie_watched(
    profile_id: str,
    payload: PlatformMovieRequest,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Mark a movie watched for a profile without affecting imported ratings."""
    try:
        return service.mark_watched(profile_id, payload.movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.delete("/platform-users/{profile_id}/watched/{movie_id}")
def unmark_movie_watched(
    profile_id: str,
    movie_id: int = Path(..., gt=0),
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Remove the watched state for a movie on a profile."""
    try:
        return service.mark_unwatched(profile_id, movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/platform-users/{profile_id}/reactions")
def set_profile_reaction(
    profile_id: str,
    payload: PlatformReactionRequest,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Set either a liked or disliked reaction without creating contradictory states."""
    try:
        return service.set_reaction(profile_id, payload.movie_id, payload.reaction)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.delete("/platform-users/{profile_id}/reactions/{movie_id}")
def clear_profile_reaction(
    profile_id: str,
    movie_id: int = Path(..., gt=0),
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Clear either a like or dislike relationship for a movie."""
    try:
        return service.clear_reaction(profile_id, movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.post("/platform-users/{profile_id}/ratings")
def set_profile_rating(
    profile_id: str,
    payload: PlatformRatingRequest,
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Set a 0.5-5.0 movie rating on a platform-specific relationship."""
    try:
        return service.set_rating(profile_id, payload.movie_id, payload.rating)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.delete("/platform-users/{profile_id}/ratings/{movie_id}")
def remove_profile_rating(
    profile_id: str,
    movie_id: int = Path(..., gt=0),
    service: PlatformProfileService = Depends(get_platform_profile_service),
):
    """Remove the platform-specific rating for a movie."""
    try:
        return service.remove_rating(profile_id, movie_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

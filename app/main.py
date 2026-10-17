"""FastAPI application for The Screening Room."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path as PathlibPath
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.graph_analytics_service import GraphAnalyticsService
from app.movie_assistant_service import MovieAssistantService
from app.recommendation_service import MovieRecommendationService


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """Initialize services for the app lifespan and close Neo4j drivers on shutdown."""
    fastapi_app.state.recommendation_service = MovieRecommendationService()
    fastapi_app.state.graph_analytics_service = GraphAnalyticsService()
    fastapi_app.state.movie_assistant_service = MovieAssistantService()
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


@app.get("/analytics/similar-users/{user_id}")
def get_similar_users(
    user_id: int = Path(..., gt=0),
    limit: int = Query(default=5, ge=1, le=50),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return users with the most similar taste profile."""
    try:
        items = service.get_similar_users(user_id=user_id, limit=limit)
        return {"user_id": user_id, "limit": limit, "items": items}
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
    user_id_1: int = Path(..., gt=0),
    user_id_2: int = Path(..., gt=0),
    service: GraphAnalyticsService = Depends(get_graph_analytics_service),
):
    """Return the shortest user-to-user connection path."""
    try:
        result = service.find_user_path(user_id_1=user_id_1, user_id_2=user_id_2)
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

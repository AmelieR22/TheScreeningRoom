# The Screening Room

The Screening Room is a Python-based movie recommendation application that uses Neo4j, FastAPI, and the MovieLens latest-small dataset. It is designed as a university Graph Databases project with a modular structure for future recommendation features, graph analysis, and personalized user experiences.

## Architecture

- `app/`: FastAPI application code
- `database/`: Neo4j scripts and database utilities
- `tests/`: automated tests
- `data/`: local dataset storage and generated outputs
- `documentation/`: design notes and project docs
- `notebooks/`: exploratory notebooks for analysis and experimentation

## Planned features

- Personalized movie recommendations
- Similar movies based on graph relationships
- Popular film summaries
- Hidden-gem discovery
- User communities with similar tastes
- Optional natural-language assistant support

## Windows setup

1. Install Python 3.13.
2. Install Docker Desktop and ensure Linux containers are enabled.
3. Clone the project and open it in VS Code.
4. Create a virtual environment:
   python -m venv .venv
5. Activate the environment:
   .venv\Scripts\activate
6. Install the project dependencies:
   pip install -r requirements.txt
7. Copy `.env.example` to `.env` and update values as needed.
8. Start services with Docker Compose when ready:
   docker compose up --build

## Importing the MovieLens data

After Docker Desktop is running and Neo4j is started, follow these PowerShell steps from the project root.

1. Create and update your local environment file:
   Copy-Item .env.example .env
   notepad .env

2. Make sure your Neo4j credentials are set correctly in `.env`.
   Example values:
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=change_me
   NEO4J_DATABASE=neo4j

3. Activate the virtual environment:
   .\.venv\Scripts\Activate.ps1

4. Install dependencies if needed:
   python -m pip install -r requirements.txt

5. Run the import script:
   python .\database\scripts\import_movielens.py

6. Verify that the import worked:
   python .\database\scripts\verify_import.py

## Verification output

The verification script will print:

- total users
- total movies
- total genres
- total rated relationships
- total tagged relationships
- sample movie records

This helps confirm that the Neo4j graph was populated correctly and that the import is idempotent when run again.

## Recommendation engine

The recommendation service uses the existing Neo4j graph and is designed to be beginner-friendly.

### Scoring approach

- `get_popular_movies(limit=10)`: ranks movies by average rating and number of ratings, with a minimum threshold of 20 ratings. This is historical MovieLens popularity, not live trend detection.
- `get_hidden_gems(limit=10)`: looks for movies with strong average ratings but fewer ratings, using a minimum threshold to reduce noise.
- `get_similar_movies(movie_id, limit=10)`: combines shared genres and overlapping user relationships to find related titles.
- `get_personalized_recommendations(user_id, limit=10)`: finds users with similar tastes and recommends movies they liked but the target user has not rated yet.

### PowerShell usage

From the project root:

1. Activate the virtual environment:
   .\.venv\Scripts\Activate.ps1

2. Run the unit tests:
   python -m pytest tests/test_recommendation_service.py -q

3. Run the recommendation demo script:
   $env:NEO4J_PASSWORD="change_me"
   python .\demo_recommendations.py

4. If you want to inspect the graph manually, open Neo4j Browser at:
   http://localhost:7474

### Important notes

- Do not reset or reimport the Neo4j database unless you explicitly want to rebuild the graph.
- The service expects the imported MovieLens data already to be present in Neo4j.
- The recommendation methods validate user IDs, movie IDs and limits before running queries.

## GDS graph analytics

The project also includes a beginner-friendly Neo4j GDS analytics layer for user similarity and community detection.

### Shortest-path connectivity

The analytics service also supports read-only shortest-path lookups using Neo4j `shortestPath` over `RATED` relationships in either direction. These endpoints use a bounded max hop count of 6 and never modify the database.

- `GET /analytics/path/users/{user_id_1}/{user_id_2}` — find the shortest connection between two users using shared movies
- `GET /analytics/path/user-movie/{user_id}/{movie_id}` — find the shortest connection between a user and a movie

Each response includes an ordered list of path nodes, relationship metadata, and the hop count. If no path exists, the response returns a clean “not found” structure instead of an exception.

### GDS setup

The Neo4j Docker service includes the official Graph Data Science plugin. In the Compose configuration, the Neo4j container enables the plugin with:

- `NEO4J_PLUGINS: '["graph-data-science"]'`
- `NEO4J_dbms_security_procedures_unrestricted: "gds.*"`

This is the official GDS plugin for Neo4j 5.25.

### Graph analytics service

The analytics service reuses the same Neo4j driver pattern as the recommendation service and creates the in-memory projection `screening-room-ratings` if it does not already exist. The projection uses the existing `User` and `Movie` nodes and projects the `RATED` relationships as `UNDIRECTED` to support similarity and community queries.

It provides:

- `get_similar_users(user_id, limit=5)`: uses GDS `nodeSimilarity.stream` to find users with similar preferences.
- `get_user_communities(limit=10)`: uses GDS `louvain.stream` to group users into communities.

The service gracefully returns an empty list if GDS is unavailable or the projection cannot be created, without modifying the MovieLens graph data.

## API endpoints

The FastAPI app exposes the recommendation endpoints below.

- `GET /health` — health check
- `GET /recommendations/popular?limit=10` — top movies by historical popularity
- `GET /recommendations/hidden-gems?limit=10` — highly rated movies with fewer ratings
- `GET /recommendations/similar/{movie_id}?limit=10` — similar movies based on genres and audience overlap
- `GET /recommendations/personalized/{user_id}?limit=10` — collaborative recommendations and fallback recommendations
- `GET /analytics/similar-users/{user_id}?limit=5` — users most similar to the target user via GDS node similarity
- `GET /analytics/communities?limit=10` — user communities discovered by GDS Louvain

### Local API run (PowerShell)

From the project root:

1. Activate the environment:
   .\.venv\Scripts\Activate.ps1

2. Set the Neo4j password for the session:
   $env:NEO4J_PASSWORD="change_me"

3. Start the FastAPI app with Uvicorn:
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

4. Open the website:
   http://localhost:8000/

5. Open the Swagger UI:
   http://localhost:8000/docs

## Website frontend

The project now includes a premium, responsive movie-club landing page served by FastAPI at the root path. The front end uses vanilla HTML, CSS, and JavaScript and communicates with the existing API via relative URLs, so it works both locally and inside the Docker setup without adding React or any frontend build tooling.

### What is included

- Hero section and cinematic brand styling
- Popular movies and hidden gems carousels/cards
- Personalized recommendations driven by a numeric user ID
- Similar-movie lookup driven by a numeric movie ID
- Concierge chat panel for the read-only assistant at `POST /assistant/ask`
- Graph insights for similar users and communities
- User-to-user shortest-path explorer
- Loading states, friendly errors, and empty-state messaging

### Files added/updated

- `app/main.py` — serves the homepage and mounts static assets
- `app/templates/index.html` — the full interface layout
- `app/static/styles.css` — premium editorial styling and responsiveness
- `app/static/script.js` — client-side fetch logic, rendering, and interactivity
- `tests/test_app_endpoints.py` — smoke test for the homepage route
- `README.md` — launch and viewing instructions

### How to view the site

1. Activate the project environment.
2. Start the app with:
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
3. Open:
   http://localhost:8000/

The site is intentionally designed to work with the existing backend endpoints without changing the recommendation or analytics logic.

### Example requests

- http://localhost:8000/recommendations/popular?limit=5
- http://localhost:8000/recommendations/hidden-gems?limit=5
- http://localhost:8000/recommendations/similar/1?limit=5
- http://localhost:8000/recommendations/personalized/1?limit=5
- http://localhost:8000/analytics/similar-users/1?limit=5
- http://localhost:8000/analytics/communities?limit=10

## Natural-language movie assistant foundation

The project now includes a secure, read-only movie assistant foundation. It does not connect to Ollama yet, but it is structured to support a future natural-language-to-Cypher workflow without letting the model generate arbitrary database commands.

### Allowlisted architecture

The assistant uses a strict allowlist of predefined query templates instead of regex-based Cypher blacklists. The model is not allowed to emit raw Cypher. Instead, it selects one of the supported intents and provides normalized parameters such as `$genre`, `$movie_id`, `$user_id`, and `$limit`.

Supported intents:

- `popular_movies`
- `top_genre_movies`
- `movie_details`
- `user_recommendations`
- `popular_tags`

Each intent maps to a fixed query template written by the application team. The templates are validated before execution and must match one of the approved queries exactly.

### Ollama integration

The assistant can call a local Ollama instance using the installed `httpx` library. The service reads two environment variables:

- `OLLAMA_BASE_URL` — defaults to `http://localhost:11434` when FastAPI runs locally on Windows or `http://ollama:11434` when FastAPI runs inside Docker Compose
- `OLLAMA_MODEL` — defaults to `qwen2.5:1.5b`

The prompt sent to Ollama asks for JSON only and instructs the model to classify the question into one of the five allowlisted intents and return parameters such as `$genre`, `$movie_id`, `$user_id`, and `$limit`. The model never generates executable Cypher.

### Safe validation rules

- `limit` must be an integer between 1 and 25
- `movie_id` and `user_id` must be positive integers
- `genre` must come from the actual MovieLens genres used in the graph
- only read-only Neo4j access is used
- multiple statements, comments, and non-allowlisted queries are rejected
- unknown questions return a clear error rather than executing arbitrary Cypher
- recognized genres without numeric user IDs are routed to `top_genre_movies`, not `user_recommendations`

### Query execution model

The service runs each query in a Neo4j read session with `READ_ACCESS` and uses a read transaction with a short timeout where supported by the driver. This keeps the database access restricted to safe, pre-approved read operations.

### Docker setup

When running the app in Docker Compose, the Ollama service is exposed on port `11434` and the app container uses the internal address `http://ollama:11434` by default. When FastAPI runs directly on a Windows host, use `http://localhost:11434`.

### Assistant API

- `POST /assistant/ask` with JSON body:
  `{"question": "Find five highly rated comedy movies"}`

Example response:

```json
{
  "question": "Find five highly rated comedy movies",
  "generated_cypher": "MATCH (:User)-[r:RATED]->(m:Movie)-[:IN_GENRE]->(:Genre {name: $genre}) ... LIMIT $limit",
  "results": [{"movie_id": 1, "title": "Toy Story"}],
  "explanation": "This answer is produced from a fixed, allowlisted MovieLens query template and a read-only Neo4j session. The assistant does not modify the database."
}
```

### Notes

- The assistant is intentionally conservative and does not allow arbitrary LLM-generated Cypher.
- The project still keeps the recommendation engine, GDS analytics endpoints, and graph data untouched.
- No Ollama integration is connected yet; the current design is intentionally an allowlisted intent-and-parameters layer for a future LLM integration.

## Notes

- Do not commit actual secrets or real database credentials.
- `docker-compose.yml` is prepared for Neo4j and a future Ollama service.
- The project now includes the recommendation engine, API endpoints, GDS analytics, and the secure movie assistant foundation built on the existing graph structure.

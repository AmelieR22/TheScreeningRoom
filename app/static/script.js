const API_BASE = "";

const state = {
  popular: [],
  hidden: [],
  personalized: [],
  similar: [],
};

function movieGradient(seed) {
  const palettes = [
    "linear-gradient(135deg, #6f1d2a, #1d1617)",
    "linear-gradient(135deg, #8b4a3d, #1e1111)",
    "linear-gradient(135deg, #56408a, #17141c)",
    "linear-gradient(135deg, #2b5d6a, #171c1f)",
    "linear-gradient(135deg, #7a3f2a, #1c1213)",
    "linear-gradient(135deg, #325b3d, #121812)",
    "linear-gradient(135deg, #6b4b3b, #1a1416)",
    "linear-gradient(135deg, #3a4d74, #111823)",
  ];

  const index = Math.abs(seed % palettes.length);
  return palettes[index];
}

function setLoading(containerId, message = "Loading...") {
  const element = document.getElementById(containerId);
  if (!element) return;

  element.innerHTML = `
    <div class="loading-state">
      <div class="typing-bubble" aria-label="Loading">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </div>
      <div style="margin-top: 8px;">${message}</div>
    </div>
  `;
}

function setEmptyState(containerId, message) {
  const element = document.getElementById(containerId);
  if (!element) return;

  element.innerHTML = `<div class="empty-state">${message}</div>`;
}

function setErrorState(containerId, message) {
  const element = document.getElementById(containerId);
  if (!element) return;

  element.innerHTML = `<div class="error-state">${message}</div>`;
}

function renderMovieCards(items, containerId, options = {}) {
  const element = document.getElementById(containerId);
  if (!element) return;

  if (!Array.isArray(items) || items.length === 0) {
    setEmptyState(containerId, options.emptyMessage || "No films to recommend yet.");
    return;
  }

  const cards = items
    .map((item, index) => {
      const movieId = item.movie_id ?? item.id ?? index + 1;
      const title = item.title || "Untitled film";
      const score = item.score ?? item.average_rating ?? item.genre_similarity ?? null;
      const ratingText = score !== null ? `${Number(score).toFixed(2)}` : "Fresh pick";
      const badge = item.source === "fallback" ? "Fallback" : item.source === "collaborative" ? "Recommended" : "Featured";
      const explanation = item.explanation || item.summary || "A standout recommendation from the film graph.";
      const meta = [];

      if (item.average_rating !== undefined) meta.push(`Avg ${Number(item.average_rating).toFixed(2)}`);
      if (item.rating_count !== undefined) meta.push(`${item.rating_count} ratings`);
      if (item.supporter_count !== undefined) meta.push(`${item.supporter_count} supporters`);
      if (item.genre_similarity !== undefined) meta.push(`Genre ${Number(item.genre_similarity).toFixed(2)}`);
      if (item.audience_similarity !== undefined) meta.push(`Audience ${Number(item.audience_similarity).toFixed(2)}`);

      const gradient = movieGradient(movieId + index);

      return `
        <article class="movie-card" style="--poster-gradient: ${gradient};">
          <span class="card-badge">${badge}</span>
          <h4>${title}</h4>
          <div class="card-meta">
            <span>Movie #${movieId}</span>
            <span class="card-score">${ratingText}</span>
          </div>
          ${meta.length ? `<div class="card-meta" style="margin-top: 8px;">${meta.map((entry) => `<span>${entry}</span>`).join("")}</div>` : ""}
          <div class="card-explainer">${explanation}</div>
        </article>
      `;
    })
    .join("");

  element.innerHTML = cards;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    const message = errorPayload.detail || errorPayload.message || "The request could not be completed.";
    throw new Error(message);
  }

  return response.json();
}

async function loadSection(sectionKey, url, containerId, emptyMessage) {
  const element = document.getElementById(containerId);
  if (!element) return;

  setLoading(containerId, `Loading ${sectionKey.replace("-", " ")}...`);

  try {
    const data = await fetchJson(url);
    const items = data.items || [];
    renderMovieCards(items, containerId, { emptyMessage });
    state[sectionKey] = items;
  } catch (error) {
    setErrorState(containerId, `Unable to load ${sectionKey.replace("-", " ")}. ${error.message}`);
  }
}

async function loadPopular() {
  await loadSection("popular", `${API_BASE}/recommendations/popular?limit=8`, "popular-results", "No popular titles are available right now.");
}

async function loadHiddenGems() {
  await loadSection("hidden", `${API_BASE}/recommendations/hidden-gems?limit=8`, "hidden-gems-results", "No hidden gems were found for this screening.");
}

async function loadPersonalized(userId) {
  setLoading("personalized-results", `Loading recommendations for user ${userId}...`);

  try {
    const data = await fetchJson(`${API_BASE}/recommendations/personalized/${userId}?limit=6`);
    const items = data.items || [];
    renderMovieCards(items, "personalized-results", { emptyMessage: `No recommendations available for user ${userId}.` });
    state.personalized = items;
  } catch (error) {
    setErrorState("personalized-results", `Could not load personalized picks for user ${userId}. ${error.message}`);
  }
}

async function loadSimilar(movieId) {
  setLoading("similar-results", `Finding similar films to movie ${movieId}...`);

  try {
    const data = await fetchJson(`${API_BASE}/recommendations/similar/${movieId}?limit=6`);
    const items = data.items || [];
    renderMovieCards(items, "similar-results", { emptyMessage: `No similar movies were found for #${movieId}.` });
    state.similar = items;
  } catch (error) {
    setErrorState("similar-results", `Could not find similar titles for movie ${movieId}. ${error.message}`);
  }
}

async function loadSimilarUsers(userId) {
  setLoading("similar-users-results", `Checking your audience circle for user ${userId}...`);

  try {
    const data = await fetchJson(`${API_BASE}/analytics/similar-users/${userId}?limit=5`);
    const items = data.items || [];

    if (!items.length) {
      setEmptyState("similar-users-results", "No closely related users were found for this viewer.");
      return;
    }

    document.getElementById("similar-users-results").innerHTML = items
      .map((item) => `<div class="analytics-item"><strong>User ${item.user_id}</strong> · similarity <strong>${Number(item.score).toFixed(3)}</strong></div>`)
      .join("");
  } catch (error) {
    setErrorState("similar-users-results", `Similar users could not be loaded. ${error.message}`);
  }
}

async function loadCommunities() {
  setLoading("communities-results", "Mapping viewer communities...");

  try {
    const data = await fetchJson(`${API_BASE}/analytics/communities?limit=5`);
    const items = data.items || [];

    if (!items.length) {
      setEmptyState("communities-results", "No communities were detected yet.");
      return;
    }

    document.getElementById("communities-results").innerHTML = items
      .map((community) => `<div class="analytics-item"><strong>Community ${community.community_id}</strong> · ${community.user_count} users · ${community.user_ids.join(", ")}</div>`)
      .join("");
  } catch (error) {
    setErrorState("communities-results", `Community data could not be loaded. ${error.message}`);
  }
}

async function loadPath(userA, userB) {
  setLoading("path-results", `Finding the shortest path from user ${userA} to user ${userB}...`);

  try {
    const data = await fetchJson(`${API_BASE}/analytics/path/users/${userA}/${userB}`);

    if (!data.found) {
      setEmptyState("path-results", data.message || "No connection was found between those users.");
      return;
    }

    const nodes = data.path?.nodes || [];
    const pathFlow = nodes
      .map((node) => `<span class="path-node">${node.type === "Movie" ? `Movie ${node.id}` : `User ${node.id}`}</span>`)
      .join('<span aria-hidden="true">→</span>');

    const relationships = data.path?.relationships || [];
    const summary = relationships.length
      ? `<div class="analytics-item"><strong>Hop count:</strong> ${data.path.hop_count} · <strong>Connections:</strong> ${relationships.length}</div>`
      : `<div class="analytics-item"><strong>Hop count:</strong> ${data.path.hop_count}</div>`;

    document.getElementById("path-results").innerHTML = `
      ${summary}
      <div class="path-flow">${pathFlow}</div>
    `;
  } catch (error) {
    setErrorState("path-results", `Connection path could not be loaded. ${error.message}`);
  }
}

async function askConcierge(question) {
  const chatMessages = document.getElementById("chat-messages");
  const userMessage = document.createElement("div");
  userMessage.className = "chat-message user";
  userMessage.innerHTML = `<p>${question}</p>`;
  chatMessages.appendChild(userMessage);

  const loadingMessage = document.createElement("div");
  loadingMessage.className = "chat-message bot";
  loadingMessage.innerHTML = `
    <div class="typing-bubble" aria-label="Thinking">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>
  `;
  chatMessages.appendChild(loadingMessage);

  try {
    const data = await fetchJson(`${API_BASE}/assistant/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });

    const results = Array.isArray(data.results) ? data.results : [];
    const list = results.length
      ? results
          .slice(0, 5)
          .map((movie) => `<li>${movie.title || "Unknown title"} — ${movie.explanation || "A strong recommendation."}</li>`)
          .join("")
      : "<li>No matched results were returned.</li>";

    loadingMessage.innerHTML = `
      <p><strong>Concierge:</strong> ${data.explanation || "Here are the best matches."}</p>
      <ul>${list}</ul>
    `;

    if (results.length > 0) {
      const suggestions = results.slice(0, 3).map((movie) => ({ title: movie.title, score: movie.score || movie.average_rating || 0 }));
      console.log("Assistant results:", suggestions);
    }
  } catch (error) {
    loadingMessage.innerHTML = `<p><strong>Concierge:</strong> I couldn't answer that request right now. ${error.message}</p>`;
  }

  chatMessages.scrollTop = chatMessages.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
  loadPopular();
  loadHiddenGems();
  setLoading("personalized-results", "Loading personalized picks...");
  setLoading("similar-results", "Loading similar titles...");
  loadSimilarUsers(1);
  loadCommunities();
  loadPath(1, 2);

  document.querySelector("[data-refresh='popular']").addEventListener("click", loadPopular);
  document.querySelector("[data-refresh='hidden-gems']").addEventListener("click", loadHiddenGems);

  document.getElementById("personalized-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const userId = document.getElementById("userIdInput").value;
    if (!userId || Number(userId) <= 0) {
      setErrorState("personalized-results", "Enter a valid positive user ID.");
      return;
    }
    await loadPersonalized(Number(userId));
  });

  document.getElementById("similar-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const movieId = document.getElementById("movieIdInput").value;
    if (!movieId || Number(movieId) <= 0) {
      setErrorState("similar-results", "Enter a valid positive movie ID.");
      return;
    }
    await loadSimilar(Number(movieId));
  });

  document.getElementById("similar-users-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const userId = document.getElementById("analyticsUserInput").value;
    if (!userId || Number(userId) <= 0) {
      setErrorState("similar-users-results", "Enter a valid positive user ID.");
      return;
    }
    await loadSimilarUsers(Number(userId));
  });

  document.getElementById("path-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const userA = document.getElementById("pathUserOne").value;
    const userB = document.getElementById("pathUserTwo").value;

    if (!userA || !userB || Number(userA) <= 0 || Number(userB) <= 0) {
      setErrorState("path-results", "Enter two valid positive user IDs.");
      return;
    }

    await loadPath(Number(userA), Number(userB));
  });

  document.getElementById("assistant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("assistant-input");
    const question = input.value.trim();

    if (!question) {
      input.focus();
      return;
    }

    input.value = "";
    await askConcierge(question);
  });
});

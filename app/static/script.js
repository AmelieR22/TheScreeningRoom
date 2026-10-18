const API_BASE = "";

const state = {
  popular: [],
  hidden: [],
  personalized: [],
  similar: [],
};

const metadataCache = new Map();
const metadataInFlight = new Map();
const MAX_METADATA_CONCURRENCY = 4;

function normalizeText(value, fallback) {
  if (typeof value !== "string") {
    return fallback;
  }

  const trimmed = value.trim();
  return trimmed || fallback;
}

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

function persistMetadataCache() {
  try {
    const serializable = Object.fromEntries(Array.from(metadataCache.entries()).map(([key, value]) => [String(key), value]));
    window.sessionStorage.setItem("tmdb-metadata-cache", JSON.stringify(serializable));
  } catch (error) {
    console.warn("TMDb metadata cache could not be persisted.", error);
  }
}

function restoreMetadataCache() {
  try {
    const rawValue = window.sessionStorage.getItem("tmdb-metadata-cache");
    if (!rawValue) {
      return;
    }

    const parsed = JSON.parse(rawValue);
    if (!parsed || typeof parsed !== "object") {
      return;
    }

    for (const [movieId, payload] of Object.entries(parsed)) {
      const numericId = Number(movieId);
      if (Number.isFinite(numericId)) {
        metadataCache.set(numericId, payload);
      }
    }
  } catch (error) {
    console.warn("TMDb metadata cache could not be restored.", error);
  }
}

restoreMetadataCache();

function setLoading(containerId, message = "Loading...") {
  const element = document.getElementById(containerId);
  if (!element) return;

  element.replaceChildren();
  const loadingState = document.createElement("div");
  loadingState.className = "loading-state";

  const bubble = document.createElement("div");
  bubble.className = "typing-bubble";
  bubble.setAttribute("aria-label", "Loading");

  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement("span");
    dot.className = "dot";
    bubble.appendChild(dot);
  }

  const label = document.createElement("div");
  label.textContent = message;
  label.style.marginTop = "8px";

  loadingState.appendChild(bubble);
  loadingState.appendChild(label);
  element.appendChild(loadingState);
}

function setEmptyState(containerId, message) {
  const element = document.getElementById(containerId);
  if (!element) return;

  const stateNode = document.createElement("div");
  stateNode.className = "empty-state";
  stateNode.textContent = message;
  element.replaceChildren(stateNode);
}

function setErrorState(containerId, message) {
  const element = document.getElementById(containerId);
  if (!element) return;

  const stateNode = document.createElement("div");
  stateNode.className = "error-state";
  stateNode.textContent = message;
  element.replaceChildren(stateNode);
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

function buildMovieMeta(item) {
  const meta = [];

  if (item.average_rating !== undefined) meta.push(`Avg ${Number(item.average_rating).toFixed(2)}`);
  if (item.rating_count !== undefined) meta.push(`${item.rating_count} ratings`);
  if (item.supporter_count !== undefined) meta.push(`${item.supporter_count} supporters`);
  if (item.genre_similarity !== undefined) meta.push(`Genre ${Number(item.genre_similarity).toFixed(2)}`);
  if (item.audience_similarity !== undefined) meta.push(`Audience ${Number(item.audience_similarity).toFixed(2)}`);

  return meta;
}

async function getMovieMetadata(movieId) {
  if (metadataCache.has(movieId)) {
    return metadataCache.get(movieId);
  }

  if (metadataInFlight.has(movieId)) {
    return metadataInFlight.get(movieId);
  }

  while (metadataInFlight.size >= MAX_METADATA_CONCURRENCY) {
    await Promise.race(Array.from(metadataInFlight.values()));
  }

  const request = fetchJson(`${API_BASE}/movies/${movieId}/metadata`)
    .then((payload) => {
      metadataCache.set(movieId, payload);
      persistMetadataCache();
      return payload;
    })
    .catch((error) => {
      console.warn(`TMDb metadata unavailable for movie ${movieId}:`, error);
      return null;
    })
    .finally(() => {
      metadataInFlight.delete(movieId);
    });

  metadataInFlight.set(movieId, request);
  return request;
}

function applyPosterState(posterImage, posterWrap) {
  posterImage.hidden = true;
  posterWrap.classList.add("poster-missing");
}

function updateSynopsisToggle(explainer, toggle) {
  const text = explainer.textContent.trim();
  if (!text) {
    toggle.hidden = true;
    return;
  }

  const expanded = explainer.classList.contains("expanded");
  const hasOverflow = explainer.scrollHeight > explainer.clientHeight + 1;

  if (expanded) {
    toggle.hidden = false;
    toggle.textContent = "Read less";
    toggle.setAttribute("aria-expanded", "true");
    return;
  }

  const needsToggle = hasOverflow || text.length > 180;
  toggle.hidden = !needsToggle;
  toggle.textContent = "Read more";
  toggle.setAttribute("aria-expanded", "false");
}

async function hydrateMetadataCard({ movieId, title, posterImage, posterWrap, overview, defaultSummary, toggle }) {
  const metadata = await getMovieMetadata(movieId);
  if (!metadata) {
    applyPosterState(posterImage, posterWrap);
    overview.textContent = defaultSummary;
    requestAnimationFrame(() => updateSynopsisToggle(overview, toggle));
    return;
  }

  if (metadata.poster_url) {
    posterWrap.classList.remove("poster-missing");
    posterImage.src = metadata.poster_url;
    posterImage.alt = `${title} poster`;
    posterImage.hidden = false;
    posterImage.onerror = () => {
      posterImage.hidden = true;
      posterWrap.classList.add("poster-missing");
    };
  } else {
    applyPosterState(posterImage, posterWrap);
  }

  const tmdbOverview = normalizeText(metadata.overview, defaultSummary);
  overview.textContent = tmdbOverview;
  requestAnimationFrame(() => updateSynopsisToggle(overview, toggle));
}

function createMovieCard(item, index) {
  const movieId = item.movie_id ?? item.id ?? index + 1;
  const title = normalizeText(item.title, "Untitled film");
  const score = item.score ?? item.average_rating ?? item.genre_similarity ?? null;
  const ratingText = score !== null ? `${Number(score).toFixed(2)}` : "Fresh pick";
  const badge = item.source === "fallback" ? "Fallback" : item.source === "collaborative" ? "Recommended" : "Featured";
  const defaultSummary = normalizeText(
    item.explanation || item.summary || "A standout recommendation from the film graph.",
    "A standout recommendation from the film graph.",
  );
  const metaItems = buildMovieMeta(item);

  const article = document.createElement("article");
  article.className = "movie-card";
  article.style.setProperty("--poster-gradient", movieGradient(movieId + index));

  const badgeNode = document.createElement("span");
  badgeNode.className = "card-badge";
  badgeNode.textContent = badge;
  article.appendChild(badgeNode);

  const posterWrap = document.createElement("div");
  posterWrap.className = "movie-poster";

  const posterImage = document.createElement("img");
  posterImage.className = "movie-poster-image";
  posterImage.alt = `${title} poster`;
  posterImage.loading = "lazy";
  posterImage.decoding = "async";
  posterImage.hidden = true;

  posterWrap.appendChild(posterImage);
  article.appendChild(posterWrap);

  const body = document.createElement("div");
  body.className = "movie-card-body";

  const titleNode = document.createElement("h4");
  titleNode.textContent = title;

  const metaRow = document.createElement("div");
  metaRow.className = "card-meta";

  const movieLabel = document.createElement("span");
  movieLabel.textContent = `Movie #${movieId}`;

  const scoreNode = document.createElement("span");
  scoreNode.className = "card-score";
  scoreNode.textContent = ratingText;

  metaRow.appendChild(movieLabel);
  metaRow.appendChild(scoreNode);

  const detailList = document.createElement("div");
  detailList.className = "card-detail-list";

  for (const entry of metaItems) {
    const entryNode = document.createElement("span");
    entryNode.textContent = entry;
    detailList.appendChild(entryNode);
  }

  const explainer = document.createElement("p");
  explainer.className = "card-explainer clamped-synopsis";
  explainer.textContent = defaultSummary;

  const synopsisToggle = document.createElement("button");
  synopsisToggle.type = "button";
  synopsisToggle.className = "synopsis-toggle";
  synopsisToggle.hidden = true;
  synopsisToggle.textContent = "Read more";
  synopsisToggle.setAttribute("aria-expanded", "false");
  synopsisToggle.addEventListener("click", () => {
    const isExpanded = explainer.classList.toggle("expanded");
    updateSynopsisToggle(explainer, synopsisToggle);
    if (isExpanded) {
      explainer.setAttribute("aria-expanded", "true");
    } else {
      explainer.setAttribute("aria-expanded", "false");
    }
  });

  body.appendChild(titleNode);
  body.appendChild(metaRow);
  if (metaItems.length > 0) {
    body.appendChild(detailList);
  }
  body.appendChild(explainer);
  body.appendChild(synopsisToggle);
  article.appendChild(body);

  void hydrateMetadataCard({
    movieId,
    title,
    posterImage,
    posterWrap,
    overview: explainer,
    defaultSummary,
    toggle: synopsisToggle,
  });

  return article;
}

function renderMovieCards(items, containerId, options = {}) {
  const element = document.getElementById(containerId);
  if (!element) return;

  if (!Array.isArray(items) || items.length === 0) {
    setEmptyState(containerId, options.emptyMessage || "No films to recommend yet.");
    return;
  }

  element.replaceChildren();

  for (const [index, item] of items.entries()) {
    const card = createMovieCard(item, index);
    element.appendChild(card);
  }
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

    const container = document.getElementById("similar-users-results");
    container.replaceChildren();

    for (const item of items) {
      const row = document.createElement("div");
      row.className = "analytics-item";
      const userText = document.createElement("strong");
      userText.textContent = `User ${item.user_id}`;
      const similarity = document.createElement("span");
      similarity.textContent = ` · similarity ${Number(item.score).toFixed(3)}`;
      row.appendChild(userText);
      row.appendChild(similarity);
      container.appendChild(row);
    }
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

    const container = document.getElementById("communities-results");
    container.replaceChildren();

    for (const community of items) {
      const row = document.createElement("div");
      row.className = "analytics-item";
      const label = document.createElement("strong");
      label.textContent = `Community ${community.community_id}`;
      const summary = document.createElement("span");
      summary.textContent = ` · ${community.user_count} users · ${community.user_ids.join(", ")}`;
      row.appendChild(label);
      row.appendChild(summary);
      container.appendChild(row);
    }
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

    const container = document.getElementById("path-results");
    container.replaceChildren();

    const summary = document.createElement("div");
    summary.className = "analytics-item";
    const summaryLabel = document.createElement("strong");
    summaryLabel.textContent = "Hop count:";
    const summaryValue = document.createElement("span");
    summaryValue.textContent = ` ${data.path.hop_count}`;
    summary.appendChild(summaryLabel);
    summary.appendChild(summaryValue);
    container.appendChild(summary);

    const nodes = data.path?.nodes || [];
    const flow = document.createElement("div");
    flow.className = "path-flow";

    for (let index = 0; index < nodes.length; index += 1) {
      const node = nodes[index];
      const nodeChip = document.createElement("span");
      nodeChip.className = "path-node";
      nodeChip.textContent = node.type === "Movie" ? `Movie ${node.id}` : `User ${node.id}`;
      flow.appendChild(nodeChip);

      if (index < nodes.length - 1) {
        const arrow = document.createElement("span");
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "→";
        flow.appendChild(arrow);
      }
    }

    container.appendChild(flow);
  } catch (error) {
    setErrorState("path-results", `Connection path could not be loaded. ${error.message}`);
  }
}

async function askConcierge(question) {
  const chatMessages = document.getElementById("chat-messages");

  const userMessage = document.createElement("div");
  userMessage.className = "chat-message user";
  const userParagraph = document.createElement("p");
  userParagraph.textContent = question;
  userMessage.appendChild(userParagraph);
  chatMessages.appendChild(userMessage);

  const loadingMessage = document.createElement("div");
  loadingMessage.className = "chat-message bot";

  const loadingBubble = document.createElement("div");
  loadingBubble.className = "typing-bubble";
  loadingBubble.setAttribute("aria-label", "Thinking");

  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement("span");
    dot.className = "dot";
    loadingBubble.appendChild(dot);
  }

  loadingMessage.appendChild(loadingBubble);
  chatMessages.appendChild(loadingMessage);

  try {
    const data = await fetchJson(`${API_BASE}/assistant/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    });

    const results = Array.isArray(data.results) ? data.results : [];
    const list = document.createElement("ul");

    if (results.length > 0) {
      for (const movie of results.slice(0, 5)) {
        const item = document.createElement("li");
        item.textContent = `${movie.title || "Unknown title"} — ${movie.explanation || "A strong recommendation."}`;
        list.appendChild(item);
      }
    } else {
      const item = document.createElement("li");
      item.textContent = "No matched results were returned.";
      list.appendChild(item);
    }

    const responseMessage = document.createElement("p");
    const responseLabel = document.createElement("strong");
    responseLabel.textContent = "Concierge:";
    responseMessage.appendChild(responseLabel);
    responseMessage.appendChild(document.createTextNode(` ${data.explanation || "Here are the best matches."}`));

    loadingMessage.replaceChildren(responseMessage, list);

    if (results.length > 0) {
      const suggestions = results.slice(0, 3).map((movie) => ({ title: movie.title, score: movie.score || movie.average_rating || 0 }));
      console.log("Assistant results:", suggestions);
    }
  } catch (error) {
    const responseMessage = document.createElement("p");
    const responseLabel = document.createElement("strong");
    responseLabel.textContent = "Concierge:";
    responseMessage.appendChild(responseLabel);
    responseMessage.appendChild(document.createTextNode(` I couldn't answer that request right now. ${error.message}`));
    loadingMessage.replaceChildren(responseMessage);
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

  const refreshPopularButton = document.querySelector("[data-refresh='popular']");
  const refreshHiddenButton = document.querySelector("[data-refresh='hidden-gems']");

  if (refreshPopularButton) {
    refreshPopularButton.addEventListener("click", loadPopular);
  }

  if (refreshHiddenButton) {
    refreshHiddenButton.addEventListener("click", loadHiddenGems);
  }

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

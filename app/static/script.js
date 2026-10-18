const API_BASE = "";
const PROFILE_STORAGE_KEY = "screening-room-profile-id";

const state = {
  popular: [],
  hidden: [],
  personalized: [],
  similar: [],
  profileOptions: [],
  selectedProfileId: localStorage.getItem(PROFILE_STORAGE_KEY) || "",
  profileActivity: {
    username: "",
    platformUserId: "",
    watchlist: [],
    watched: [],
    reactions: [],
  },
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

function setModalStatus(message, isError = false) {
  const statusNode = document.getElementById("movie-search-status");
  if (!statusNode) return;
  statusNode.textContent = message;
  statusNode.style.color = isError ? "#e7a6a6" : "#f0d8a4";
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

function renderProfileStatus(message, isError = false) {
  const statusNode = document.getElementById("profile-status");
  if (!statusNode) return;

  statusNode.textContent = message;
  statusNode.classList.toggle("error", Boolean(isError));
}

function renderProfileActivitySummary(data) {
  const summaryNode = document.getElementById("profile-summary");
  if (!summaryNode) return;

  if (!data || !data.platformUserId) {
    summaryNode.textContent = "Pick a profile to load your film activity.";
    return;
  }

  const watchlistCount = Array.isArray(data.watchlist) ? data.watchlist.length : 0;
  const likedCount = (Array.isArray(data.reactions) ? data.reactions : []).filter((item) => String(item.reaction || "").toLowerCase() === "liked").length;
  const dislikedCount = (Array.isArray(data.reactions) ? data.reactions : []).filter((item) => String(item.reaction || "").toLowerCase() === "disliked").length;

  summaryNode.innerHTML = `
    <strong>${normalizeText(data.username, "Profile")}</strong>
    <span>Watchlist: ${watchlistCount}</span>
    <span>Liked: ${likedCount}</span>
    <span>Disliked: ${dislikedCount}</span>
  `;
}

function renderProfileList(containerId, items, emptyMessage, formatter) {
  const container = document.getElementById(containerId);
  if (!container) return;

  container.replaceChildren();

  if (!Array.isArray(items) || items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "profile-empty";
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }

  for (const item of items) {
    const row = document.createElement("div");
    row.className = "profile-list-item";
    row.appendChild(formatter(item));
    container.appendChild(row);
  }
}

function renderMyProfile(data) {
  const profileData = data || { watchlist: [], reactions: [] };
  const reactions = Array.isArray(profileData.reactions) ? profileData.reactions : [];
  renderProfileActivitySummary(profileData);
  renderProfileList("profile-watchlist", profileData.watchlist || [], "No titles on the watchlist yet.", (item) => {
    const node = document.createElement("span");
    node.textContent = `${item.title || `Movie ${item.movie_id}`}`;
    return node;
  });

  renderProfileList("profile-liked", reactions.filter((item) => String(item.reaction || "").toLowerCase() === "liked"), "No liked movies yet.", (item) => {
    const node = document.createElement("span");
    node.textContent = `${item.title || `Movie ${item.movie_id}`}`;
    return node;
  });

  renderProfileList("profile-disliked", reactions.filter((item) => String(item.reaction || "").toLowerCase() === "disliked"), "No disliked movies yet.", (item) => {
    const node = document.createElement("span");
    node.textContent = `${item.title || `Movie ${item.movie_id}`}`;
    return node;
  });
}

function getMovieActionState(movieId, action) {
  const { watchlist = [], reactions = [] } = state.profileActivity || {};

  const normalizedId = Number(movieId);
  switch (action) {
    case "watchlist":
      return watchlist.some((item) => Number(item.movie_id) === normalizedId);
    case "liked":
      return reactions.some((item) => Number(item.movie_id) === normalizedId && String(item.reaction).toLowerCase() === "liked");
    case "disliked":
      return reactions.some((item) => Number(item.movie_id) === normalizedId && String(item.reaction).toLowerCase() === "disliked");
    default:
      return false;
  }
}

function syncMovieCardButtonState(card) {
  if (!card || !card.dataset.movieId) return;
  const movieId = Number(card.dataset.movieId);
  const actionButtons = card.querySelectorAll("[data-profile-action]");
  actionButtons.forEach((button) => {
    const action = button.dataset.profileAction;
    const active = getMovieActionState(movieId, action);
    button.classList.toggle("active", active);
    button.disabled = !state.selectedProfileId;
    const actionLabel = button.dataset.actionLabel || action;
    const nextText = typeof actionLabel === "string" ? actionLabel : action;
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent.trim();
    }
    if (action === "liked") {
      button.textContent = active ? "Liked" : button.dataset.defaultLabel;
    } else if (action === "disliked") {
      button.textContent = active ? "Disliked" : button.dataset.defaultLabel;
    } else {
      button.textContent = active ? `${nextText} ✓` : button.dataset.defaultLabel;
    }
  });
}

async function loadProfileActivity() {
  const profileId = state.selectedProfileId;
  const activityContainer = document.getElementById("profile-summary");

  if (!profileId) {
    state.profileActivity = { username: "", platformUserId: "", watchlist: [], watched: [], reactions: [] };
    if (activityContainer) {
      activityContainer.textContent = "Pick a profile to load your film activity.";
    }
    renderProfileList("profile-watchlist", [], "No titles on the watchlist yet.", (item) => {
      const node = document.createElement("span");
      node.textContent = `${item.title || `Movie ${item.movie_id}`}`;
      return node;
    });
    renderProfileList("profile-watched", [], "No watched titles yet.", (item) => {
      const node = document.createElement("span");
      node.textContent = `${item.title || `Movie ${item.movie_id}`}`;
      return node;
    });
    renderProfileList("profile-reactions", [], "No reactions saved yet.", (item) => {
      const node = document.createElement("span");
      node.textContent = `${item.title || `Movie ${item.movie_id}`} · ${item.reaction || "reaction"}`;
      return node;
    });
    document.querySelectorAll(".movie-card").forEach(syncMovieCardButtonState);
    return;
  }

  try {
    const profile = await fetchJson(`${API_BASE}/platform-users/${profileId}/activity`);
    state.profileActivity = profile;
    renderMyProfile(profile);
    renderProfileStatus(`Loaded profile ${profile.username || profile.platformUserId}.`);
    document.querySelectorAll(".movie-card").forEach(syncMovieCardButtonState);
  } catch (error) {
    state.profileActivity = { username: "", platformUserId: "", watchlist: [], watched: [], reactions: [] };
    renderProfileStatus(`Could not load this profile. ${error.message}`, true);
    document.querySelectorAll(".movie-card").forEach(syncMovieCardButtonState);
  }
}

async function createPlatformProfile(username) {
  const cleaned = normalizeText(username, "").trim();
  if (!cleaned) {
    renderProfileStatus("Profile names must be at least 3 characters long.", true);
    return;
  }

  try {
    const created = await fetchJson(`${API_BASE}/platform-users`, {
      method: "POST",
      body: JSON.stringify({ username: cleaned }),
    });

    await loadPlatformProfiles();
    state.selectedProfileId = created.platformUserId || created.platformUserId || "";
    localStorage.setItem(PROFILE_STORAGE_KEY, state.selectedProfileId);
    const selectNode = document.getElementById("profile-select");
    if (selectNode) {
      selectNode.value = state.selectedProfileId;
    }
    renderProfileStatus(`Profile ${created.username || cleaned} is ready.`);
    await loadProfileActivity();
  } catch (error) {
    renderProfileStatus(`Could not create this profile. ${error.message}`, true);
  }
}

async function loadPlatformProfiles() {
  try {
    const payload = await fetchJson(`${API_BASE}/platform-users`);
    const profiles = Array.isArray(payload.items) ? payload.items : [];
    state.profileOptions = profiles;

    const selectNode = document.getElementById("profile-select");
    if (!selectNode) return;

    selectNode.replaceChildren();

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = profiles.length ? "Choose a profile" : "No profiles yet";
    selectNode.appendChild(placeholder);

    for (const profile of profiles) {
      const option = document.createElement("option");
      option.value = profile.platformUserId;
      option.textContent = profile.username || profile.platformUserId;
      selectNode.appendChild(option);
    }

    if (!state.selectedProfileId && profiles.length) {
      state.selectedProfileId = profiles[0].platformUserId;
      localStorage.setItem(PROFILE_STORAGE_KEY, state.selectedProfileId);
    }

    const matchingProfile = profiles.find((profile) => profile.platformUserId === state.selectedProfileId);
    if (matchingProfile) {
      selectNode.value = state.selectedProfileId;
    } else if (profiles.length) {
      state.selectedProfileId = profiles[0].platformUserId;
      localStorage.setItem(PROFILE_STORAGE_KEY, state.selectedProfileId);
      selectNode.value = state.selectedProfileId;
    } else {
      state.selectedProfileId = "";
      localStorage.removeItem(PROFILE_STORAGE_KEY);
      selectNode.value = "";
    }

    const personalizedInput = document.getElementById("userIdInput");
    if (personalizedInput && personalizedInput.value.trim() === "") {
      const selectedProfile = profiles.find((profile) => profile.platformUserId === state.selectedProfileId);
      if (selectedProfile) {
        personalizedInput.value = selectedProfile.username || selectedProfile.platformUserId;
      }
    }
  } catch (error) {
    renderProfileStatus(`Profile list could not be loaded. ${error.message}`, true);
  }
}

function setSelectedProfile(profileId) {
  state.selectedProfileId = profileId || "";

  if (profileId) {
    localStorage.setItem(PROFILE_STORAGE_KEY, profileId);
  } else {
    localStorage.removeItem(PROFILE_STORAGE_KEY);
  }

  const selectNode = document.getElementById("profile-select");
  if (selectNode) {
    selectNode.value = profileId || "";
  }

  const personalizedInput = document.getElementById("userIdInput");
  if (personalizedInput && personalizedInput.dataset.userEdited !== "true") {
    const matchedProfile = state.profileOptions.find((profile) => profile.platformUserId === profileId);
    personalizedInput.value = matchedProfile ? (matchedProfile.username || matchedProfile.platformUserId) : "";
  }

  if (profileId) {
    loadProfileActivity();
  } else {
    renderProfileStatus("Select or create a profile to save your watchlist, reactions, and ratings.");
  }
}

function createProfileActionButton(label, tone, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `tiny-action ${tone}`;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

async function updateMovieProfileAction(profileId, movieId, action, payload = {}) {
  if (!profileId) {
    renderProfileStatus("Select a profile before saving movie actions.", true);
    return;
  }

  const actionState = getMovieActionState(movieId, action);

  try {
    const urlBase = `${API_BASE}/platform-users/${profileId}`;
    let method = "POST";
    let url = "";
    let body = {};

    if (action === "watchlist") {
      url = `${urlBase}/watchlist`;
      body = { movie_id: movieId };
      if (actionState) {
        method = "DELETE";
        url = `${urlBase}/watchlist/${movieId}`;
        body = {};
      }
    } else if (action === "liked" || action === "disliked") {
      url = `${urlBase}/reactions`;
      body = { movie_id: movieId, reaction: action === "liked" ? "liked" : "disliked" };
      if (actionState) {
        method = "DELETE";
        url = `${urlBase}/reactions/${movieId}`;
        body = {};
      }
    }

    const requestOptions = method === "POST" ? { method, body: JSON.stringify(body) } : { method };
    await fetchJson(url, requestOptions);

    renderProfileStatus(`Saved to profile ${profileId}.`);
    await loadProfileActivity();
  } catch (error) {
    renderProfileStatus(`Could not save the movie action. ${error.message}`, true);
  }
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
  article.dataset.movieId = String(movieId);
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

  const actionGroup = document.createElement("div");
  actionGroup.className = "movie-actions";

  const profileActionButtons = [];
  const createAction = (label, tone, actionName) => {
    const button = createProfileActionButton(label, tone, async () => {
      await updateMovieProfileAction(state.selectedProfileId, movieId, actionName);
    });
    button.dataset.profileAction = actionName;
    button.dataset.actionLabel = label;
    if (!state.selectedProfileId) {
      button.disabled = true;
    }
    const active = getMovieActionState(movieId, actionName);
    button.classList.toggle("active", active);
    profileActionButtons.push(button);
    return button;
  };

  profileActionButtons.push(createAction("Watchlist", "neutral", "watchlist"));
  profileActionButtons.push(createAction("Like", "positive", "liked"));
  profileActionButtons.push(createAction("Dislike", "negative", "disliked"));

  actionGroup.append(...profileActionButtons);

  body.appendChild(titleNode);
  body.appendChild(metaRow);
  if (metaItems.length > 0) {
    body.appendChild(detailList);
  }
  body.appendChild(explainer);
  body.appendChild(synopsisToggle);
  body.appendChild(actionGroup);
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

async function resolvePlatformProfileLookup(inputValue) {
  const trimmed = inputValue.trim();
  if (!trimmed) {
    throw new Error("Enter a user ID, username, or platform profile ID.");
  }

  if (trimmed.startsWith("pf_")) {
    const payload = await fetchJson(`${API_BASE}/platform-users/${trimmed}`);
    return payload;
  }

  if (/^\d+$/.test(trimmed)) {
    return null;
  }

  const payload = await fetchJson(`${API_BASE}/platform-users/lookup?username=${encodeURIComponent(trimmed)}`);
  return payload;
}

async function loadPersonalizedByIdentifier(rawValue) {
  const value = String(rawValue || "").trim();
  if (!value) {
    setErrorState("personalized-results", "Enter a valid MovieLens user ID, platform username, or profile ID.");
    return;
  }

  setLoading("personalized-results", `Loading recommendations for ${value}...`);

  try {
    if (/^\d+$/.test(value)) {
      const numericUserId = Number(value);
      const data = await fetchJson(`${API_BASE}/recommendations/personalized/${numericUserId}?limit=6`);
      const items = data.items || [];
      renderMovieCards(items, "personalized-results", { emptyMessage: `No recommendations available for user ${numericUserId}.` });
      state.personalized = items;
      return;
    }

    const profile = await resolvePlatformProfileLookup(value);
    if (!profile || !profile.platformUserId) {
      throw new Error(`No platform profile matched "${value}".`);
    }

    const data = await fetchJson(`${API_BASE}/recommendations/platform/${profile.platformUserId}?limit=6`);
    const items = data.items || [];
    renderMovieCards(items, "personalized-results", { emptyMessage: `No personalized profile picks are available for ${profile.username || value}.` });
    state.personalized = items;
  } catch (error) {
    setErrorState("personalized-results", `Could not load personalized picks for "${value}". ${error.message}`);
  }
}

async function loadPersonalized(userId) {
  await loadPersonalizedByIdentifier(String(userId));
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

async function renderPathNode(node) {
  const nodeItem = document.createElement("div");
  nodeItem.className = `path-node ${node.type === "Movie" ? "movie-node" : "user-node"}`;

  if (node.type === "Movie") {
    const posterWrap = document.createElement("div");
    posterWrap.className = "path-poster";

    const posterImage = document.createElement("img");
    posterImage.className = "path-poster-image";
    posterImage.alt = `${normalizeText(node.title, `Movie ${node.id}`)} poster`;
    posterImage.hidden = true;

    const posterFallback = document.createElement("div");
    posterFallback.className = "path-poster-fallback";
    posterFallback.textContent = "🎬";

    posterWrap.appendChild(posterImage);
    posterWrap.appendChild(posterFallback);

    const copy = document.createElement("div");
    copy.className = "path-node-copy";

    const title = document.createElement("strong");
    title.textContent = normalizeText(node.title, `Movie ${node.id}`);

    const details = document.createElement("span");
    details.textContent = `MovieLens #${node.id}`;

    copy.appendChild(title);
    copy.appendChild(details);
    nodeItem.appendChild(posterWrap);
    nodeItem.appendChild(copy);

    try {
      const metadata = await getMovieMetadata(Number(node.id));
      if (metadata && metadata.poster_url) {
        posterImage.src = metadata.poster_url;
        posterImage.alt = `${title.textContent} poster`;
        posterImage.hidden = false;
        posterFallback.hidden = true;
        posterImage.onerror = () => {
          posterImage.hidden = true;
          posterFallback.hidden = false;
        };
      }
    } catch (error) {
      console.warn(`No poster metadata available for movie ${node.id}:`, error);
    }

    return nodeItem;
  }

  const userLabel = document.createElement("strong");
  userLabel.textContent = `User ${node.id}`;
  nodeItem.appendChild(userLabel);
  return nodeItem;
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

    const renderedNodes = await Promise.all(nodes.map(renderPathNode));
    renderedNodes.forEach((nodeChip, index) => {
      flow.appendChild(nodeChip);
      if (index < renderedNodes.length - 1) {
        const arrow = document.createElement("span");
        arrow.className = "path-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "→";
        flow.appendChild(arrow);
      }
    });

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

async function searchMovieIds(query) {
  const cleaned = String(query || "").trim();
  const statusNode = document.getElementById("movie-search-status");
  const resultsNode = document.getElementById("movie-search-results");

  if (!cleaned) {
    setModalStatus("Enter a movie title to search.", true);
    setEmptyState("movie-search-results", "Try a title like 'matrix' or 'before sunrise'.");
    return;
  }

  setLoading("movie-search-results", `Searching for “${cleaned}”…`);
  setModalStatus("Looking for matches...");

  try {
    const data = await fetchJson(`${API_BASE}/movies/search?q=${encodeURIComponent(cleaned)}&limit=8`);
    const items = Array.isArray(data.items) ? data.items : [];

    if (!items.length) {
      setModalStatus(`No results found for “${cleaned}”.`, true);
      setEmptyState("movie-search-results", "No matching movie titles were found.");
      return;
    }

    setModalStatus(`Found ${items.length} match${items.length === 1 ? "" : "es"}.`);
    resultsNode.replaceChildren();

    const rows = await Promise.all(
      items.map(async (movie) => {
        const item = document.createElement("div");
        item.className = "movie-search-result";

        const posterWrap = document.createElement("div");
        posterWrap.className = "movie-search-poster";
        const posterImage = document.createElement("img");
        posterImage.alt = `${movie.title || "Movie"} poster`;
        posterImage.loading = "lazy";
        posterImage.hidden = true;

        const fallback = document.createElement("span");
        fallback.textContent = "🎬";
        posterWrap.appendChild(posterImage);
        posterWrap.appendChild(fallback);

        try {
          const metadata = await getMovieMetadata(Number(movie.movie_id));
          if (metadata && metadata.poster_url) {
            posterImage.src = metadata.poster_url;
            posterImage.hidden = false;
            fallback.hidden = true;
            posterImage.onerror = () => {
              posterImage.hidden = true;
              fallback.hidden = false;
            };
          }
        } catch (error) {
          console.warn(`Poster metadata unavailable for movie ${movie.movie_id}:`, error);
        }

        const meta = document.createElement("div");
        meta.className = "movie-search-meta";

        const title = document.createElement("strong");
        title.textContent = movie.title || `Movie ${movie.movie_id}`;

        const details = document.createElement("span");
        details.textContent = [movie.year ? String(movie.year) : "Unknown year", `MovieLens ID: ${movie.movie_id}`].join(" • ");

        meta.appendChild(title);
        meta.appendChild(details);

        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "copy-id-button";
        copyButton.textContent = "Copy ID";
        copyButton.addEventListener("click", async () => {
          const value = String(movie.movie_id);
          try {
            await navigator.clipboard.writeText(value);
            setModalStatus(`Copied MovieLens ID ${value}.`);
            copyButton.textContent = "Copied";
            window.setTimeout(() => {
              copyButton.textContent = "Copy ID";
            }, 1200);
          } catch (error) {
            setModalStatus(`Could not copy MovieLens ID ${value}.`, true);
          }
        });

        item.appendChild(posterWrap);
        item.appendChild(meta);
        item.appendChild(copyButton);
        return item;
      }),
    );

    resultsNode.replaceChildren(...rows);
  } catch (error) {
    setModalStatus(`Could not search movie titles. ${error.message}`, true);
    setErrorState("movie-search-results", `Search failed. ${error.message}`);
  }
}

function openMovieSearchModal() {
  const modal = document.getElementById("movie-search-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  const input = document.getElementById("movie-search-input");
  if (input) {
    window.setTimeout(() => input.focus(), 60);
  }
}

function closeMovieSearchModal() {
  const modal = document.getElementById("movie-search-modal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
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

  const personalizedInput = document.getElementById("userIdInput");
  if (personalizedInput) {
    personalizedInput.addEventListener("input", () => {
      personalizedInput.dataset.userEdited = "true";
    });
    personalizedInput.addEventListener("focus", () => {
      if (!personalizedInput.value.trim()) {
        personalizedInput.dataset.userEdited = "false";
      }
    });
  }

  document.getElementById("personalized-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const userValue = document.getElementById("userIdInput").value;
    const trimmed = userValue.trim();
    if (!trimmed) {
      setErrorState("personalized-results", "Enter a valid MovieLens user ID, platform username, or profile ID.");
      return;
    }
    await loadPersonalizedByIdentifier(trimmed);
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
    const userId = document.getElementById("analyticsUserInput").value.trim();
    if (!userId) {
      setErrorState("similar-users-results", "Enter a valid MovieLens user ID, platform username, or profile ID.");
      return;
    }
    await loadSimilarUsers(userId);
  });

  document.getElementById("path-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const userA = document.getElementById("pathUserOne").value.trim();
    const userB = document.getElementById("pathUserTwo").value.trim();

    if (!userA || !userB) {
      setErrorState("path-results", "Enter two valid MovieLens user IDs, platform usernames, or platform profile IDs.");
      return;
    }

    await loadPath(userA, userB);
  });

  const movieSearchOpenButton = document.getElementById("movie-search-open");
  const movieSearchModal = document.getElementById("movie-search-modal");
  const movieSearchCloseButton = document.getElementById("movie-search-close");
  const movieSearchForm = document.getElementById("movie-search-form");

  if (movieSearchOpenButton) {
    movieSearchOpenButton.addEventListener("click", openMovieSearchModal);
  }

  if (movieSearchCloseButton) {
    movieSearchCloseButton.addEventListener("click", closeMovieSearchModal);
  }

  if (movieSearchModal) {
    movieSearchModal.addEventListener("click", (event) => {
      if (event.target instanceof HTMLElement && event.target.hasAttribute("data-close-movie-search")) {
        closeMovieSearchModal();
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && movieSearchModal && !movieSearchModal.classList.contains("hidden")) {
      closeMovieSearchModal();
    }
  });

  if (movieSearchForm) {
    movieSearchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const target = document.getElementById("movie-search-input");
      await searchMovieIds(target ? target.value : "");
    });
  }

  const profileSelect = document.getElementById("profile-select");
  const profileCreateForm = document.getElementById("profile-create-form");

  if (profileSelect) {
    profileSelect.addEventListener("change", (event) => {
      setSelectedProfile(event.target.value);
    });
  }

  if (profileCreateForm) {
    profileCreateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = document.getElementById("profile-username-input");
      const username = input ? input.value : "";
      if (!username.trim()) {
        renderProfileStatus("Add a profile name before creating a new profile.", true);
        return;
      }
      input.value = "";
      await createPlatformProfile(username);
    });
  }

  loadPlatformProfiles();
  if (state.selectedProfileId) {
    setSelectedProfile(state.selectedProfileId);
  }

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

"use strict";

const state = {
  directory: null,
  status: null,
  observations: new Map(),
  stale: false,
};

const elements = {
  grid: document.querySelector("#mesh-grid"),
  message: document.querySelector("#directory-message"),
  search: document.querySelector("#search"),
  region: document.querySelector("#region-filter"),
  operation: document.querySelector("#operation-filter"),
  signal: document.querySelector("#signal-filter"),
  listed: document.querySelector("#stat-listed"),
  up: document.querySelector("#stat-up"),
  latency: document.querySelector("#stat-latency"),
  checked: document.querySelector("#stat-checked"),
};

function node(tag, className, text) {
  const selected = document.createElement(tag);
  if (className) selected.className = className;
  if (text !== undefined) selected.textContent = text;
  return selected;
}

function appendOption(select, value, label) {
  const option = node("option", "", label);
  option.value = value;
  select.append(option);
}

function observationFor(mesh) {
  const observation = state.observations.get(mesh.peer_id);
  if (!observation || observation.registry_status !== mesh.status || state.stale) {
    return {
      state: "not_checked",
      response_time_ms: null,
      http_status: null,
      checked_at: null,
    };
  }
  return observation;
}

function stateName(value) {
  return value === "not_checked" ? "Not checked" : `${value[0].toUpperCase()}${value.slice(1)}`;
}

function formatAge(value) {
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const minutes = Math.floor(elapsed / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

function speedLabel(milliseconds) {
  if (milliseconds === null) return "—";
  return `${milliseconds} ms`;
}

function metric(label, value) {
  const wrapper = node("div");
  wrapper.append(node("b", "", value), node("small", "", label));
  return wrapper;
}

function tag(text, extraClass = "") {
  return node("span", `tag${extraClass ? ` ${extraClass}` : ""}`, text);
}

function createCard(mesh) {
  const observation = observationFor(mesh);
  const card = node("article", "mesh-card");
  const header = node("div", "mesh-card-header");
  const identity = node("div");
  identity.append(node("span", "peer-id", mesh.peer_id), node("h3", "", mesh.display_name));
  const signal = node("span", "state-label");
  signal.append(node("i", `state-dot ${observation.state}`), document.createTextNode(stateName(observation.state)));
  header.append(identity, signal);

  const registry = node("div", "registry-row");
  registry.append(tag(`Registry: ${mesh.status}`, "registry"));
  mesh.regions.forEach((region) => registry.append(tag(region)));

  const endpoint = node("a", "endpoint", mesh.endpoint);
  endpoint.href = mesh.endpoint;
  endpoint.rel = "noopener noreferrer";

  const operations = node("div", "registry-row");
  mesh.operations.forEach((operation) => operations.append(tag(`${operation.name}/${operation.version}`)));

  const metrics = node("div", "metric-row");
  const historical = mesh.stats;
  metrics.append(
    metric("latest response", speedLabel(observation.response_time_ms)),
    metric("HTTP", observation.http_status === null ? "—" : String(observation.http_status)),
    metric("historical p95", historical ? `${historical.latency_ms.p95} ms` : "—"),
  );

  const footer = node("div", "mesh-footer");
  const operator = node("a", "", mesh.operator.name);
  operator.href = mesh.operator.website;
  operator.rel = "noopener noreferrer";
  const fingerprint = node("span", "peer-id", `${mesh.availability_identity.key_id.slice(0, 20)}…`);
  fingerprint.title = mesh.availability_identity.key_id;
  footer.append(operator, fingerprint);

  card.append(
    header,
    node("p", "mesh-description", mesh.description),
    registry,
    endpoint,
    operations,
    metrics,
    footer,
  );
  return card;
}

function renderEmpty(filtered) {
  const card = node("div", "empty-card");
  const copy = node("div");
  const title = filtered ? "No mesh matches those filters." : "The first public mesh starts here.";
  const detail = filtered
    ? "Try a broader region, operation, signal, or search term."
    : "The registry opens empty on purpose: simulated operators are never presented as independent public infrastructure. Run a public-only endpoint and submit its reviewed profile.";
  copy.append(node("h3", "", title), node("p", "", detail));
  if (!filtered) {
    const actions = node("div", "hero-actions");
    const register = node("a", "button primary", "Register a public mesh");
    register.href = "https://github.com/yassinbahri/OnceMesh/issues/new?template=public_mesh_registration.yml";
    const guide = node("a", "button secondary", "Read the operator guide");
    guide.href = "https://github.com/yassinbahri/OnceMesh/blob/main/docs/user-guide.md";
    actions.append(register, guide);
    copy.append(actions);
  }
  card.append(copy, node("div", "empty-glyph", "·—·"));
  elements.grid.append(card);
}

function render() {
  const meshes = state.directory.meshes;
  const query = elements.search.value.trim().toLocaleLowerCase();
  const region = elements.region.value;
  const operation = elements.operation.value;
  const signal = elements.signal.value;
  const filtered = meshes.filter((mesh) => {
    const searchable = `${mesh.peer_id} ${mesh.display_name} ${mesh.description} ${mesh.operator.name}`.toLocaleLowerCase();
    const regions = region === "" || mesh.regions.includes(region);
    const operations = operation === "" || mesh.operations.some((item) => `${item.name}/${item.version}` === operation);
    const signals = signal === "" || observationFor(mesh).state === signal;
    return searchable.includes(query) && regions && operations && signals;
  });

  elements.grid.replaceChildren();
  elements.message.textContent = meshes.length === 0
    ? "No independently operated public mesh has registered yet."
    : `Showing ${filtered.length} of ${meshes.length} registered ${meshes.length === 1 ? "mesh" : "meshes"}.${state.stale ? " The monitoring snapshot is stale." : ""}`;
  if (filtered.length === 0) renderEmpty(meshes.length > 0);
  filtered.forEach((mesh) => elements.grid.append(createCard(mesh)));
}

function populateFilters(meshes) {
  const regions = [...new Set(meshes.flatMap((mesh) => mesh.regions))].sort();
  const operations = [...new Set(meshes.flatMap((mesh) => mesh.operations.map((item) => `${item.name}/${item.version}`)))].sort();
  regions.forEach((region) => appendOption(elements.region, region, region));
  operations.forEach((operation) => appendOption(elements.operation, operation, operation));
}

function summarize(meshes) {
  const observations = meshes.map(observationFor);
  const responseTimes = observations
    .map((item) => item.response_time_ms)
    .filter((value) => value !== null)
    .sort((a, b) => a - b);
  let median = null;
  if (responseTimes.length > 0) {
    const middle = Math.floor(responseTimes.length / 2);
    median = responseTimes.length % 2
      ? responseTimes[middle]
      : Math.round((responseTimes[middle - 1] + responseTimes[middle]) / 2);
  }
  elements.listed.textContent = String(meshes.filter((mesh) => ["listed", "observed"].includes(mesh.status)).length);
  elements.up.textContent = String(observations.filter((item) => item.state === "up").length);
  elements.latency.textContent = speedLabel(median);
  elements.checked.textContent = meshes.length === 0 ? "Awaiting first listing" : (state.stale ? "Snapshot stale" : formatAge(state.status.generated_at));
}

function showError() {
  elements.message.textContent = "The public registry could not be loaded.";
  elements.grid.replaceChildren();
  const card = node("div", "error-card");
  card.append(
    node("h3", "", "Directory unavailable"),
    node("p", "", "The static registry did not load. View the reviewed JSON on GitHub or try this page again later."),
  );
  elements.grid.append(card);
  [elements.listed, elements.up, elements.latency, elements.checked].forEach((item) => { item.textContent = "—"; });
}

async function start() {
  try {
    const [directoryResponse, statusResponse] = await Promise.all([
      fetch("data/public-meshes.json", { cache: "no-store" }),
      fetch("data/public-mesh-status.json", { cache: "no-store" }),
    ]);
    if (!directoryResponse.ok) throw new Error("registry request failed");
    state.directory = await directoryResponse.json();
    if (statusResponse.ok) {
      state.status = await statusResponse.json();
      state.observations = new Map(state.status.meshes.map((item) => [item.peer_id, item]));
      const maximumAge = (state.status.monitor.schedule_minutes * 2 + 10) * 60000;
      state.stale = Date.now() - new Date(state.status.generated_at).getTime() > maximumAge;
    } else {
      state.stale = true;
    }
    populateFilters(state.directory.meshes);
    summarize(state.directory.meshes);
    render();
    [elements.search, elements.region, elements.operation, elements.signal].forEach((control) => {
      control.addEventListener("input", render);
    });
  } catch (error) {
    showError();
  }
}

start();

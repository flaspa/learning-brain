function renderRichText(text) {
  let escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Markdown-style links: [label](url)
  escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');

  // Bold: **text**
  escaped = escaped.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // Bare URLs not already inside an <a> tag
  escaped = escaped.replace(/(?<!href=")(?<!>)(https?:\/\/[^\s<)]+)/g,
    '<a href="$1" target="_blank" rel="noopener">$1</a>');

  return escaped;
}

function escapeHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderPills(el, categories, tags) {
  let html = "";
  if (categories && categories.length) {
    html += '<div class="pill-row"><span class="pill-label">Categories:</span> ' +
      categories.map(c => `<span class="pill pill-category">${escapeHtml(c)}</span>`).join(" ") + "</div>";
  }
  if (tags && tags.length) {
    html += '<div class="pill-row"><span class="pill-label">Tags:</span> ' +
      tags.map(t => `<span class="pill pill-tag">${escapeHtml(t)}</span>`).join(" ") + "</div>";
  }
  el.innerHTML = html;
}

function askCardImage(card) {
  // Same rule as the dashboard rich cards: only a real preview_image is ever
  // shown, never a favicon; missing/broken image just omits the image area.
  if (!card.preview_image) return "";
  return `
    <a class="rich-card-image-link" href="${escapeHtml(card.url)}" target="_blank" rel="noopener">
      <img class="rich-card-image" src="${escapeHtml(card.preview_image)}" alt=""
           loading="lazy" onerror="this.closest('.rich-card-image-link').remove()">
    </a>`;
}

function renderUsedToAnswer(el, cards) {
  if (!cards || cards.length === 0) {
    el.innerHTML = "";
    return;
  }
  const items = cards.map(c => `
    <div class="rich-card rich-card-compact" data-url="${escapeHtml(c.url)}">
      ${askCardImage(c)}
      <div class="rich-card-body">
        <a class="topic-list-title" href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.preview_title || c.title)}</a>
        ${c.description ? `<div class="topic-list-summary">${escapeHtml(c.description)}</div>` : ""}
        <div class="rich-card-meta">${escapeHtml([c.author, c.domain].filter(Boolean).join(" · "))}</div>
      </div>
    </div>`).join("");
  el.innerHTML = `<span class="uta-label">Matching saved resources</span>${items}`;
}

const askBtn = document.getElementById("askBtn");
const questionEl = document.getElementById("question");
const answerEl = document.getElementById("answer");
const answerMetaEl = document.getElementById("answerMeta");
const usedToAnswerEl = document.getElementById("usedToAnswer");

const rememberBtn = document.getElementById("rememberBtn");
const urlEl = document.getElementById("url");
const rememberStatusEl = document.getElementById("rememberStatus");
const rememberMetaEl = document.getElementById("rememberMeta");
const rememberSummaryEl = document.getElementById("rememberSummary");

async function ask() {
  const question = questionEl.value.trim();
  if (!question) return;

  askBtn.disabled = true;
  answerEl.className = "answer spinner";
  answerEl.textContent = "Thinking...";
  answerMetaEl.innerHTML = "";
  usedToAnswerEl.innerHTML = "";

  try {
    const resp = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await resp.json();
    answerEl.className = "answer";
    answerEl.innerHTML = renderRichText(data.answer || "(no answer)");
    renderPills(answerMetaEl, data.categories, data.tags);
    renderUsedToAnswer(usedToAnswerEl, data.used_to_answer);
  } catch (err) {
    answerEl.className = "answer status error";
    answerEl.textContent = "Error: " + err;
  } finally {
    askBtn.disabled = false;
  }
}

async function remember() {
  const url = urlEl.value.trim();
  if (!url) return;

  rememberBtn.disabled = true;
  rememberStatusEl.className = "status spinner";
  rememberStatusEl.textContent = "Fetching and remembering...";
  rememberMetaEl.innerHTML = "";
  rememberSummaryEl.innerHTML = "";

  try {
    const resp = await fetch("/remember", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await resp.json();
    rememberStatusEl.className = "status " + (data.status === "success" ? "success" : "error");
    rememberStatusEl.innerHTML = renderRichText(data.message || "");
    renderPills(rememberMetaEl, data.categories, data.tags);
    if (data.summary || data.author) {
      const authorLine = data.author ? `<strong>${escapeHtml(data.author)}</strong> &middot; ` : "";
      rememberSummaryEl.innerHTML = authorLine + escapeHtml(data.summary || "");
    }
  } catch (err) {
    rememberStatusEl.className = "status error";
    rememberStatusEl.textContent = "Error: " + err;
  } finally {
    rememberBtn.disabled = false;
  }
}

askBtn.addEventListener("click", ask);
rememberBtn.addEventListener("click", remember);
questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask();
});

// ----- Dashboard (Topics / Sources / People) -----

let RESOURCES = [];

const PRIORITY_TOPICS = [
  "AI / Machine Learning", "LLMs / Foundation Models", "Agents", "Computer Vision",
  "RAG / Knowledge / Memory", "Robotics / Embodied AI", "Research / Papers", "Events / Hackathons",
];
const SOURCE_ORDER = ["LinkedIn", "arXiv", "GitHub", "Blogs / Articles", "YouTube", "Events", "Other"];

function sourceLabel(resource) {
  const domain = (resource.domain || "").toLowerCase();
  if (domain.includes("youtube.com") || domain.includes("youtu.be")) return "YouTube";
  switch (resource.source_type) {
    case "linkedin": return "LinkedIn";
    case "github": return "GitHub";
    case "paper": return "arXiv";
    case "article": return "Blogs / Articles";
    case "event": return "Events";
    default: return "Other";
  }
}

function groupByTopic(resources) {
  const groups = {};
  for (const r of resources) {
    for (const cat of (r.categories || [])) {
      (groups[cat] = groups[cat] || []).push(r);
    }
  }
  return groups;
}

function groupBySource(resources) {
  const groups = {};
  for (const r of resources) {
    const label = sourceLabel(r);
    (groups[label] = groups[label] || []).push(r);
  }
  return groups;
}

function groupByAuthor(resources) {
  const raw = {};
  for (const r of resources) {
    if (!r.author) continue;
    (raw[r.author] = raw[r.author] || []).push(r);
  }
  const meaningful = {};
  for (const [name, items] of Object.entries(raw)) {
    if (items.length >= 2) meaningful[name] = items;
  }
  return meaningful;
}

function sortTopicKeys(keys) {
  return keys.sort((a, b) => {
    const ai = PRIORITY_TOPICS.indexOf(a);
    const bi = PRIORITY_TOPICS.indexOf(b);
    if (ai !== -1 && bi !== -1) return ai - bi;
    if (ai !== -1) return -1;
    if (bi !== -1) return 1;
    return a.localeCompare(b);
  });
}

function authorSubLabel(items) {
  const cats = new Set();
  items.forEach(r => (r.categories || []).forEach(c => cats.add(c)));
  return Array.from(cats).slice(0, 3).map(escapeHtml).join(" &middot; ");
}

function renderCardGrid(el, groups, sortedKeys, subLabelFn, emptyMessage) {
  if (sortedKeys.length === 0) {
    el.innerHTML = `<div class="empty-note">${emptyMessage}</div>`;
    return;
  }
  el.innerHTML = sortedKeys.map(key => {
    const items = groups[key];
    const recent = items.slice(0, 5);
    const listItems = recent.map(r =>
      `<li data-url="${escapeHtml(r.url)}">${escapeHtml(r.title || r.url)}</li>`
    ).join("");
    const sub = subLabelFn ? subLabelFn(items) : "";
    return `
      <div class="dash-card">
        <h4>${escapeHtml(key)}</h4>
        <div class="dash-count">${items.length} saved</div>
        ${sub ? `<div class="dash-sub">${sub}</div>` : ""}
        <ul>${listItems}</ul>
      </div>`;
  }).join("");

  el.querySelectorAll("li[data-url]").forEach(li => {
    li.addEventListener("click", () => openDetail(li.getAttribute("data-url")));
  });
}

function topicSubtopics(items, topicName) {
  const freq = {};
  items.forEach(r => (r.tags || []).forEach(t => {
    const tag = (t || "").trim();
    if (!tag || tag.toLowerCase() === topicName.toLowerCase()) return;
    freq[tag] = (freq[tag] || 0) + 1;
  }));
  return Object.entries(freq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([tag]) => tag);
}

// ----- Topic sections: resources are browsable directly, no "View all" -----

function topicSlug(name) {
  return "topic-" + name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function savedDate(resource) {
  const ts = resource.timestamp || "";
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts.slice(0, 10);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function resourceCardHtml(r) {
  // Same preview rule as everywhere else: a real preview_image or nothing at
  // all -- a broken image removes itself, leaving a clean text-only card.
  const img = r.preview_image
    ? `<img class="res-card-image" src="${escapeHtml(r.preview_image)}" alt="" loading="lazy" onerror="this.remove()">`
    : "";
  const title = r.title || r.preview_title || r.url;
  const summary = r.short_summary || r.preview_description || "";
  const tags = (r.tags || []).slice(0, 3)
    .map(t => `<span class="pill pill-tag">${escapeHtml(t)}</span>`).join(" ");
  const metaParts = [];
  if (r.domain) metaParts.push(escapeHtml(r.domain));
  const date = savedDate(r);
  if (date) metaParts.push(escapeHtml(date));
  return `
    <article class="res-card" data-url="${escapeHtml(r.url)}">
      <button class="res-remove" type="button" title="Remove this resource"
              aria-label="Remove this resource">&times;</button>
      ${img}
      <div class="res-card-body">
        <div class="res-card-title">${escapeHtml(title)}</div>
        ${summary ? `<div class="res-card-summary">${escapeHtml(summary)}</div>` : ""}
        ${tags ? `<div class="pill-row">${tags}</div>` : ""}
        <div class="res-card-meta">
          ${metaParts.join(" &middot; ")}${metaParts.length ? " &middot; " : ""}<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Open&nbsp;&rarr;</a>
        </div>
      </div>
    </article>`;
}

function renderTopicSections(el, groups, sortedKeys, emptyMessage) {
  if (sortedKeys.length === 0) {
    el.innerHTML = `<div class="empty-note">${emptyMessage}</div>`;
    return;
  }
  el.innerHTML = sortedKeys.map(key => {
    const items = groups[key];
    const subtopics = topicSubtopics(items, key);
    return `
      <section class="topic-section" id="${topicSlug(key)}" data-topic="${escapeHtml(key)}">
        <div class="topic-section-head">
          <h3>${escapeHtml(key)}</h3>
          <span class="topic-section-count">${items.length} saved</span>
        </div>
        ${subtopics.length ? `<div class="topic-section-tags">${subtopics.map(escapeHtml).join(" &middot; ")}</div>` : ""}
        <div class="resource-grid">${items.map(resourceCardHtml).join("")}</div>
        <button class="show-more-btn" type="button" aria-expanded="false" hidden></button>
      </section>`;
  }).join("");

  el.querySelectorAll(".show-more-btn").forEach(btn => {
    btn.addEventListener("click", () => toggleTopic(btn));
  });
  bindResourceCards(el);
  clampAllTopicSections();
}

// How many cards actually fit on one row, read straight off the live grid so
// the clamp always agrees with whatever the responsive CSS is doing.
function columnsInGrid(grid) {
  const tpl = getComputedStyle(grid).gridTemplateColumns;
  if (!tpl || tpl === "none") return 1;
  const n = tpl.split(" ").filter(Boolean).length;
  return n > 0 ? n : 1;
}

// Collapsed topics show exactly one row; expanded topics show everything.
function clampTopicSection(section) {
  const grid = section.querySelector(".resource-grid");
  const btn = section.querySelector(".show-more-btn");
  if (!grid || !btn) return;
  const cards = Array.from(grid.children);
  const expanded = section.classList.contains("expanded");
  const perRow = Math.min(columnsInGrid(grid), cards.length);
  const hiddenCount = Math.max(cards.length - perRow, 0);

  cards.forEach((card, i) => card.classList.toggle("is-clamped", !expanded && i >= perRow));

  if (hiddenCount === 0) {
    btn.hidden = true;
    section.classList.remove("expanded");
    return;
  }
  btn.hidden = false;
  btn.textContent = expanded ? "Show less ↑" : `Show ${hiddenCount} more ↓`;
  btn.setAttribute("aria-expanded", expanded ? "true" : "false");
}

function clampAllTopicSections() {
  document.querySelectorAll(".topic-section").forEach(clampTopicSection);
}

// Expand/collapse happens in place -- no modal, no drawer, no navigation.
function toggleTopic(btn) {
  const section = btn.closest(".topic-section");
  if (!section) return;
  section.classList.toggle("expanded");
  clampTopicSection(section);
  // When collapsing a tall topic, keep its header on screen.
  if (!section.classList.contains("expanded") &&
      section.getBoundingClientRect().top < 0) {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// Column count changes with the viewport, so re-clamp after a resize.
let clampTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(clampTimer);
  clampTimer = setTimeout(clampAllTopicSections, 150);
}, { passive: true });

function bindResourceCards(root) {
  root.querySelectorAll(".res-card[data-url]").forEach(card => {
    card.addEventListener("click", () => openDetail(card.getAttribute("data-url")));
    const remove = card.querySelector(".res-remove");
    if (remove) {
      remove.addEventListener("click", (e) => {
        e.stopPropagation();
        removeResource(card.getAttribute("data-url"));
      });
    }
  });
}

// ----- Soft delete: hides a resource, never deletes the underlying data -----

async function postJson(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return resp.json();
}

function dropFromUi(url) {
  // Pull it out of the in-memory list and off any surface showing it right
  // now, so nothing needs a full page reload.
  RESOURCES = RESOURCES.filter(r => r.url !== url);
  document.querySelectorAll(`.rich-card[data-url="${CSS.escape(url)}"]`)
    .forEach(el => el.remove());
  const open = document.getElementById("detailOverlay");
  if (open && open.dataset.url === url) closeDetail();
}

function rerenderDashboard() {
  renderTopicsView();
  renderSourcesView();
  renderPeopleView();
}

async function removeResource(url) {
  const resource = RESOURCES.find(r => r.url === url);
  if (!resource) return;
  if (!window.confirm("Remove this saved resource from Learning Brain?")) return;

  const payload = { id: resource.id || null, url: resource.url,
                    resolved_url: resource.resolved_url || null };
  try {
    await postJson("/api/resources/delete", payload);
  } catch (err) {
    window.alert("Could not remove that resource: " + err);
    return;
  }
  dropFromUi(url);
  rerenderDashboard();
  showUndoToast(resource, payload);
}

let undoTimer = null;

function showUndoToast(resource, payload) {
  let toast = document.getElementById("undoToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "undoToast";
    toast.className = "undo-toast";
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span class="undo-text">Resource removed</span>
    <button type="button" class="undo-btn">Undo</button>`;
  toast.classList.add("is-visible");
  toast.querySelector(".undo-btn").addEventListener("click", async () => {
    try {
      await postJson("/api/resources/restore", payload);
    } catch (err) {
      return;
    }
    RESOURCES.push(resource);
    rerenderDashboard();
    toast.classList.remove("is-visible");
  });
  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => toast.classList.remove("is-visible"), 6000);
}

function renderTopicsView() {
  const groups = groupByTopic(RESOURCES);
  renderTopicSections(
    document.getElementById("topicsView"), groups, sortTopicKeys(Object.keys(groups)),
    "Nothing to show yet -- run the dashboard index builder to populate this view."
  );
  wireCategoryNav(groups);
}

// Category chips scroll to the matching topic section (no routing, no reload).
function wireCategoryNav(groups) {
  document.querySelectorAll(".cat-chip").forEach(chip => {
    const topic = chip.getAttribute("data-topic");
    const hasItems = (groups[topic] || []).length > 0;
    if (!hasItems) {
      chip.classList.add("is-empty");
      chip.title = "Nothing saved in this topic yet";
      chip.onclick = null;
      return;
    }
    chip.classList.remove("is-empty");
    chip.title = "";
    chip.onclick = () => {
      showView("topics");
      const section = document.getElementById(topicSlug(topic));
      if (!section) return;
      section.scrollIntoView({ behavior: "smooth", block: "start" });
      section.classList.add("highlight");
      setTimeout(() => section.classList.remove("highlight"), 1600);
    };
  });
}

function renderSourcesView() {
  const groups = groupBySource(RESOURCES);
  const keys = Object.keys(groups).sort((a, b) => SOURCE_ORDER.indexOf(a) - SOURCE_ORDER.indexOf(b));
  renderCardGrid(
    document.getElementById("sourcesView"), groups, keys, authorSubLabel,
    "Nothing to show yet -- run the dashboard index builder to populate this view."
  );
}

function renderPeopleView() {
  const groups = groupByAuthor(RESOURCES);
  const keys = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length);
  renderCardGrid(
    document.getElementById("peopleView"), groups, keys, authorSubLabel,
    "No recurring authors detected yet in the sampled resources."
  );
}

// ----- Large centered modal: single-resource deep view -----

function openDetail(url) {
  const resource = RESOURCES.find(r => r.url === url);
  if (!resource) return;
  const el = document.getElementById("drawerContent");
  const catPills = (resource.categories || []).map(c => `<span class="pill pill-category">${escapeHtml(c)}</span>`).join(" ");
  const tagPills = (resource.tags || []).map(t => `<span class="pill pill-tag">${escapeHtml(t)}</span>`).join(" ");
  const subParts = [];
  if (resource.author) subParts.push(escapeHtml(resource.author));
  if (resource.domain) subParts.push(escapeHtml(resource.domain));
  const date = savedDate(resource);
  if (date) subParts.push("Saved " + escapeHtml(date));

  const hero = resource.preview_image
    ? `<img class="modal-hero" src="${escapeHtml(resource.preview_image)}" alt="" onerror="this.remove()">`
    : "";
  const summary = resource.short_summary || resource.preview_description || "";

  el.innerHTML = `
    ${hero}
    <h3>${escapeHtml(resource.title || resource.preview_title || resource.url)}</h3>
    <div class="drawer-sub">${subParts.join(" &middot; ")}</div>
    <div class="drawer-summary">${escapeHtml(summary || "No summary available for this resource yet.")}</div>
    ${catPills ? `<div class="pill-row">${catPills}</div>` : ""}
    ${tagPills ? `<div class="pill-row">${tagPills}</div>` : ""}
    <div><a class="drawer-open" href="${escapeHtml(resource.url)}" target="_blank" rel="noopener">Open original &rarr;</a></div>
  `;
  const overlay = document.getElementById("detailOverlay");
  overlay.dataset.url = resource.url;
  overlay.style.display = "flex";
  el.scrollTop = 0;
}

function closeDetail() {
  document.getElementById("detailOverlay").style.display = "none";
}

document.getElementById("closeDrawer").addEventListener("click", closeDetail);
document.getElementById("detailOverlay").addEventListener("click", (e) => {
  if (e.target.id === "detailOverlay") closeDetail();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDetail();
});

function showView(name) {
  document.querySelectorAll(".view-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view-panel").forEach(p => p.style.display = "none");
  const panel = document.getElementById(name + "View");
  panel.style.display = (name === "topics") ? "flex" : "grid";
}

document.querySelectorAll(".view-btn").forEach(btn => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});

async function loadDashboard() {
  try {
    const resp = await fetch("/api/resources");
    RESOURCES = await resp.json();
  } catch (err) {
    RESOURCES = [];
  }
  renderTopicsView();
  renderSourcesView();
  renderPeopleView();
}

loadDashboard();

// ----- Floating back-to-top button -----

const BACK_TO_TOP_AFTER = 500;

function initBackToTop() {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "back-to-top";
  btn.id = "backToTop";
  btn.setAttribute("aria-label", "Back to top");
  btn.title = "Back to top";
  btn.innerHTML = "&uarr;";
  document.body.appendChild(btn);

  btn.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  let ticking = false;
  const sync = () => {
    ticking = false;
    const y = window.pageYOffset || document.documentElement.scrollTop || 0;
    btn.classList.toggle("is-visible", y > BACK_TO_TOP_AFTER);
  };
  window.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(sync);
  }, { passive: true });
  window.addEventListener("resize", sync, { passive: true });
  sync();
}

initBackToTop();

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
    <div class="rich-card rich-card-compact">
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

function renderTopicCards(el, groups, sortedKeys, emptyMessage) {
  if (sortedKeys.length === 0) {
    el.innerHTML = `<div class="empty-note">${emptyMessage}</div>`;
    return;
  }
  el.innerHTML = sortedKeys.map(key => {
    const items = groups[key];
    const subtopics = topicSubtopics(items, key);
    const subList = subtopics.length
      ? `<ul class="subtopic-list">${subtopics.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`
      : "";
    return `
      <div class="dash-card">
        <h4>${escapeHtml(key)}</h4>
        <div class="dash-count">${items.length} saved</div>
        ${subList}
        <button class="view-all-btn" data-topic="${escapeHtml(key)}">View all ${items.length} &rarr;</button>
      </div>`;
  }).join("");

  el.querySelectorAll(".view-all-btn").forEach(btn => {
    btn.addEventListener("click", () => openTopicList(btn.getAttribute("data-topic")));
  });
}

function richCardImage(resource) {
  // Only a real preview_image is ever shown as the article preview -- no
  // favicon, no logo box. If it's missing or fails to load, the image area
  // is simply omitted (this.closest(...).remove()), leaving a text-only card.
  if (!resource.preview_image) return "";
  return `
    <a class="rich-card-image-link" href="${escapeHtml(resource.url)}" target="_blank" rel="noopener">
      <img class="rich-card-image" src="${escapeHtml(resource.preview_image)}" alt=""
           loading="lazy" onerror="this.closest('.rich-card-image-link').remove()">
    </a>`;
}

function openTopicList(topicName) {
  const items = groupByTopic(RESOURCES)[topicName] || [];
  const el = document.getElementById("drawerContent");
  const rows = items.map(r => {
    const tagPills = (r.tags || []).map(t => `<span class="pill pill-tag">${escapeHtml(t)}</span>`).join(" ");
    const description = r.short_summary || r.preview_description || "";
    return `
      <div class="rich-card">
        ${richCardImage(r)}
        <div class="rich-card-body">
          <a class="topic-list-title" href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${escapeHtml(r.title || r.url)}</a>
          ${description ? `<div class="topic-list-summary">${escapeHtml(description)}</div>` : ""}
          <div class="drawer-sub">${escapeHtml(r.domain || "")}</div>
          <div class="pill-row">${tagPills}</div>
        </div>
      </div>`;
  }).join("");

  el.innerHTML = `
    <h3>${escapeHtml(topicName)}</h3>
    <div class="drawer-sub">${items.length} saved resource${items.length === 1 ? "" : "s"}</div>
    <div class="topic-list">${rows}</div>
  `;
  document.getElementById("detailOverlay").style.display = "flex";
}

function renderTopicsView() {
  const groups = groupByTopic(RESOURCES);
  renderTopicCards(
    document.getElementById("topicsView"), groups, sortTopicKeys(Object.keys(groups)),
    "Nothing to show yet -- run the dashboard index builder to populate this view."
  );
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

function openDetail(url) {
  const resource = RESOURCES.find(r => r.url === url);
  if (!resource) return;
  const el = document.getElementById("drawerContent");
  const catPills = (resource.categories || []).map(c => `<span class="pill pill-category">${escapeHtml(c)}</span>`).join(" ");
  const tagPills = (resource.tags || []).map(t => `<span class="pill pill-tag">${escapeHtml(t)}</span>`).join(" ");
  const subParts = [];
  if (resource.author) subParts.push(escapeHtml(resource.author));
  if (resource.domain) subParts.push(escapeHtml(resource.domain));
  if (resource.timestamp) subParts.push(escapeHtml(resource.timestamp));

  el.innerHTML = `
    <h3>${escapeHtml(resource.title || resource.url)}</h3>
    <div class="drawer-sub">${subParts.join(" &middot; ")}</div>
    <div class="drawer-summary">${escapeHtml(resource.short_summary || "No summary available for this resource yet.")}</div>
    <div class="pill-row">${catPills}</div>
    <div class="pill-row">${tagPills}</div>
    <a class="drawer-open" href="${escapeHtml(resource.url)}" target="_blank" rel="noopener">Open source</a>
  `;
  document.getElementById("detailOverlay").style.display = "flex";
}

document.getElementById("closeDrawer").addEventListener("click", () => {
  document.getElementById("detailOverlay").style.display = "none";
});
document.getElementById("detailOverlay").addEventListener("click", (e) => {
  if (e.target.id === "detailOverlay") e.target.style.display = "none";
});

document.querySelectorAll(".view-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".view-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view-panel").forEach(p => p.style.display = "none");
    document.getElementById(btn.dataset.view + "View").style.display = "grid";
  });
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

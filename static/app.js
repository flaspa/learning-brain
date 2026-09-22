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

const askBtn = document.getElementById("askBtn");
const questionEl = document.getElementById("question");
const answerEl = document.getElementById("answer");
const answerMetaEl = document.getElementById("answerMeta");

const rememberBtn = document.getElementById("rememberBtn");
const urlEl = document.getElementById("url");
const rememberStatusEl = document.getElementById("rememberStatus");
const rememberMetaEl = document.getElementById("rememberMeta");

async function ask() {
  const question = questionEl.value.trim();
  if (!question) return;

  askBtn.disabled = true;
  answerEl.className = "answer spinner";
  answerEl.textContent = "Thinking...";
  answerMetaEl.innerHTML = "";

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

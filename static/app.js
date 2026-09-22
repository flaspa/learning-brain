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

const askBtn = document.getElementById("askBtn");
const questionEl = document.getElementById("question");
const answerEl = document.getElementById("answer");

const rememberBtn = document.getElementById("rememberBtn");
const urlEl = document.getElementById("url");
const rememberStatusEl = document.getElementById("rememberStatus");

async function ask() {
  const question = questionEl.value.trim();
  if (!question) return;

  askBtn.disabled = true;
  answerEl.className = "answer spinner";
  answerEl.textContent = "Thinking...";

  try {
    const resp = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await resp.json();
    answerEl.className = "answer";
    answerEl.innerHTML = renderRichText(data.answer || "(no answer)");
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

  try {
    const resp = await fetch("/remember", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await resp.json();
    rememberStatusEl.className = "status " + (data.status === "success" ? "success" : "error");
    rememberStatusEl.innerHTML = renderRichText(data.message || "");
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

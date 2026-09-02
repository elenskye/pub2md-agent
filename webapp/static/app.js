/* pub2md UI — thin client over the JSON API. Session auth; every POST
 * echoes the csrftoken cookie in X-CSRFToken (planted by the index view). */

const $ = (id) => document.getElementById(id);

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? m[1] : "";
}

async function api(path, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.method === "POST") {
    opts.headers = { "X-CSRFToken": csrfToken(), ...(opts.headers || {}) };
  }
  return fetch(path, opts);
}

/* ---------- auth ---------- */

async function boot() {
  const resp = await api("/api/me");
  if (resp.ok) {
    const { username, auth } = await resp.json();
    // auth === false → PUB2MD_AUTH=off, a local single-user run: no login
    // panel, no account chip in the header.
    showApp(auth === false ? null : username);
  } else {
    $("login-panel").hidden = false;
  }
}

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-error").textContent = "";
  const body = new FormData(ev.target);
  const resp = await api("/api/login", { method: "POST", body });
  if (resp.ok) {
    const { username } = await resp.json();
    $("login-panel").hidden = true;
    ev.target.reset();
    showApp(username);
  } else {
    $("login-error").textContent = "⚠ Incorrect username or password";
  }
});

$("logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

/* Two-axis style model: base style (single) × glossary domains (multi).
 * The pill display order doubles as the glossary precedence order, so the
 * base style's usual domains are listed first. */

let styleMeta = { base_styles: [], domains: [], defaults: {} };
let currentBase = "economist";

function renderDomains() {
  const defaults = styleMeta.defaults[currentBase] || [];
  const ordered = [...defaults, ...styleMeta.domains.filter((d) => !defaults.includes(d))];
  $("domain-boxes").innerHTML = ordered
    .map(
      (d) => `<label class="pill">
        <input type="checkbox" name="domains" value="${d}" ${defaults.includes(d) ? "checked" : ""}>${d}
      </label>`
    )
    .join("");
}

/* Custom dropdown (native select popups can't match the paper-ink theme). */

function renderStyleOptions() {
  $("style-current").textContent = currentBase;
  $("style-panel").innerHTML = styleMeta.base_styles
    .map(
      (s) => `<div class="select-option" role="option" data-value="${s}"
        aria-selected="${s === currentBase}">${s}</div>`
    )
    .join("");
  $("style-panel").querySelectorAll(".select-option").forEach((opt) => {
    opt.onclick = () => {
      currentBase = opt.dataset.value;
      toggleStylePanel(false);
      renderStyleOptions();
      renderDomains();
    };
  });
}

function toggleStylePanel(open) {
  $("style-panel").hidden = !open;
  $("style-btn").setAttribute("aria-expanded", String(open));
}

$("style-btn").addEventListener("click", () =>
  toggleStylePanel($("style-panel").hidden)
);
document.addEventListener("click", (ev) => {
  if (!$("style-select-wrap").contains(ev.target)) toggleStylePanel(false);
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") toggleStylePanel(false);
});

/* Custom file picker. */

$("file-btn").addEventListener("click", () => $("pdf-input").click());
$("pdf-input").addEventListener("change", () => {
  const file = $("pdf-input").files[0];
  $("file-name").textContent = file ? file.name : "No file selected";
});

/* How-to dialog. */

$("howto-btn").addEventListener("click", () => $("howto-dialog").showModal());
$("howto-close").addEventListener("click", () => $("howto-dialog").close());

async function showApp(username) {
  if (username) {
    $("username").textContent = username;
    $("user-box").hidden = false;
  }
  $("login-panel").hidden = true;
  $("job-panel").hidden = false;
  styleMeta = await (await api("/api/styles")).json();
  if (!styleMeta.base_styles.includes(currentBase)) currentBase = styleMeta.base_styles[0];
  renderStyleOptions();
  renderDomains();
  refreshHistory();
}

/* ---------- job flow ---------- */

let currentJob = null;
let pollTimer = null;

/* Two submit buttons, one form: the button that was pressed decides whether
 * the run gets the second review-and-rewrite pass. */
let refineRequested = false;
const submitButtons = () => [$("start-btn"), $("refine-btn")];
$("start-btn").addEventListener("click", () => { refineRequested = false; });
$("refine-btn").addEventListener("click", () => { refineRequested = true; });

$("job-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("job-error").textContent = "";
  const file = $("pdf-input").files[0];
  if (!file) return;
  // No domain selected is a valid choice: translate without a glossary.
  const checked = [...document.querySelectorAll("#domain-boxes input:checked")];
  const body = new FormData();
  body.append("pdf", file);
  body.append("base_style", currentBase);
  checked.forEach((box) => body.append("domains", box.value));
  if (refineRequested) body.append("refine", "true");

  submitButtons().forEach((b) => (b.disabled = true));
  $("result-box").hidden = true;
  const resp = await api("/api/jobs", { method: "POST", body });
  if (!resp.ok) {
    $("job-error").textContent = "⚠ " + ((await resp.json()).error || "Failed to create job");
    submitButtons().forEach((b) => (b.disabled = false));
    return;
  }
  const job = await resp.json();
  currentJob = job.id;
  $("progress-box").hidden = false;
  $("progress-text").textContent = "Queued…";
  $("progress-pct").textContent = "0%";
  $("progress-fill").style.width = "0%";
  pollTimer = setInterval(poll, 2000);
});

async function poll() {
  const resp = await api(`/api/jobs/${currentJob}`);
  if (!resp.ok) return;
  const job = await resp.json();
  $("progress-text").textContent = job.progress || job.status;
  $("progress-pct").textContent = `${job.percent || 0}%`;
  $("progress-fill").style.width = `${job.percent || 0}%`;
  if (job.status === "done" || job.status === "failed") {
    clearInterval(pollTimer);
    $("progress-box").hidden = true;
    submitButtons().forEach((b) => (b.disabled = false));
    if (job.status === "failed") {
      $("job-error").textContent = `⚠ Job failed: ${job.error}`;
    } else {
      renderResult(job);
    }
    refreshHistory();
  }
}

function renderResult(job) {
  $("result-box").hidden = false;
  $("cost-note").textContent = `(${job.result.llm_calls} calls · ~$${job.cost_usd})`;
  $("article-list").innerHTML = job.result.articles
    .map(
      (a, i) => `<li>
        <span class="title">${a.title}</span>
        <span class="meta">${a.n_paragraphs} paragraphs${a.n_failed ? ` · ${a.n_failed} failed` : ""} · ${a.mode === "chinese_only" ? "Simplified" : "Bilingual"}</span>
        <button data-file="${a.filename}" data-title="${a.title}" class="preview-btn ghost">Preview</button>
      </li>`
    )
    .join("");
  $("download-btn").onclick = () => {
    location.href = `/api/jobs/${currentJob}/download`;
  };
  const terms = job.result.new_terms || [];
  $("new-terms-box").hidden = terms.length === 0;
  $("new-terms-list").innerHTML = terms
    .map((t) => `<li>${t.en} → ${t.zh} <small>[${t.domain || "?"} · ${t.source}]</small></li>`)
    .join("");
  const conflicts = job.result.glossary_conflicts || [];
  $("conflicts-box").hidden = conflicts.length === 0;
  $("conflicts-list").innerHTML = conflicts
    .map(
      (c) =>
        `<li>${c.en}: used <b>${c.chosen_domain}</b> “${c.chosen_zh}” over ` +
        c.shadowed.map((s) => `${s.domain} “${s.zh}”`).join(", ") +
        `</li>`
    )
    .join("");
  document.querySelectorAll(".preview-btn").forEach((btn) => {
    btn.onclick = () => preview(btn.dataset.file, btn.dataset.title);
  });
}

/* ---------- preview with KaTeX ---------- */

async function preview(filename, title) {
  const resp = await api(`/api/jobs/${currentJob}/files/${encodeURIComponent(filename)}`);
  if (!resp.ok) return;
  const md = await resp.text();
  $("preview-title").textContent = title;
  $("preview-body").innerHTML = marked.parse(md);
  renderMathInElement($("preview-body"), {
    delimiters: [
      { left: "$$", right: "$$", display: true },
      { left: "$", right: "$", display: false },
    ],
    throwOnError: false,
  });
  $("preview-dialog").showModal();
}

$("preview-close").addEventListener("click", () => $("preview-dialog").close());

/* ---------- history ---------- */

$("clear-history-btn").addEventListener("click", async () => {
  if (!confirm("Delete all finished jobs and their files? This cannot be undone.")) return;
  await api("/api/jobs/clear", { method: "POST" });
  refreshHistory();
});

async function refreshHistory() {
  const resp = await api("/api/jobs?limit=8");
  if (!resp.ok) return;
  const { jobs } = await resp.json();
  $("history-card").hidden = jobs.length === 0;
  $("history-list").innerHTML = jobs
    .map(
      (j) => `<li>
        <span class="title">${j.original_filename}</span>
        <span class="meta">${j.base_style} × ${(j.domains || []).join("+") || "no glossary"} · ${j.status} · ${new Date(j.created_at).toLocaleString()}</span>
        ${j.status === "done" ? `<a href="/api/jobs/${j.id}/download">Download</a>` : ""}
      </li>`
    )
    .join("");
}

boot();

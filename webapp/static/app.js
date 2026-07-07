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
    const { username } = await resp.json();
    showApp(username);
  } else {
    $("login-card").hidden = false;
  }
}

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("login-error").textContent = "";
  const body = new FormData(ev.target);
  const resp = await api("/api/login", { method: "POST", body });
  if (resp.ok) {
    const { username } = await resp.json();
    $("login-card").hidden = true;
    ev.target.reset();
    showApp(username);
  } else {
    $("login-error").textContent = "账户或密码错误";
  }
});

$("logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

async function showApp(username) {
  $("username").textContent = username;
  $("user-box").hidden = false;
  $("app-card").hidden = false;
  const styles = (await (await api("/api/styles")).json()).styles;
  $("style-select").innerHTML = styles
    .map((s) => `<option value="${s}">${s}</option>`)
    .join("");
  if (styles.includes("economist")) $("style-select").value = "economist";
  refreshHistory();
}

/* ---------- job flow ---------- */

let currentJob = null;
let pollTimer = null;

$("job-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("job-error").textContent = "";
  const file = $("pdf-input").files[0];
  if (!file) return;
  const body = new FormData();
  body.append("pdf", file);
  body.append("style", $("style-select").value);

  $("start-btn").disabled = true;
  $("result-box").hidden = true;
  const resp = await api("/api/jobs", { method: "POST", body });
  if (!resp.ok) {
    $("job-error").textContent = (await resp.json()).error || "创建任务失败";
    $("start-btn").disabled = false;
    return;
  }
  const job = await resp.json();
  currentJob = job.id;
  $("progress-box").hidden = false;
  $("progress-text").textContent = "排队中…";
  pollTimer = setInterval(poll, 2000);
});

async function poll() {
  const resp = await api(`/api/jobs/${currentJob}`);
  if (!resp.ok) return;
  const job = await resp.json();
  $("progress-text").textContent = job.progress || job.status;
  if (job.status === "done" || job.status === "failed") {
    clearInterval(pollTimer);
    $("progress-box").hidden = true;
    $("start-btn").disabled = false;
    if (job.status === "failed") {
      $("job-error").textContent = `任务失败：${job.error}`;
    } else {
      renderResult(job);
    }
    refreshHistory();
  }
}

function renderResult(job) {
  $("result-box").hidden = false;
  $("cost-note").textContent = `（${job.result.llm_calls} 次调用 · 约 $${job.cost_usd}）`;
  $("article-list").innerHTML = job.result.articles
    .map(
      (a, i) => `<li>
        <span class="title">${a.title}</span>
        <span class="meta">${a.n_paragraphs} 段${a.n_failed ? ` · ${a.n_failed} 段失败` : ""} · ${a.mode === "chinese_only" ? "简体输出" : "双语"}</span>
        <button data-file="${a.filename}" data-title="${a.title}" class="preview-btn ghost">预览</button>
      </li>`
    )
    .join("");
  $("download-btn").onclick = () => {
    location.href = `/api/jobs/${currentJob}/download`;
  };
  const terms = job.result.new_terms || [];
  $("new-terms-box").hidden = terms.length === 0;
  $("new-terms-list").innerHTML = terms
    .map((t) => `<li>${t.en} → ${t.zh} <small>[${t.source}]</small></li>`)
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

async function refreshHistory() {
  const resp = await api("/api/jobs?limit=8");
  if (!resp.ok) return;
  const { jobs } = await resp.json();
  $("history-card").hidden = jobs.length === 0;
  $("history-list").innerHTML = jobs
    .map(
      (j) => `<li>
        <span class="title">${j.original_filename}</span>
        <span class="meta">${j.style} · ${j.status} · ${new Date(j.created_at).toLocaleString()}</span>
        ${j.status === "done" ? `<a href="/api/jobs/${j.id}/download">下载</a>` : ""}
      </li>`
    )
    .join("");
}

boot();

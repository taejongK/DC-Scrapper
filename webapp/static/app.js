"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const api = async (path) => (await fetch(path)).json();

// Shared filter state
const filt = () => {
  const p = new URLSearchParams();
  if ($("#f-gallery").value) p.set("gallery_id", $("#f-gallery").value);
  if ($("#f-from").value) p.set("date_from", $("#f-from").value);
  if ($("#f-to").value) p.set("date_to", $("#f-to").value);
  if ($("#f-q") && $("#f-q").value.trim()) p.set("q", $("#f-q").value.trim());
  return p;
};
const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString());

// ---------- Tabs ----------
// The top filter bar only scopes 글목록/분석, so it's shown only on those tabs.
function syncFilterBar(tab) {
  $("#filter-bar").hidden = (tab !== "posts" && tab !== "analysis" && tab !== "chat");
}
$$(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.remove("active"));
    $$(".panel").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#tab-" + t.dataset.tab).classList.add("active");
    syncFilterBar(t.dataset.tab);
    if (t.dataset.tab === "analysis") loadAnalysis();
    if (t.dataset.tab === "posts") loadPosts();
    if (t.dataset.tab === "collect") loadRuns();
    if (t.dataset.tab === "chat") loadChat();
  })
);

// ---------- Filters init ----------
async function initFilters() {
  const gals = await api("/api/meta/galleries");
  const sel = $("#f-gallery");
  gals.forEach((g) => {
    const o = document.createElement("option");
    o.value = g.gallery_id;
    o.textContent = `${g.gallery_id} (${g.n})`;
    sel.appendChild(o);
  });
  if (gals[0]) { $("#f-from").value = gals[0].mn; $("#f-to").value = gals[0].mx; }
  const cats = await api("/api/stats/categories");
  cats.forEach((c) => {
    const o = document.createElement("option");
    o.value = c.category; o.textContent = `${c.category} (${c.count})`;
    $("#p-category").appendChild(o);
  });
}
$("#apply-filters").addEventListener("click", () => {
  if ($("#tab-analysis").classList.contains("active")) loadAnalysis();
  else if ($("#tab-posts").classList.contains("active")) loadPosts();
});

// ---------- Collect ----------
$("#c-mode").addEventListener("change", (e) => {
  const m = e.target.value;
  $("#c-date-wrap").style.display = m === "date" ? "flex" : "none";
  $("#c-from-wrap").style.display = m === "range" ? "flex" : "none";
  $("#c-to-wrap").style.display = m === "range" ? "flex" : "none";
});

let pollTimer = null;
$("#start-collect").addEventListener("click", async () => {
  const mode = $("#c-mode").value;
  const body = {
    gallery_id: $("#c-gallery").value,
    max_pages: +$("#c-maxpages").value,
    with_comments: $("#c-comments").checked,
    delay_min: +$("#c-dmin").value,
    delay_max: +$("#c-dmax").value,
  };
  if (mode === "date") body.target_date = $("#c-date").value;
  if (mode === "range") { body.date_from = $("#c-from").value; body.date_to = $("#c-to").value; }
  const live = $("#collect-live");
  live.className = "live run";
  live.textContent = "수집 시작 중…";
  const res = await fetch("/api/collect", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.json());
  if (res.detail) { live.className = "live err"; live.textContent = "오류: " + res.detail; return; }
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => pollStatus(res.job_id, live), 1500);
  pollStatus(res.job_id, live);
});

async function pollStatus(jobId, live) {
  const st = await api("/api/collect/status?job_id=" + jobId);
  renderRuns(st.runs);
  const j = st.job;
  if (!j) return;
  if (j.status === "running") {
    live.className = "live run";
    live.textContent = "⏳ 수집 진행 중… (백그라운드 실행, 완료까지 시간이 걸립니다)";
  } else {
    clearInterval(pollTimer);
    if (j.status === "failed") {
      live.className = "live err";
      live.textContent = "❌ 실패: " + (j.error || "");
    } else {
      const s = j.summary || {};
      live.className = "live ok";
      live.textContent = `✅ 완료 (${j.status}) — 대상 ${s.target_date}, 글 ${s.posts_saved}건, 댓글 ${s.comments_saved}건`;
      initFilters(); // refresh gallery/date bounds
    }
  }
}

async function loadRuns() {
  const st = await api("/api/collect/status");
  renderRuns(st.runs);
}
function renderRuns(runs) {
  const tb = $("#runs-table tbody");
  tb.innerHTML = "";
  (runs || []).forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.gallery_id}</td><td>${r.target_date}</td>
      <td>${(r.started_at||"").slice(5,16)}</td><td>${(r.finished_at||"").slice(5,16)}</td>
      <td class="num">${fmt(r.posts_found)}</td><td class="num">${fmt(r.posts_saved)}</td>
      <td class="num">${fmt(r.comments_saved)}</td>
      <td><span class="badge">${r.status}</span></td>`;
    tb.appendChild(tr);
  });
}

// ---------- Posts ----------
let pOffset = 0;
const P_LIMIT = 50;
function loadPosts() {
  pOffset = 0; fetchPosts();
}
$("#p-search-btn").addEventListener("click", () => { pOffset = 0; fetchPosts(); });
$("#p-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { pOffset = 0; fetchPosts(); } });
$("#p-prev").addEventListener("click", () => { if (pOffset >= P_LIMIT) { pOffset -= P_LIMIT; fetchPosts(); } });
$("#p-next").addEventListener("click", () => { pOffset += P_LIMIT; fetchPosts(); });

async function fetchPosts() {
  const p = filt();
  p.set("limit", P_LIMIT); p.set("offset", pOffset);
  p.set("sort", $("#p-sort").value);
  if ($("#p-search").value) p.set("q", $("#p-search").value);
  if ($("#p-category").value) p.set("category", $("#p-category").value);
  const data = await api("/api/posts?" + p);
  const tb = $("#posts-table tbody"); tb.innerHTML = "";
  data.items.forEach((r) => {
    const tr = document.createElement("tr");
    const adult = r.is_adult ? ' <span class="badge">🔞</span>' : "";
    tr.innerHTML = `<td>${r.post_no}</td><td>${r.category||""}</td>
      <td class="clickable">${escapeHtml(r.title)}${adult}</td>
      <td>${escapeHtml(r.writer||"")}</td><td>${(r.posted_at||"").slice(5,16)}</td>
      <td class="num">${fmt(r.view_count)}</td><td class="num">${fmt(r.recommend)}</td>
      <td class="num">${fmt(r.comment_cnt)}</td>`;
    tr.querySelector(".clickable").addEventListener("click", () => openPost(r.post_no));
    tb.appendChild(tr);
  });
  const page = Math.floor(pOffset / P_LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(data.total / P_LIMIT));
  $("#p-pageinfo").textContent = `${page} / ${pages} 페이지 · 총 ${fmt(data.total)}건`;
}

async function openPost(no) {
  const d = await api("/api/posts/" + no);
  const p = d.post;
  let html = `<h2>${escapeHtml(p.title)}</h2>
    <p class="meta">${escapeHtml(p.writer||"")} · ${p.posted_at} · 조회 ${fmt(p.view_count)} · 추천 ${fmt(p.recommend)} · 댓글 ${fmt(p.comment_cnt)}</p>
    <div class="post-body">${p.is_adult ? "🔞 성인인증 필요 — 본문 미수집" : escapeHtml(p.body_text||"(본문 없음)")}</div>
    <a href="${p.url}" target="_blank">원문 보기 ↗</a><h3>댓글 ${d.comments.length}</h3>`;
  d.comments.forEach((c) => {
    html += `<div class="cmt ${c.is_reply ? "reply" : ""}">
      <div class="meta">${escapeHtml(c.writer||"")} ${c.writer_ip?("("+c.writer_ip+")"):""} · ${c.posted_at||""}</div>
      <div>${escapeHtml(c.content||"")}</div></div>`;
  });
  $("#modal-body").innerHTML = html;
  $("#modal").style.display = "flex";
}
$("#modal-close").addEventListener("click", () => ($("#modal").style.display = "none"));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").style.display = "none"; });

// ---------- Analysis ----------
const PALETTE = ["#4c8dff","#34d399","#fbbf24","#f87171","#a78bfa","#22d3ee","#fb923c","#4ade80","#e879f9","#60a5fa"];

async function loadAnalysis() {
  const q = filt().toString();
  // overview cards
  const ov = await api("/api/stats/overview?" + q);
  $("#overview-cards").innerHTML = [
    ["글", ov.posts], ["댓글", ov.comments], ["작성자", ov.unique_writers],
    ["평균 댓글", ov.avg_comments], ["평균 조회", ov.avg_views], ["성인글", ov.adult_posts],
  ].map(([l, v]) => `<div class="stat"><div class="val">${fmt(v)}</div><div class="lbl">${l}</div></div>`).join("");

  loadTop(); loadWordCloud(); loadBursts(); loadHeatmap();
  // prefill the LLM keyword box from the filter's keyword, if any
  const fq = filt().get("q");
  if (fq && !$("#llm-word").value) $("#llm-word").value = fq;
}

async function loadWordCloud() {
  const q = filt(); q.set("source", $("#wc-source").value); q.set("top_n", 120);
  const kw = await api("/api/analysis/keywords?" + q);
  const canvas = $("#wordcloud");
  if (!kw.length || typeof WordCloud === "undefined") {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const max = kw[0].count;
  WordCloud(canvas, {
    list: kw.map((d) => [d.word, d.count]),
    gridSize: 6,
    weightFactor: (n) => Math.max(12, (n / max) * 60 + 10),
    fontFamily: '"Apple SD Gothic Neo", "Malgun Gothic", sans-serif',
    color: (word, weight) => PALETTE[Math.floor((weight / (max + 1)) * PALETTE.length) % PALETTE.length],
    backgroundColor: "transparent",
    rotateRatio: 0.4,
    shrinkToFit: true,
    // click a word -> prefill it into the LLM deep-analysis box
    click: (item) => { $("#llm-word").value = item[0]; },
  });
}
$("#wc-source").addEventListener("change", loadWordCloud);

// ---------- LLM deep analysis ----------
let llmReady = false;
async function initLLM() {
  const st = await api("/api/analysis/llm_status");
  llmReady = st.available;
  $("#llm-model").textContent = st.available ? `(${st.model})` : "";
  $("#llm-status").innerHTML = st.available ? "" :
    `⚠️ LLM 미설정 — ${escapeHtml(st.reason || "")}. ` +
    `<code>ANTHROPIC_API_KEY</code> 설정 후 서버를 재시작하세요.`;
  $("#llm-btn").disabled = !st.available;
  $("#chat-model").textContent = st.available ? `(${st.model})` : "";
  $("#chat-btn").disabled = !st.available;
  if (!st.available) {
    $("#chat-status").innerHTML =
      `⚠️ LLM 미설정 — ${escapeHtml(st.reason || "")}. 대화 기능을 쓰려면 API 키가 필요합니다.`;
  }
}
async function runLLM() {
  const word = $("#llm-word").value.trim();
  const status = $("#llm-status");
  const box = $("#llm-report");
  if (!word) { status.textContent = "키워드를 입력하세요."; return; }
  if (!llmReady) { return; }
  status.innerHTML = `⏳ "<b>${escapeHtml(word)}</b>" 관련 글·댓글을 LLM으로 분석 중… (수십 초 걸릴 수 있음)`;
  box.innerHTML = "";
  const f = filt();
  const body = {
    q: word, source: $("#llm-source").value, refresh: $("#llm-refresh").checked,
    gallery_id: f.get("gallery_id") || null,
    date_from: f.get("date_from") || null, date_to: f.get("date_to") || null,
  };
  let r;
  try {
    r = await fetch("/api/analysis/llm_report", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((x) => x.json());
  } catch (e) { status.innerHTML = "❌ 요청 실패: " + escapeHtml(String(e)); return; }
  if (r.detail) { status.innerHTML = "❌ " + escapeHtml(r.detail); return; }
  if (r.error) { status.innerHTML = "⚠️ " + escapeHtml(r.error); return; }
  renderLLM(r);
}
function renderLLM(r) {
  const tag = r.cached ? '<span class="badge">캐시</span>' :
    (r.truncated ? `<span class="badge">상위 ${r.analyzed_posts}/${r.post_count}글 분석</span>` :
      `<span class="badge">${r.analyzed_posts}글 분석</span>`);
  $("#llm-status").innerHTML =
    `✅ "<b>${escapeHtml(r.keyword)}</b>" 분석 완료 · 매칭 ${fmt(r.post_count)}글 ${tag}`;
  if (r.empty) { $("#llm-report").innerHTML = `<p class="note">${escapeHtml(r.overview||"")}</p>`; return; }
  // evidence links: [#123] chips linking back to the source post
  const src = (sources) => (sources && sources.length)
    ? ' <span class="src">' + sources.map((s) => s.url
        ? `<a href="${s.url}" target="_blank" title="${escapeHtml(s.title||"")}">#${s.post_no}</a>`
        : `<span>#${s.post_no}</span>`).join("") + "</span>"
    : "";
  const list = (arr) => (arr && arr.length)
    ? "<ul>" + arr.map((x) => `<li>${escapeHtml(x.text || "")}${src(x.sources)}</li>`).join("") + "</ul>"
    : '<p class="note">—</p>';
  const themes = (r.themes || []).map((t) =>
    `<div class="theme"><b>${escapeHtml(t.title || "")}</b>${src(t.sources)}` +
    `<div>${escapeHtml(t.detail || "")}</div></div>`).join("");
  const quotes = (r.quotes || []).map((q) => {
    const cite = q.url ? `<a href="${q.url}" target="_blank">#${q.post_no} ↗</a>` :
      (q.post_no != null ? `#${q.post_no}` : "");
    return `<div class="quote">“${escapeHtml(q.quote || "")}” <span class="qcite">${cite}</span></div>`;
  }).join("");
  $("#llm-report").innerHTML = `
    <div class="llm-overview">${escapeHtml(r.overview || "")}</div>
    ${r.mood ? `<p class="llm-mood">🌡️ ${escapeHtml(r.mood)}</p>` : ""}
    ${themes ? `<h3 class="sub">📌 주요 주제</h3>${themes}` : ""}
    <div class="grid-2">
      <div><h3 class="sub">👍 긍정 평가</h3>${list(r.positives)}</div>
      <div><h3 class="sub">👎 부정 평가</h3>${list(r.negatives)}</div>
    </div>
    ${(r.issues && r.issues.length) ? `<h3 class="sub">⚔️ 쟁점</h3>${list(r.issues)}` : ""}
    ${quotes ? `<h3 class="sub">💬 대표 반응</h3>${quotes}` : ""}`;
}
$("#llm-btn").addEventListener("click", runLLM);
$("#llm-word").addEventListener("keydown", (e) => { if (e.key === "Enter") runLLM(); });

// ---------- Conversational (agentic) analysis ----------
function loadChat() {
  if (llmReady && !$("#chat-status").textContent.startsWith("✅")) $("#chat-status").innerHTML = "";
  $("#chat-q").focus();
}
async function runAsk() {
  const q = $("#chat-q").value.trim();
  const status = $("#chat-status");
  const box = $("#chat-answer");
  if (!q) { status.textContent = "질문을 입력하세요."; return; }
  if (!llmReady) { return; }
  status.innerHTML = `⏳ "<b>${escapeHtml(q)}</b>" — AI가 관련 글을 검색하며 분석 중… (수십 초 걸릴 수 있음)`;
  box.innerHTML = "";
  const f = filt();
  const body = {
    question: q,
    gallery_id: f.get("gallery_id") || null,
    date_from: f.get("date_from") || null,
    date_to: f.get("date_to") || null,
  };
  let r;
  try {
    r = await fetch("/api/analysis/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((x) => x.json());
  } catch (e) { status.innerHTML = "❌ 요청 실패: " + escapeHtml(String(e)); return; }
  if (r.detail) { status.innerHTML = "❌ " + escapeHtml(r.detail); return; }
  if (r.error) { status.innerHTML = "⚠️ " + escapeHtml(r.error); return; }
  renderAsk(r);
}
function renderAsk(r) {
  $("#chat-status").innerHTML = `✅ 답변 완료 · 참고 글 ${fmt(r.used_posts)}개`;
  const cites = {};
  (r.citations || []).forEach((c) => { cites[c.post_no] = c; });
  // inline [#123] / #123 -> source links; then newlines -> <br>
  let html = escapeHtml(r.answer || "").replace(/\[?#(\d+)\]?/g, (m, no) => {
    const c = cites[no];
    return c && c.url
      ? `<a href="${c.url}" target="_blank" title="${escapeHtml(c.title || "")}">#${no}</a>` : m;
  }).replace(/\n/g, "<br>");
  let src = "";
  if ((r.citations || []).length) {
    src = `<div class="chat-cites"><h3 class="sub">🔗 근거 글</h3>` +
      r.citations.map((c) =>
        `<a href="${c.url}" target="_blank">#${c.post_no} ${escapeHtml(c.title || "")}</a>`).join("") +
      `</div>`;
  }
  $("#chat-answer").innerHTML = `<div class="chat-bubble">${html}</div>${src}`;
}
$("#chat-btn").addEventListener("click", runAsk);
$("#chat-q").addEventListener("keydown", (e) => { if (e.key === "Enter") runAsk(); });

// ---------- Issue bursts ----------
async function loadBursts() {
  const q = filt(); q.set("top_n", 12); q.set("min_count", 2);
  if ($("#burst-date").value) q.set("date", $("#burst-date").value);
  const b = await api("/api/analysis/bursts?" + q);
  const info = $("#burst-info");
  if (!b || !b.date) { info.textContent = "데이터가 없습니다."; $("#burst-up").innerHTML = ""; $("#burst-new").innerHTML = ""; return; }
  const base = b.baseline_days ? `기준: ${b.baseline_from}~${b.baseline_to} (${b.baseline_days}일)` : "기준일 없음(첫날)";
  info.textContent = `${b.date} · ${base}`;
  const rowsUp = (b.bursts || []).map((x) =>
    `<div class="brow"><span class="bw clickable">${escapeHtml(x.word)}</span>
       <span class="bmeta">×${x.count} · ${x.burst}배${x.is_new ? " 🆕" : ""}</span></div>`).join("");
  const rowsNew = (b.new_keywords || []).map((x) =>
    `<div class="brow"><span class="bw clickable">${escapeHtml(x.word)}</span>
       <span class="bmeta">×${x.count}</span></div>`).join("");
  $("#burst-up").innerHTML = rowsUp || '<p class="note">급상승 없음</p>';
  $("#burst-new").innerHTML = rowsNew || '<p class="note">신규 없음</p>';
  // click a word -> prefill it into the LLM deep-analysis box
  $$("#burst-up .bw, #burst-new .bw").forEach((el) =>
    el.addEventListener("click", () => { $("#llm-word").value = el.textContent; }));
}
$("#burst-date").addEventListener("change", loadBursts);

// ---------- Heatmap ----------
async function loadHeatmap() {
  const q = filt().toString();
  const hm = await api("/api/analysis/heatmap?" + q);
  const max = Math.max(1, ...hm.matrix.flat());
  let html = '<table class="hm"><thead><tr><th></th>' +
    Array.from({length:24}, (_,h) => `<th>${h}</th>`).join("") + "</tr></thead><tbody>";
  hm.weekdays.forEach((wd, w) => {
    html += `<tr><th>${wd}</th>` + hm.matrix[w].map((v) => {
      const a = v === 0 ? 0 : 0.15 + 0.85 * (v / max);
      return `<td title="${wd} ${v}건" style="background:rgba(76,141,255,${a.toFixed(3)})">${v || ""}</td>`;
    }).join("") + "</tr>";
  });
  $("#heatmap-wrap").innerHTML = html + "</tbody></table>";
}
async function loadTop() {
  const q = filt(); q.set("by", $("#top-by").value); q.set("limit", 15);
  const rows = await api("/api/stats/top?" + q);
  const tb = $("#top-table tbody"); tb.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="clickable">${escapeHtml(r.title)}</td><td>${escapeHtml(r.writer||"")}</td>
      <td class="num">${fmt(r.view_count)}</td><td class="num">${fmt(r.recommend)}</td><td class="num">${fmt(r.comment_cnt)}</td>`;
    tr.querySelector(".clickable").addEventListener("click", () => openPost(r.post_no));
    tb.appendChild(tr);
  });
}
$("#top-by").addEventListener("change", loadTop);

function escapeHtml(s) { return (s||"").replace(/[&<>"']/g, (m) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[m])); }

// ---------- Boot ----------
initFilters().then(loadRuns);
initLLM();

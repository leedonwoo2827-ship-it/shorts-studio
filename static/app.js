// 쇼츠공방 — 세로 쇼츠 메이커 SPA
const $ = (id) => document.getElementById(id);
const STATE = { bundleDir: "", spec: { beats: [], audio: null, cta: "", title: "" }, allScenes: [], llmReady: false };
let renderTimer = null;
let ttsTimer = null;

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let d = null; try { d = await res.json(); } catch (e) {}
  if (!res.ok) throw new Error((d && d.detail) || `HTTP ${res.status}`);
  return d;
}
const img = (p) => `/api/image?path=${encodeURIComponent(p)}`;
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- init ----------
async function boot() {
  await llmRefresh();
  await refreshBundles();
  loadHooks();
}

// ---------- LLM 계정 ----------
function applyLlmStatus(s) {
  STATE.llmReady = !!(s && s.ready);
  const chip = $("llmChip");
  if (s && s.ready) {
    chip.textContent = `LLM: ${s.label || s.provider} ✓`; chip.className = "chip ok";
  } else {
    chip.textContent = "LLM 미로그인 (클릭)"; chip.className = "chip bad";
  }
  if (s && s.provider && $("llmProvider")) $("llmProvider").value = s.provider;
  if ($("llmInfo")) $("llmInfo").textContent = s && s.ready
    ? `✓ ${s.label || s.provider}${s.email ? " · " + s.email : ""}`
    : `미로그인${s && s.label ? " (" + s.label + ")" : ""}${s && s.error ? " — " + s.error : ""}`;
}
async function llmRefresh() {
  try { applyLlmStatus(await api("/api/llm/status")); await loadModels(); }
  catch (e) { $("llmChip").textContent = "서버 확인 실패"; }
}
async function loadModels() {
  const sel = $("llmModel"); if (!sel) return;
  try {
    const d = await api("/api/llm/models");
    const cur = d.current || "";
    sel.innerHTML = '<option value="">기본값 (자동 선택)</option>' +
      (d.models || []).map(m => `<option value="${m}"${m === cur ? " selected" : ""}>${m}</option>`).join("");
    if (cur && !(d.models || []).includes(cur)) sel.value = "";
    if ($("llmModelInfo")) $("llmModelInfo").textContent = "현재 적용: " + (cur || "기본 모델");
  } catch (e) { /* 모델 목록 미지원 공급자/오류는 무시 */ }
}
async function applyModel() {
  const sel = $("llmModel"); if (!sel) return;
  try {
    const r = await api("/api/llm/model", { method: "POST", body: JSON.stringify({ model: sel.value }) });
    if ($("llmModelInfo")) $("llmModelInfo").textContent = "현재 적용: " + ((r && r.model) || "기본 모델");
  } catch (e) { alert("모델 적용 실패: " + e.message); }
}
async function llmSetProvider(p) {
  try { const r = await api("/api/llm/provider", { method: "POST", body: JSON.stringify({ provider: p }) }); applyLlmStatus(r.status ? statusFrom(r.status) : null); await llmRefresh(); }
  catch (e) { alert("공급자 변경 실패: " + e.message); }
}
function statusFrom(sa) { const a = (sa && sa.active) || {}; return { ready: a.installed && a.authenticated, provider: sa.provider, label: a.label, email: a.email }; }
async function llmLogin() {
  try { await api("/api/llm/login", { method: "POST", body: JSON.stringify({ provider: $("llmProvider").value }) }); $("llmInfo").textContent = "터미널에서 로그인 진행 → 끝나면 ↻ 새로고침"; }
  catch (e) { alert("로그인 실행 실패: " + e.message); }
}
async function llmLogout() {
  if (!confirm("현재 공급자에서 로그아웃할까요? (다른 계정으로 전환하려면 로그아웃 후 로그인)")) return;
  try { await api("/api/llm/logout", { method: "POST", body: JSON.stringify({ provider: $("llmProvider").value }) }); await llmRefresh(); }
  catch (e) { alert("로그아웃 실패: " + e.message); }
}
async function refreshBundles() {
  try {
    const d = await api("/api/bundles");
    const sel = $("bundleSel");
    sel.innerHTML = "";
    (d.bundles || []).forEach(b => {
      const o = document.createElement("option");
      o.value = b.dir; o.textContent = `${b.name}${b.title ? " — " + b.title : ""}`;
      sel.appendChild(o);
    });
    $("bundleHint").textContent = `${(d.bundles || []).length}개 번들 발견`;
  } catch (e) { $("bundleHint").textContent = "번들 검색 실패: " + e.message; }
}

function currentBundleDir() {
  return $("bundlePath").value.trim() || $("bundleSel").value || "";
}

// ---------- compose ----------
async function compose() {
  const dir = currentBundleDir();
  if (!dir) { alert("번들을 선택하세요"); return; }
  STATE.bundleDir = dir;
  $("composeBtn").disabled = true;
  $("bundleHint").textContent = "씬 구성 중…";
  try {
    const spec = await api("/api/spec", { method: "POST", body: JSON.stringify({ bundle_dir: dir, duration: parseFloat($("duration").value), target_beats: parseInt($("targetBeats").value, 10) }) });
    STATE.spec = spec;
    if (spec.hashtags) $("hashtags").value = spec.hashtags;
    const sc = await api("/api/scenes", { method: "POST", body: JSON.stringify({ bundle_dir: dir }) });
    STATE.allScenes = sc.scenes || [];
    renderBeats();
    $("workspace").style.display = "flex";
    $("bundleHint").textContent = `자동 구성 완료 — 씬 ${spec.beats.length}개`;
    if (STATE.llmReady) {
      await aiFill({});        // AI로 후크·해시태그·자막 자동 채움
      await verifyContent();   // 이어서 자동 검토 → 각 자막 밑에 근거 표시
    } else {
      $("aiStatus").textContent = "LLM 미연결 — 문구는 직접 입력하세요 (렌더는 그대로 가능)";
    }
  } catch (e) { $("bundleHint").textContent = "실패: " + e.message; }
  finally { $("composeBtn").disabled = false; }
}

// AI 자동 채움. opts = {only:"hook"|"captions"|null, review:bool}
async function aiFill(opts = {}) {
  const only = opts.only || null, review = !!opts.review;
  if (!STATE.spec.beats.length) return;
  const scenes = STATE.spec.beats.map(b => {
    const s = STATE.allScenes.find(x => x.scene_index === b.scene_index) || {};
    return { scene_index: b.scene_index, narration: s.narration || b.caption || "", subtitle: s.subtitle || "" };
  });
  let review_of = null;
  if (review) {
    const caps = {}; STATE.spec.beats.forEach(b => { caps[b.scene_index] = b.caption; });
    const h = (STATE.spec.beats[0]?.hook || "").split(/[\r\n]+/);
    review_of = { hook1: h[0] || "", hook2: h[1] || "", hashtags: $("hashtags").value, captions: caps };
  }
  const btns = ["aiFillHookBtn", "aiFillCapBtn"];
  btns.forEach(id => { if ($(id)) $(id).disabled = true; });
  $("aiStatus").textContent = review ? "최종검토 중…" : (only === "hook" ? "AI 후크 생성 중…" : only === "captions" ? "AI 자막 생성 중…" : "AI 후크·자막 생성 중…");
  try {
    const d = await api("/api/ai-fill", { method: "POST", body: JSON.stringify({ title: STATE.spec.title, scenes, review_of, only }) });
    if (only !== "captions") {   // 후크 + 해시태그
      const hook = [d.hook1, d.hook2].filter(Boolean).join("\n");
      if (hook) STATE.spec.beats.forEach(b => { b.hook = hook; });   // 후크는 전 씬 공통
      if (d.hashtags) $("hashtags").value = d.hashtags;
    }
    if (only !== "hook" && d.captions) {   // 씬 자막
      STATE.spec.beats.forEach(b => { if (d.captions[b.scene_index]) b.caption = d.captions[b.scene_index]; });
    }
    renderBeats();
    loadHooks();
    $("aiStatus").textContent = "✓ AI 적용됨 — 자유롭게 수정하세요";
  } catch (e) { $("aiStatus").textContent = "AI 생략(" + e.message + ") — 수동 편집 가능"; }
  finally { btns.forEach(id => { if ($(id)) $(id).disabled = false; }); }
}

// ---------- AI 후크 보관함 ----------
async function loadHooks() {
  try {
    const d = await api("/api/hooks");
    const sel = $("hookStore");
    sel.innerHTML = '<option value="">— 후크 보관함 —</option>';
    (d.hooks || []).forEach(h => {
      const o = document.createElement("option");
      o.value = h; o.textContent = h.replace(/\n/g, " / ").slice(0, 40);
      sel.appendChild(o);
    });
  } catch (e) {}
}
function applyHookToAll(hook) {
  if (!hook || !STATE.spec.beats.length) return;
  STATE.spec.beats.forEach(b => { b.hook = hook; });
  renderBeats();
}
async function saveCurrentHook() {
  const hook = (STATE.spec.beats[0] && STATE.spec.beats[0].hook) || "";
  if (!hook.trim()) { alert("저장할 후크가 없습니다"); return; }
  try { await api("/api/hooks", { method: "POST", body: JSON.stringify({ hook }) }); await loadHooks(); $("aiStatus").textContent = "✓ 후크 보관함에 저장됨"; }
  catch (e) { alert("저장 실패: " + e.message); }
}

// ---------- beat cards ----------
function renderBeats() {
  const box = $("beats"); box.innerHTML = "";
  STATE.spec.beats.forEach((b, i) => {
    const el = document.createElement("div");
    el.className = "beat";
    el.innerHTML = `
      <img class="thumb" src="${img(b.image)}" alt="">
      <div class="fields">
        <div class="fieldrow">
          <div><label>상단 후크 <span class="hint">(1줄=검정 / Enter 후 2줄=주황)</span></label><textarea data-k="hook" rows="2">${esc(b.hook)}</textarea></div>
        </div>
        <div class="fieldrow">
          <div><label>음성 자막 <span class="hint">(중간 · 음성으로 읽힘)</span></label><textarea data-k="caption" rows="2">${esc(b.caption)}</textarea></div>
          <button class="ghost mini" data-a="verify" title="이 씬 자막을 원본과 대조해 사실 검토">🔎 검토</button>
        </div>
        ${b._verify ? `<div class="verify-result ${b._verify.ok ? "ok" : "ng"}">
          <div class="vr-head">${b._verify.ok ? "✓ 사실에 맞음" : "⚠ 어색"}${b._verify.reason ? ` · ${esc(b._verify.reason)}` : ""}</div>
          ${(b._verify.alts || []).map((a, ai) => `<button class="alt" data-a="alt" data-i="${ai}" title="클릭하면 이 문장으로 자막 교체">${esc(a)}</button>`).join("")}
        </div>` : ""}
        <div class="fieldrow">
          <div style="flex:0 0 120px"><label>길이(초)</label><input data-k="duration" type="number" step="0.1" value="${b.duration}"></div>
          <div style="font-weight:700;color:var(--fg);font-size:.95rem">씬 #${b.scene_index}</div>
        </div>
      </div>
      <div class="ctrls">
        <button class="ghost" data-a="up">↑</button>
        <button class="ghost" data-a="down">↓</button>
        <button class="ghost" data-a="del">✕</button>
      </div>`;
    el.querySelectorAll("[data-k]").forEach(inp => {
      inp.addEventListener("input", () => {
        const k = inp.dataset.k;
        STATE.spec.beats[i][k] = (k === "duration") ? parseFloat(inp.value) || 0 : inp.value;
        if (k === "caption") updateScriptView();
      });
    });
    el.querySelector('[data-a="del"]').onclick = () => { STATE.spec.beats.splice(i, 1); renderBeats(); };
    el.querySelector('[data-a="up"]').onclick = () => { if (i > 0) { const a = STATE.spec.beats; [a[i - 1], a[i]] = [a[i], a[i - 1]]; renderBeats(); } };
    el.querySelector('[data-a="down"]').onclick = () => { const a = STATE.spec.beats; if (i < a.length - 1) { [a[i + 1], a[i]] = [a[i], a[i + 1]]; renderBeats(); } };
    el.querySelector('[data-a="verify"]').onclick = (ev) => verifyOne(i, ev.target);
    el.querySelectorAll('[data-a="alt"]').forEach(btn => {
      btn.onclick = () => {
        const ai = +btn.dataset.i, v = STATE.spec.beats[i]._verify;
        if (v && v.alts && v.alts[ai] != null) { STATE.spec.beats[i].caption = v.alts[ai]; delete STATE.spec.beats[i]._verify; renderBeats(); }
      };
    });
    box.appendChild(el);
  });
  updateScriptView();
}

function updateScriptView() {
  const sv = $("scriptView");
  if (sv) sv.textContent = STATE.spec.beats.map((b, i) => `${i + 1}. ${(b.caption || "").replace(/\n/g, " ")}`).join("\n") || "(자막 없음)";
}

async function suggest(btn, i, kind) {
  const beat = STATE.spec.beats[i];
  const sceneInfo = STATE.allScenes.find(s => s.scene_index === beat.scene_index) || {};
  btn.disabled = true; const old = btn.textContent; btn.textContent = "…";
  try {
    const d = await api("/api/suggest", { method: "POST", body: JSON.stringify({ kind, narration: sceneInfo.narration || beat.caption || beat.hook, current: kind === "hook" ? beat.hook : beat.caption }) });
    if (kind === "hook") beat.hook = d.text; else beat.caption = d.text;
    renderBeats();
  } catch (e) { alert("AI 제안 실패: " + e.message); btn.textContent = old; btn.disabled = false; }
}

// 내용 검증 (원본 내레이션 대비 사실 점검·수정)
async function verifyOne(i, btn) {
  const b = STATE.spec.beats[i]; if (!b) return;
  const s = STATE.allScenes.find(x => x.scene_index === b.scene_index) || {};
  btn.disabled = true; btn.textContent = "검토…";
  try {
    const d = await api("/api/verify", { method: "POST", body: JSON.stringify({ scenes: [{ scene_index: b.scene_index, narration: s.narration || "", caption: b.caption }] }) });
    const v = d[b.scene_index];
    if (v) { b._verify = v; renderBeats(); }   // 결과를 자막 밑에 인라인 표시
    else { btn.disabled = false; btn.textContent = "🔎 검토"; }
  } catch (e) { $("aiStatus").textContent = "검토 실패: " + e.message; btn.disabled = false; btn.textContent = "🔎 검토"; }
}
async function verifyContent() {
  if (!STATE.spec.beats.length) return;
  const scenes = STATE.spec.beats.map(b => { const s = STATE.allScenes.find(x => x.scene_index === b.scene_index) || {}; return { scene_index: b.scene_index, narration: s.narration || "", caption: b.caption }; });
  $("verifyBtn").disabled = true; $("aiStatus").textContent = "전체 내용 검증 중…";
  try {
    const d = await api("/api/verify", { method: "POST", body: JSON.stringify({ scenes }) });
    let ng = 0;
    STATE.spec.beats.forEach(b => { const v = d[b.scene_index]; if (v) { b._verify = v; if (!v.ok) ng++; } });
    renderBeats();
    $("aiStatus").textContent = `🔎 검토 완료 — 각 자막 밑 근거 확인` + (ng ? ` (어색 ${ng}개, 대안 클릭=교체)` : " (모두 사실 OK)");
  } catch (e) { $("aiStatus").textContent = "검증 실패: " + e.message; }
  finally { $("verifyBtn").disabled = false; }
}

// ---------- add scene modal ----------
function openModal() {
  const list = $("sceneList"); list.innerHTML = "";
  STATE.allScenes.forEach(s => {
    const it = document.createElement("div");
    it.className = "scene-item";
    it.innerHTML = `<img src="${img(s.image)}"><div><div class="t">#${s.scene_index} ${esc(s.title)}</div><div class="n">${esc(s.narration)}</div></div>`;
    it.onclick = () => {
      STATE.spec.beats.push({ image: s.image, hook: s.subtitle || s.title, caption: (s.narration || "").split(/(?<=[.?!。！？])\s/)[0].slice(0, 34), duration: 4, image2: null, scene_index: s.scene_index, template: STATE.spec.beats.length % 4 });
      renderBeats(); closeModal();
    };
    list.appendChild(it);
  });
  $("modal").style.display = "flex";
}
function closeModal() { $("modal").style.display = "none"; }

// ---------- 음성 싱크 재생성 (F4·1.1) ----------
async function ttsSync() {
  if (!STATE.spec.beats.length) { alert("먼저 씬을 구성하세요"); return; }
  $("ttsBtn").disabled = true;
  $("ttsBar").style.display = "block"; $("ttsBarFill").style.width = "30%";
  $("ttsLogs").style.display = "block"; $("ttsLogs").textContent = "음성 생성 시작…";
  $("ttsStatus").textContent = "생성 중… (엔진 로드 + 줄당 ~2초)";
  try {
    const beats = STATE.spec.beats.map(b => ({ scene_index: b.scene_index, caption: b.caption, hook: b.hook }));
    const voice = $("voice") ? $("voice").value : "F4";
    const speed = parseFloat($("speed").value) || 1.1;
    const d = await api("/api/tts-sync", { method: "POST", body: JSON.stringify({ bundle_dir: STATE.bundleDir, beats, voice, speed }) });
    if (ttsTimer) clearInterval(ttsTimer);
    ttsTimer = setInterval(() => ttsPoll(d.job), 1500);
  } catch (e) { $("ttsStatus").textContent = "실패: " + e.message; $("ttsBtn").disabled = false; }
}
async function ttsPoll(job) {
  let d; try { d = await api(`/api/render/${job}`); } catch (e) { return; }
  $("ttsLogs").textContent = (d.logs || []).join("\n");
  $("ttsLogs").scrollTop = $("ttsLogs").scrollHeight;
  if (!d.running) {
    clearInterval(ttsTimer); ttsTimer = null; $("ttsBtn").disabled = false;
    if (d.data && d.data.audio) {
      const dt = d.data;
      STATE.spec.audio = dt.audio; STATE.spec.speed = 1.0;   // 이미 1.1배속 음성 → 추가 가속 금지
      (dt.beats || []).forEach((bo, i) => {
        const b = STATE.spec.beats[i]; if (!b) return;
        b.duration = bo.duration; b.video = bo.video; b.clip_start = bo.clip_start;
      });
      $("ttsBarFill").style.width = "100%";
      renderBeats();
      $("ttsStatus").textContent = dt.has_video
        ? "✓ 새 음성 + 롱폼 영상(음소거) 적용 — 이제 🎬 쇼츠 생성"
        : "✓ 새 음성 적용 (자막없는 클린 롱폼 없음 → 이미지로) — 🎬 쇼츠 생성";
    } else if (d.error) { $("ttsStatus").textContent = "실패: " + d.error; }
  }
}

// ---------- render ----------
async function doRender() {
  if (!STATE.spec.beats.length) { alert("씬이 없습니다"); return; }
  $("renderBtn").disabled = true;
  $("bar").style.display = "block"; $("barFill").style.width = "0%";
  $("renderLogs").style.display = "block"; $("renderLogs").textContent = "쇼츠 생성 시작…";
  $("previewWrap").style.display = "none";
  $("renderStatus").textContent = "생성 중…";
  try {
    const body = {
      bundle_dir: STATE.bundleDir,
      beats: STATE.spec.beats,
      audio: STATE.spec.audio,
      hashtags: $("hashtags").value.trim(),
      title: STATE.spec.title,
      speed: (STATE.spec.speed != null ? STATE.spec.speed : (parseFloat($("speed").value) || 1.0)),
      hook_scale1: parseFloat($("hookScale1").value) || 1.0,
      hook_scale2: parseFloat($("hookScale2").value) || 1.0,
      hook_color1: $("hookColor1").value || "#111111",
      hook_color2: $("hookColor2").value || "#F4511E",
    };
    const d = await api("/api/render", { method: "POST", body: JSON.stringify(body) });
    if (renderTimer) clearInterval(renderTimer);
    renderTimer = setInterval(() => poll(d.job), 1200);
  } catch (e) {
    $("renderStatus").textContent = "실패: " + e.message;
    $("renderBtn").disabled = false;
  }
}
async function poll(job) {
  let d; try { d = await api(`/api/render/${job}`); } catch (e) { return; }
  $("renderLogs").textContent = (d.logs || []).join("\n");
  $("renderLogs").scrollTop = $("renderLogs").scrollHeight;
  let pct = 0;
  for (let i = (d.logs || []).length - 1; i >= 0; i--) { const m = /progress=(\d+)\/(\d+)/.exec(d.logs[i]); if (m) { pct = Math.round((+m[1] / +m[2]) * 100); break; } }
  if (pct) $("barFill").style.width = pct + "%";
  if (!d.running) {
    clearInterval(renderTimer); renderTimer = null;
    $("renderBtn").disabled = false;
    if (d.done) {
      $("barFill").style.width = "100%";
      const url = `/api/video/${job}?t=${Date.now()}`;
      $("player").src = url; $("dl").href = url;
      $("previewWrap").style.display = "flex";
      $("renderStatus").textContent = "✓ 완성";
      if (CAMP.assign) {   // 캠페인에서 구성한 건이면 자동 '생산' 기록
        const a = CAMP.assign; CAMP.assign = null;
        api("/api/campaign/produced", { method: "POST", body: JSON.stringify({ chapter: a.chapter, mbti: a.mbti, video_path: d.path || "" }) }).catch(() => {});
        $("renderStatus").textContent = `✓ 완성 — ${a.chapter}장·${a.mbti} 생산 기록됨`;
      }
    } else if (d.error) { $("renderStatus").textContent = "실패"; }
  }
}

// ---------- meta ----------
function beatsAsText() {
  return STATE.spec.beats.map((b, i) => `${i + 1}. [${b.hook}] ${b.caption}`).join("\n");
}
async function genMeta() {
  $("metaBtn").disabled = true; $("metaStatus").textContent = "메타 생성 중…";
  try {
    const d = await api("/api/meta", { method: "POST", body: JSON.stringify({ text: beatsAsText(), original_url: $("originalUrl").value.trim(), title_hint: STATE.spec.title }) });
    $("metaOut").textContent = d.meta || ""; $("metaOut").style.display = "block";
    $("metaCopyBtn").style.display = ""; $("metaStatus").textContent = "✓ 완료";
  } catch (e) { $("metaStatus").textContent = "실패: " + e.message; }
  finally { $("metaBtn").disabled = false; }
}
async function copyMeta() {
  try { await navigator.clipboard.writeText($("metaOut").textContent); $("metaStatus").textContent = "✓ 복사됨"; }
  catch (e) { $("metaStatus").textContent = "복사 실패"; }
}

// ---------- 캠페인 (MBTI 후크 × 무중복 스케줄) ----------
let CAMP = { rows: [], assign: null };

function showTab(name) {
  const make = name === "make";
  $("tabMake").style.display = make ? "" : "none";
  $("tabCampaign").style.display = make ? "none" : "";
  $("tabBtnMake").classList.toggle("active", make);
  $("tabBtnCampaign").classList.toggle("active", !make);
  if (!make) loadCampaign();
}

async function loadSeries() {
  try {
    const d = await api("/api/series");
    $("campSeries").innerHTML = (d.series || []).map(s =>
      `<option value="${esc(s)}"${s === d.active ? " selected" : ""}>${esc(s)}</option>`).join("")
      || '<option value="">(시리즈 없음)</option>';
  } catch (e) {}
}
async function setActiveSeries(s) {
  try {
    await api("/api/series/active", { method: "POST", body: JSON.stringify({ series: s }) });
    await refreshBundles();
    await loadCampaign();
  } catch (e) { alert("시리즈 전환 실패: " + e.message); }
}
async function loadCampaign() {
  await loadSeries();
  try {
    const d = await api("/api/campaign/list");
    CAMP.rows = d.rows || [];
    const p = d.progress || {};
    $("campProgress").textContent = `${p.produced || 0} / ${p.total || 0} 생산 · 장 ${p.chapters || 0}개`;
    const chapters = [...new Set(CAMP.rows.map(r => r.chapter))];
    $("campChapter").innerHTML = chapters.map(c => `<option value="${c}">${c}장</option>`).join("");
    $("campFilterChapter").innerHTML = '<option value="">전체</option>' + chapters.map(c => `<option value="${c}">${c}장</option>`).join("");
    const mbtis = [...new Set(CAMP.rows.map(r => r.mbti))];
    $("campFilterMbti").innerHTML = '<option value="">전체</option>' + mbtis.map(m => `<option value="${m}">${m}</option>`).join("");
    renderCampList();
  } catch (e) { $("campProgress").textContent = "로드 실패: " + e.message; }
}
function nextUnproducedDay() {
  const r = CAMP.rows.find(x => x.status !== "produced");
  return r ? r.day : null;
}
function renderCampList() {
  const fs = $("campFilterStatus").value, fm = $("campFilterMbti").value, fc = $("campFilterChapter").value;
  const nd = nextUnproducedDay();
  const rows = CAMP.rows.filter(r =>
    (!fs || r.status === fs) && (!fm || r.mbti === fm) && (!fc || String(r.chapter) === fc));
  $("campList").innerHTML = rows.map(r => {
    const today = r.day === nd ? " today" : "";
    const prod = r.status === "produced";
    return `<div class="camp-row${today}${prod ? " done" : ""}" data-ch="${r.chapter}" data-mbti="${r.mbti}">
      <span class="c-day">${r.day}</span>
      <span class="c-ch">${r.chapter}장<small>${esc(r.title || "")}</small></span>
      <span class="c-mbti">${r.mbti}</span>
      <span class="c-hook">
        <input class="ch-l1" value="${esc(r.line1)}" placeholder="1줄(검정)">
        <input class="ch-l2" value="${esc(r.line2)}" placeholder="2줄(주황)"></span>
      <span class="c-st">${prod ? "✅ 생산" : (today ? "⭐ 오늘" : "예정")}</span>
      <span class="c-act"><button class="ghost mini ch-build">구성</button></span>
    </div>`;
  }).join("") || '<div class="hint" style="padding:1rem">표시할 행이 없습니다. 후크 생성 또는 필터를 확인하세요.</div>';
  $("campList").querySelectorAll(".camp-row").forEach(row => {
    const ch = +row.dataset.ch, mbti = row.dataset.mbti;
    const l1 = row.querySelector(".ch-l1"), l2 = row.querySelector(".ch-l2");
    const save = () => saveHook(ch, mbti, l1.value, l2.value);
    l1.onchange = save; l2.onchange = save;
    row.querySelector(".ch-build").onclick = () => applyAssignment(ch, mbti, l1.value, l2.value);
  });
}
async function saveHook(chapter, mbti, line1, line2) {
  try {
    await api("/api/campaign/hooks", { method: "POST", body: JSON.stringify({ chapter, mbti, line1, line2 }) });
    const r = CAMP.rows.find(x => x.chapter === chapter && x.mbti === mbti);
    if (r) { r.line1 = line1; r.line2 = line2; r.edited = 1; }
    $("campStatus").textContent = `✓ ${chapter}장 ${mbti} 저장됨`;
  } catch (e) { $("campStatus").textContent = "저장 실패: " + e.message; }
}
async function genChapterHooks() {
  const ch = +$("campChapter").value;
  if (!ch) return;
  $("campGenBtn").disabled = true; $("campStatus").textContent = `${ch}장 16유형 후크 생성 중…`;
  try {
    await api("/api/campaign/hooks/gen", { method: "POST", body: JSON.stringify({ chapter: ch }) });
    await loadCampaign();
    $("campStatus").textContent = `✓ ${ch}장 후크 생성됨`;
  } catch (e) { $("campStatus").textContent = "생성 실패: " + e.message; }
  finally { $("campGenBtn").disabled = false; }
}
async function applyAssignment(chapter, mbti, line1, line2) {
  const pad = String(chapter).padStart(2, "0");
  const sel = $("bundleSel");
  const opt = [...sel.options].find(o => o.value.replace(/\\/g, "/").toLowerCase().endsWith(`ch${pad}_bundle`));
  if (!opt) { alert(`ch${pad}_bundle 을 번들 목록에서 찾지 못했습니다 (제작 탭에서 직접 선택).`); return; }
  sel.value = opt.value; $("bundlePath").value = "";
  CAMP.assign = { chapter, mbti };
  showTab("make");
  await compose();                              // 씬 구성(+AI 자막)
  const hook = [line1, line2].filter(Boolean).join("\n");
  if (hook) applyHookToAll(hook);              // MBTI 후크로 덮어쓰기(aiFill 후크 대체)
  $("aiStatus").textContent = `🗓 ${chapter}장 · ${mbti} 구성됨 — 검토 후 렌더하면 자동 '생산' 기록`;
}

// ---------- wire ----------
$("tabBtnMake").onclick = () => showTab("make");
$("tabBtnCampaign").onclick = () => showTab("campaign");
$("campSeries").onchange = (e) => setActiveSeries(e.target.value);
$("campGenBtn").onclick = genChapterHooks;
$("campJumpBtn").onclick = () => { const nd = nextUnproducedDay(); if (nd) { ["campFilterStatus", "campFilterMbti", "campFilterChapter"].forEach(id => $(id).value = ""); renderCampList(); const el = $("campList").querySelector(".camp-row.today"); if (el) el.scrollIntoView({ block: "center" }); } };
["campFilterStatus", "campFilterMbti", "campFilterChapter"].forEach(id => { $(id).onchange = renderCampList; });
$("refreshBtn").onclick = refreshBundles;
$("composeBtn").onclick = compose;
$("aiFillHookBtn").onclick = () => aiFill({ only: "hook" });
$("aiFillCapBtn").onclick = () => aiFill({ only: "captions" });
$("verifyBtn").onclick = verifyContent;
$("hookStore").onchange = (e) => applyHookToAll(e.target.value);
$("hookSaveBtn").onclick = saveCurrentHook;
$("addSceneBtn").onclick = openModal;
$("modalClose").onclick = closeModal;
$("ttsBtn").onclick = ttsSync;
$("renderBtn").onclick = doRender;
$("metaBtn").onclick = genMeta;
$("metaCopyBtn").onclick = copyMeta;
$("llmChip").onclick = () => { const p = $("llmPanel"); p.style.display = p.style.display === "none" ? "" : "none"; if (p.style.display !== "none") llmRefresh(); };
$("llmProvider").onchange = (e) => llmSetProvider(e.target.value);
$("llmLoginBtn").onclick = llmLogin;
$("llmLogoutBtn").onclick = llmLogout;
$("llmRefreshBtn").onclick = llmRefresh;
$("llmModelApplyBtn").onclick = applyModel;
boot();

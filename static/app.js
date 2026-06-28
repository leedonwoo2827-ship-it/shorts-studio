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
  showTab("campaign");   // 시작 탭 = 캠페인(워크플로 시작점)
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
async function compose(keepCampaign = false) {
  if (!keepCampaign) clearBuildBanner();   // 수동 구성이면 캠페인 배너·할당 해제
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
    if (keepCampaign) {
      // 캠페인 구성: 후크·자막은 applyAssignment 가 MBTI 무드로 채움(여기선 일반 생성 건너뜀)
    } else if (STATE.llmReady) {
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
  const N = CAMP.rows.length ? Math.round(CAMP.rows.length / 16) : 17;   // 장 수(=리스트당 글 수)
  const rowHtml = (r) => {
    const today = r.day === nd ? " today" : "";
    const prod = r.status === "produced";
    const hasHook = !!(r.line1 && r.line1.trim());
    const state = prod ? "done" : (hasHook ? "ready" : "empty");   // 흰/노랑/네이비
    const views = (r.views != null) ? `<b class="yt-views">▶ ${r.views.toLocaleString()}</b>` : "";
    const dis = prod ? " disabled" : "";
    return `<div class="camp-row ${state}${today}" data-ch="${r.chapter}" data-mbti="${r.mbti}" data-mood="${esc(r.mood || "")}">
      <span class="c-day">${r.day}</span>
      <span class="c-ch">${r.chapter}장<small>${esc(r.title || "")}</small></span>
      <span class="c-mbti">${r.mbti}</span>
      <span class="c-hook">
        <input class="ch-l1" value="${esc(r.line1)}" placeholder="1줄(검정)"${dis}>
        <input class="ch-l2" value="${esc(r.line2)}" placeholder="2줄(주황)"${dis}></span>
      <span class="c-yt">
        <input class="ch-yt" value="${esc(r.video_id)}" placeholder="발행 후 URL/ID 붙여넣기">
        ${views}</span>
      <span class="c-st">${prod ? "✅ 생산" : (today ? "⭐ 오늘" : (hasHook ? "준비됨" : "후크 없음"))}</span>
      <span class="c-act"><button class="ghost mini ch-build"${(!hasHook || prod) ? " disabled" : ""}>구성</button></span>
    </div>`;
  };
  // 일자순 → 라운드(=한 MBTI로 17장)별로 자동 묶어 헤더 표시. 1리스트=1라운드=17개 글.
  let html = "", lastMbti = null;
  for (const r of rows) {
    if (r.mbti !== lastMbti) {
      lastMbti = r.mbti;
      const round = Math.floor((r.day - 1) / N) + 1;
      const grp = CAMP.rows.filter(x => x.mbti === r.mbti);
      const done = grp.filter(x => x.status === "produced").length;
      html += `<div class="camp-group"><b>${round}리스트</b> · <span class="cg-mbti">${r.mbti}</span>` +
        `<small>${esc(r.mood || "")}</small><span class="cg-prog">${done}/${grp.length} 생산</span></div>`;
    }
    html += rowHtml(r);
  }
  $("campList").innerHTML = html || '<div class="hint" style="padding:1rem">표시할 행이 없습니다. 후크 생성 또는 필터를 확인하세요.</div>';
  $("campList").querySelectorAll(".camp-row").forEach(row => {
    const ch = +row.dataset.ch, mbti = row.dataset.mbti, mood = row.dataset.mood;
    const l1 = row.querySelector(".ch-l1"), l2 = row.querySelector(".ch-l2"), yt = row.querySelector(".ch-yt");
    const build = row.querySelector(".ch-build");
    const prod = row.classList.contains("done");
    const save = () => {
      saveHook(ch, mbti, l1.value, l2.value);
      const has = !!l1.value.trim();
      build.disabled = prod || !has;                    // 후크 입력되면 구성 활성
      row.classList.toggle("ready", !prod && has);
      row.classList.toggle("empty", !prod && !has);
    };
    l1.onchange = save; l2.onchange = save;
    yt.onchange = () => saveVideo(ch, mbti, yt.value);
    build.onclick = () => applyAssignment(ch, mbti, l1.value, l2.value, mood);
  });
  // 첫 화면을 '다음 미생산' 위치로 자동 이동(예: 1~17 생산되면 18번이 맨 위). 클릭으로 찾을 필요 X.
  const t = $("campList").querySelector(".camp-row.today");
  if (t) {
    const grp = t.previousElementSibling;   // 그 줄의 라운드 헤더가 있으면 헤더부터 보이게
    $("campList").scrollTop = Math.max(0, (grp && grp.classList.contains("camp-group") ? grp : t).offsetTop - 6);
  }
}
async function saveVideo(chapter, mbti, video) {
  try {
    const d = await api("/api/campaign/video", { method: "POST", body: JSON.stringify({ chapter, mbti, video }) });
    const r = CAMP.rows.find(x => x.chapter === chapter && x.mbti === mbti);
    if (r) r.video_id = d.video_id || "";
    $("campStatus").textContent = `✓ ${chapter}장 ${mbti} 영상 연결 (${d.video_id || "—"})`;
  } catch (e) { $("campStatus").textContent = "영상 연결 실패: " + e.message; }
}
async function refreshViews() {
  $("campViewsBtn").disabled = true; $("campStatus").textContent = "조회수 가져오는 중…";
  try {
    const d = await api("/api/campaign/views/refresh", { method: "POST", body: "{}" });
    await loadCampaign();
    $("campStatus").textContent = `✓ 조회수 갱신: ${d.updated}개 영상 (연결 ${d.linked})`;
  } catch (e) { $("campStatus").textContent = "조회수 갱신 실패: " + e.message; }
  finally { $("campViewsBtn").disabled = false; }
}
async function loadInsights() {
  const box = $("campInsights");
  if (box.style.display !== "none") { box.style.display = "none"; return; }
  box.style.display = "";
  box.innerHTML = "집계 중…";
  try {
    const d = await api("/api/campaign/insights");
    if (!d.samples) { box.innerHTML = '<div class="hint">아직 조회수 데이터가 없습니다. YT칸에 URL을 넣고 [조회수 갱신]을 누르세요.</div>'; return; }
    const tbl = (title, arr, fmtKey) => `<div class="ins-col"><h4>${title}</h4>` +
      arr.map((x, i) => `<div class="ins-row"><span class="ins-rank">${i + 1}</span><span class="ins-key">${fmtKey(x.key)}</span><span class="ins-avg">평균 ${x.avg.toLocaleString()}</span><span class="ins-n">n=${x.n}·합 ${x.total.toLocaleString()}</span></div>`).join("") + "</div>";
    box.innerHTML = `<div class="ins-note">표본 ${d.samples}개의 '최신 조회수' 기준 평균. 어떤 유형/장이 잘 먹히는지.</div>
      <div class="ins-grid">${tbl("MBTI별 평균 조회수", d.by_mbti, k => k)}${tbl("장별 평균 조회수", d.by_chapter, k => k + "장")}</div>`;
  } catch (e) { box.innerHTML = "인사이트 실패: " + e.message; }
}
async function saveHook(chapter, mbti, line1, line2) {
  try {
    await api("/api/campaign/hooks", { method: "POST", body: JSON.stringify({ chapter, mbti, line1, line2 }) });
    const r = CAMP.rows.find(x => x.chapter === chapter && x.mbti === mbti);
    if (r) { r.line1 = line1; r.line2 = line2; r.edited = 1; }
    $("campStatus").textContent = `✓ ${chapter}장 ${mbti} 저장됨`;
  } catch (e) { $("campStatus").textContent = "저장 실패: " + e.message; }
}
async function loadMoods() {
  const box = $("campMoods");
  if (box.style.display !== "none") { box.style.display = "none"; return; }
  box.style.display = ""; box.innerHTML = "불러오는 중…";
  try {
    const d = await api("/api/campaign/moods");
    const moods = d.moods || {}, order = d.order || Object.keys(moods);
    box.innerHTML = `<div class="mood-note">🎭 MBTI 16유형 <b>무드</b>(지속 페르소나)를 미리 정의 — 후크 생성이 이 무드를 따릅니다. 순서 = 라운드 진행 순서.</div>
      <div class="mood-grid">` +
      order.map(m => `<div class="mood-row"><span class="mood-key">${m}</span><input class="mood-in" data-mbti="${m}" value="${esc(moods[m] || "")}"></div>`).join("") +
      `</div><div class="toolbar"><button id="moodSaveBtn" class="ghost">💾 무드 저장</button><span id="moodStatus" class="hint"></span></div>`;
    $("moodSaveBtn").onclick = saveMoods;
  } catch (e) { box.innerHTML = "무드 로드 실패: " + e.message; }
}
async function saveMoods() {
  const moods = {};
  $("campMoods").querySelectorAll(".mood-in").forEach(i => { moods[i.dataset.mbti] = i.value; });
  try {
    await api("/api/campaign/moods", { method: "POST", body: JSON.stringify({ moods }) });
    if ($("moodStatus")) $("moodStatus").textContent = "✓ 저장됨 — 다음 후크 생성부터 반영";
  } catch (e) { if ($("moodStatus")) $("moodStatus").textContent = "저장 실패: " + e.message; }
}
async function genAllChapterHooks() {
  const chapters = [...new Set(CAMP.rows.map(r => r.chapter))];
  const todo = chapters.filter(c => CAMP.rows.some(r => r.chapter === c && !(r.line1 && r.line1.trim())));
  if (!todo.length) { $("campStatus").textContent = "모든 장에 이미 후크가 있습니다"; return; }
  if (!confirm(`후크 없는 ${todo.length}개 장의 16유형 후크를 생성합니다(장당 ~30초). 진행할까요?`)) return;
  const a = $("campGenAllBtn"), g = $("campGenBtn");
  a.disabled = true; g.disabled = true;
  try {
    for (let i = 0; i < todo.length; i++) {
      $("campStatus").textContent = `후크 생성 중… (${i + 1}/${todo.length} · ${todo[i]}장)`;
      try { await api("/api/campaign/hooks/gen", { method: "POST", body: JSON.stringify({ chapter: todo[i] }) }); }
      catch (e) { /* 한 장 실패해도 계속 */ }
    }
    await loadCampaign();
    $("campStatus").textContent = `✓ ${todo.length}개 장 후크 생성 완료`;
  } finally { a.disabled = false; g.disabled = false; }
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
async function applyAssignment(chapter, mbti, line1, line2, mood) {
  const pad = String(chapter).padStart(2, "0");
  const sel = $("bundleSel");
  const opt = [...sel.options].find(o => o.value.replace(/\\/g, "/").toLowerCase().endsWith(`ch${pad}_bundle`));
  if (!opt) { alert(`ch${pad}_bundle 을 번들 목록에서 찾지 못했습니다 (제작 탭에서 직접 선택).`); return; }
  sel.value = opt.value; $("bundlePath").value = "";
  CAMP.assign = { chapter, mbti };
  showTab("make");
  setBuildBanner(chapter, mbti, mood);          // 제작 탭에 "N장·MBTI·무드" 표시
  await compose(true);                          // 씬 구성(일반 자동생성은 건너뜀)
  const hook = [line1, line2].filter(Boolean).join("\n");
  if (hook) applyHookToAll(hook);              // 뱅크의 MBTI 후크 주입
  if (STATE.llmReady) {
    await regenCaptions();                      // 자막도 MBTI 무드 톤으로 생성
    await genHashtags();                        // 해시태그 넉넉히 자동 생성
    await verifyContent();                      // 사실검증
  }
  $("aiStatus").textContent = `🗓 ${chapter}장 · ${mbti} 구성됨 — 무드 따라 톤·내용 다듬고 렌더하면 자동 '생산'`;
}
async function genHashtags() {
  if (!STATE.spec.beats.length) return;
  const scenes = STATE.spec.beats.map(b => {
    const s = STATE.allScenes.find(x => x.scene_index === b.scene_index) || {};
    return { scene_index: b.scene_index, narration: s.narration || b.caption || "" };
  });
  const btn = $("hashtagBtn"); if (btn) btn.disabled = true;
  try {
    const d = await api("/api/ai-hashtags", { method: "POST", body: JSON.stringify({ title: STATE.spec.title, scenes }) });
    if (d.hashtags) $("hashtags").value = d.hashtags;
  } catch (e) { /* 해시태그 생성 실패는 조용히 무시(직접 입력 가능) */ }
  finally { if (btn) btn.disabled = false; }
}
// 제작 탭 "AI 후크 다시": 캠페인 구성 중이면 그 MBTI 무드로 새 후크, 아니면 일반
async function regenHook() {
  if (!CAMP.assign) { aiFill({ only: "hook" }); return; }
  const { chapter, mbti } = CAMP.assign;
  const btn = $("aiFillHookBtn"); if (btn) btn.disabled = true;
  $("aiStatus").textContent = `${mbti} 후크 다시 생성 중…`;
  try {
    const d = await api("/api/campaign/hooks/regen-one", { method: "POST", body: JSON.stringify({ chapter, mbti }) });
    const hook = [d.line1, d.line2].filter(Boolean).join("\n");
    if (hook) applyHookToAll(hook);
    $("aiStatus").textContent = `✓ ${mbti} 후크 새 제안 — 다시 누르면 또 다른 안`;
  } catch (e) { $("aiStatus").textContent = "후크 생성 실패: " + e.message; }
  finally { if (btn) btn.disabled = false; }
}
// 제작 탭 "AI 자막 다시": 캠페인 구성 중이면 그 MBTI 무드 톤으로 자막, 아니면 일반
async function regenCaptions() {
  if (!STATE.spec.beats.length) return;
  if (!CAMP.assign) { return aiFill({ only: "captions" }); }
  const { chapter, mbti } = CAMP.assign;
  const scenes = STATE.spec.beats.map(b => {
    const s = STATE.allScenes.find(x => x.scene_index === b.scene_index) || {};
    return { scene_index: b.scene_index, narration: s.narration || b.caption || "" };
  });
  const btn = $("aiFillCapBtn"); if (btn) btn.disabled = true;
  $("aiStatus").textContent = `${mbti} 무드로 자막 생성 중…`;
  try {
    const d = await api("/api/campaign/captions", { method: "POST", body: JSON.stringify({ title: STATE.spec.title, scenes, mbti }) });
    const caps = d.captions || {};
    STATE.spec.beats.forEach(b => { if (caps[b.scene_index]) { b.caption = caps[b.scene_index]; delete b._verify; } });
    renderBeats();
    $("aiStatus").textContent = `✓ ${mbti} 무드 자막 적용 — 사실은 검토로 확인`;
  } catch (e) { $("aiStatus").textContent = "자막 생성 실패: " + e.message; }
  finally { if (btn) btn.disabled = false; }
}
function setBuildBanner(chapter, mbti, mood) {
  const b = $("buildBanner");
  if (!b) return;
  b.innerHTML = `🗓 <b>${chapter}장</b> · <b class="bb-mbti">${esc(mbti)}</b>${mood ? ` · 무드: ${esc(mood)}` : ""}`;
  b.style.display = "";
}
function clearBuildBanner() { const b = $("buildBanner"); if (b) b.style.display = "none"; CAMP.assign = null; }

// ---------- wire ----------
$("tabBtnMake").onclick = () => showTab("make");
$("tabBtnCampaign").onclick = () => showTab("campaign");
$("campSeries").onchange = (e) => setActiveSeries(e.target.value);
$("campGenBtn").onclick = genChapterHooks;
$("campGenAllBtn").onclick = genAllChapterHooks;
$("campMoodBtn").onclick = loadMoods;
$("campViewsBtn").onclick = refreshViews;
$("campInsightBtn").onclick = loadInsights;
$("campJumpBtn").onclick = () => { const nd = nextUnproducedDay(); if (nd) { ["campFilterStatus", "campFilterMbti", "campFilterChapter"].forEach(id => $(id).value = ""); renderCampList(); const el = $("campList").querySelector(".camp-row.today"); if (el) el.scrollIntoView({ block: "center" }); } };
["campFilterStatus", "campFilterMbti", "campFilterChapter"].forEach(id => { $(id).onchange = renderCampList; });
$("refreshBtn").onclick = refreshBundles;
$("composeBtn").onclick = () => compose();
$("aiFillHookBtn").onclick = regenHook;
$("aiFillCapBtn").onclick = regenCaptions;
$("verifyBtn").onclick = verifyContent;
$("hookStore").onchange = (e) => applyHookToAll(e.target.value);
$("hookSaveBtn").onclick = saveCurrentHook;
$("addSceneBtn").onclick = openModal;
$("modalClose").onclick = closeModal;
$("ttsBtn").onclick = ttsSync;
$("hashtagBtn").onclick = genHashtags;
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

"""MBTI 후크 캠페인 — SQLite 기반 후크 뱅크 + 무중복 일일 스케줄 (표준 라이브러리 + 내부 모듈만).

한 장(章) × MBTI 16유형 = 장수×16 셀. 하루 1개씩 장을 순환 발행하되 같은 (장,유형)은 한 번만.
무중복 스케줄 공식(N=장수, M=16):  Day d → 장=chapters[(d-1)%N], 유형=mbti[((d-1)//N + (d-1)%N) % M]
→ 같은 장이라도 라운드마다 다른 유형 → Day(N+1) 이 Day1 과 안 겹침. 진실원천은 slot UNIQUE 제약.

조회수/분석(Phase 3)은 view_stat 빈 테이블 + slot.youtube_video_id 로 자리만 마련.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import bundle as _bundle
from . import llm as _llm
from . import series as _series
from . import youtube as _youtube

MBTI16 = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
          "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ"]

# 라운드(=한 MBTI로 전체 장을 한 바퀴, 17일) 진행 순서의 기본값. (campaign.mbti_order 로 편집 가능)
# 근거: ① 인구 비율(잠재 도달; 감각형 73%, ISFJ/ESFJ/ISTJ 최다, 직관형 희소)
#       ② 온라인·쇼츠 참여(외향·감각·감정형이 즉각 소구·바이럴, ISTP는 SNS 최저, 내향직관은 인구대비 유튜브 참여↑)
# → 앞쪽 = 초반 조회수 잘 나올 가능성 높은 유형. 데이터 쌓이면 재정렬.
MBTI_ROUND_ORDER = ["ESFP", "ESFJ", "ENFP", "ESTP", "ISFJ", "ISFP", "ISTJ", "ESTJ",
                    "ENTP", "ENFJ", "INFP", "INTP", "ISTP", "INTJ", "ENTJ", "INFJ"]

# MBTI 16유형별 기본 '무드'(지속 페르소나/분위기). 미리 1회 정의해 모든 장 후크 생성에 재사용.
# 편집하면 campaign.moods(json)에 저장되고, 비어있으면 이 기본값 사용.
MBTI_MOODS = {
    "ISTJ": "믿음직한 정공법 — 검증된 사실로 차곡차곡",
    "ISFJ": "따뜻한 보살핌 — 사람을 챙기는 시선",
    "INFJ": "의미심장한 통찰 — 깊은 뜻을 짚어줌",
    "INTJ": "냉철한 분석 — 원리와 큰 그림",
    "ISTP": "쿨한 실용 — 작동 원리·핵심만",
    "ISFP": "감성적 미감 — 장면과 분위기",
    "INFP": "진정성 있는 울림 — 가치와 마음",
    "INTP": "호기심 탐구 — '왜?'를 파고듦",
    "ESTP": "짜릿한 반전 — 즉각적 흥미·스릴",
    "ESFP": "활기찬 즐거움 — 신나고 생생하게",
    "ENFP": "설레는 가능성 — 상상과 영감",
    "ENTP": "도발적 역발상 — 통념 비틀기",
    "ESTJ": "단호한 결론 — 핵심 교훈·실행",
    "ESFJ": "다정한 공감 — 함께 느끼는 따뜻함",
    "ENFJ": "영감 주는 리더십 — 동기부여·비전",
    "ENTJ": "강력한 임팩트 — 큰 야망·결단",
}

_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campaign.db"
_title_cache: dict = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    cx = sqlite3.connect(_DB_PATH)
    cx.row_factory = sqlite3.Row
    cx.executescript(
        """
        CREATE TABLE IF NOT EXISTS campaign(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, chapters TEXT, mbti_order TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS hook(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INT, chapter INT, mbti TEXT, line1 TEXT, line2 TEXT,
            edited INT DEFAULT 0, created TEXT,
            UNIQUE(campaign_id, chapter, mbti));
        CREATE TABLE IF NOT EXISTS slot(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INT, chapter INT, mbti TEXT, hook_id INT,
            day_number INT, date TEXT, status TEXT DEFAULT 'planned',
            video_path TEXT, youtube_video_id TEXT, produced_at TEXT,
            UNIQUE(campaign_id, chapter, mbti));
        CREATE TABLE IF NOT EXISTS view_stat(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INT, fetched_at TEXT, view_count INT);
        """
    )
    # 마이그레이션: campaign.moods(json) 컬럼이 없으면 추가
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(campaign)")}
    if "moods" not in cols:
        cx.execute("ALTER TABLE campaign ADD COLUMN moods TEXT")
    return cx


# ── 장 발견 / 제목 ────────────────────────────────────────────────────────────
def discover_chapters(series: Optional[str] = None) -> List[int]:
    """활성(또는 지정) 시리즈 input 폴더의 chNN_bundle 에서 장 번호 추출."""
    indir = _series.input_dir(series)
    if not indir or not indir.is_dir():
        return []
    out = []
    for d in indir.iterdir():
        if d.is_dir() and d.name.endswith("_bundle"):
            digits = "".join(ch for ch in d.name[:d.name.index("_bundle")] if ch.isdigit())
            if digits:
                out.append(int(digits))
    return sorted(set(out))


def _bundle_dir(chapter: int, series: Optional[str] = None) -> Optional[Path]:
    indir = _series.input_dir(series)
    if not indir:
        return None
    cand = indir / f"ch{chapter:02d}_bundle"
    return cand if cand.is_dir() else None


def chapter_title(chapter: int, series: Optional[str] = None) -> str:
    s = series or _series.active_series()
    key = (s, chapter)
    if key in _title_cache:
        return _title_cache[key]
    title = ""
    bdir = _bundle_dir(chapter, series)
    if bdir:
        try:
            sj = next((bdir / "script").glob("*_script.json"), None)
            if sj:
                title = (json.loads(sj.read_text(encoding="utf-8")).get("title") or "").strip()
        except Exception:
            pass
    _title_cache[key] = title
    return title


# ── 캠페인 (시리즈당 1개) ─────────────────────────────────────────────────────
def ensure_campaign(name: Optional[str] = None, chapters: Optional[List[int]] = None) -> dict:
    """활성 시리즈명으로 캠페인을 보장(없으면 생성). chapters 미지정 시 input 에서 자동 발견.
    기존 캠페인이 있어도 새 장이 늘면 chapters 를 갱신."""
    name = (name or _series.active_series() or "default").strip()
    chapters = chapters or discover_chapters(name if name in _series.list_series() else None)
    with _conn() as cx:
        row = cx.execute("SELECT * FROM campaign WHERE name=?", (name,)).fetchone()
        if row is None:
            cx.execute("INSERT INTO campaign(name, chapters, mbti_order, created) VALUES(?,?,?,?)",
                       (name, json.dumps(chapters), json.dumps(MBTI_ROUND_ORDER), _now()))
            row = cx.execute("SELECT * FROM campaign WHERE name=?", (name,)).fetchone()
        else:
            sets, vals = [], []
            if chapters and json.loads(row["chapters"] or "[]") != chapters:
                sets.append("chapters=?"); vals.append(json.dumps(chapters))
            # 레거시 기본 순서(MBTI16) 캠페인은 새 라운드 순서로 1회 자동 업그레이드(미커스텀일 때만)
            if json.loads(row["mbti_order"] or "[]") == MBTI16:
                sets.append("mbti_order=?"); vals.append(json.dumps(MBTI_ROUND_ORDER))
            if sets:
                vals.append(row["id"])
                cx.execute(f"UPDATE campaign SET {', '.join(sets)} WHERE id=?", vals)
                row = cx.execute("SELECT * FROM campaign WHERE id=?", (row["id"],)).fetchone()
        return _campaign_dict(row)


def _campaign_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"],
            "chapters": json.loads(row["chapters"] or "[]"),
            "mbti_order": json.loads(row["mbti_order"] or "[]") or MBTI_ROUND_ORDER,
            "created": row["created"]}


def get_campaign() -> dict:
    return ensure_campaign()


# ── MBTI 무드 가이드 (16개·미리 정의, 모든 장 후크 생성에 재사용) ──────────────
def get_moods() -> dict:
    """저장된 무드 맵(없으면 기본값). 누락 유형은 기본값으로 채움."""
    camp = ensure_campaign()
    with _conn() as cx:
        row = cx.execute("SELECT moods FROM campaign WHERE id=?", (camp["id"],)).fetchone()
    saved = {}
    try:
        saved = json.loads((row["moods"] if row else None) or "{}")
    except Exception:
        saved = {}
    return {m: (saved.get(m) or MBTI_MOODS[m]) for m in MBTI16}


def set_moods(moods: dict) -> dict:
    camp = ensure_campaign()
    clean = {m: str(moods.get(m, "")).strip() for m in MBTI16 if str(moods.get(m, "")).strip()}
    with _conn() as cx:
        cx.execute("UPDATE campaign SET moods=? WHERE id=?", (json.dumps(clean, ensure_ascii=False), camp["id"]))
    return {"ok": True, "moods": get_moods()}


# ── 후크 뱅크 ─────────────────────────────────────────────────────────────────
def gen_hooks(chapter: int) -> dict:
    """그 장의 16유형 후크를 LLM 으로 생성해 뱅크에 저장(이미 손수정된 행은 보존). 반환: {mbti: {...}}."""
    camp = ensure_campaign()
    bdir = _bundle_dir(chapter)
    if not bdir:
        raise FileNotFoundError(f"ch{chapter:02d}_bundle 을 활성 시리즈 input 에서 찾을 수 없습니다")
    b = _bundle.load_bundle(bdir)
    scenes = [{"scene_index": s.index, "narration": s.narration_text} for s in b.scenes]
    hooks = _llm.gen_mbti_hooks(b.title or f"{chapter}장", scenes, moods=get_moods())
    with _conn() as cx:
        edited = {r["mbti"] for r in cx.execute(
            "SELECT mbti FROM hook WHERE campaign_id=? AND chapter=? AND edited=1",
            (camp["id"], chapter))}
        for mbti, h in hooks.items():
            if mbti in edited:
                continue  # 손수정 보존
            cx.execute(
                "INSERT INTO hook(campaign_id,chapter,mbti,line1,line2,edited,created) "
                "VALUES(?,?,?,?,?,0,?) "
                "ON CONFLICT(campaign_id,chapter,mbti) DO UPDATE SET line1=excluded.line1, "
                "line2=excluded.line2 WHERE hook.edited=0",
                (camp["id"], chapter, mbti, h.get("line1", ""), h.get("line2", ""), _now()))
    return get_hooks(chapter)


def regen_one_hook(chapter: int, mbti: str) -> dict:
    """그 장 + MBTI 무드로 후크 1개를 새로 제안(에디터용, 뱅크는 안 바꿈). 반환 {line1, line2}."""
    bdir = _bundle_dir(chapter)
    if not bdir:
        raise FileNotFoundError(f"ch{chapter:02d}_bundle 을 활성 시리즈 input 에서 찾을 수 없습니다")
    b = _bundle.load_bundle(bdir)
    scenes = [{"scene_index": s.index, "narration": s.narration_text} for s in b.scenes]
    mood = get_moods().get(mbti.upper(), "")
    return _llm.gen_one_mbti_hook(b.title or f"{chapter}장", scenes, mbti.upper(), mood)


def mbti_captions(title: str, scenes: list, mbti: str) -> dict:
    """에디터의 현재 씬들(scenes:[{scene_index,narration}])을 그 MBTI 무드 톤으로 자막 재생성. {idx: caption}."""
    mood = get_moods().get(mbti.upper(), "")
    return _llm.gen_mbti_captions(title or "", scenes, mbti.upper(), mood)


def get_hooks(chapter: int) -> dict:
    camp = ensure_campaign()
    with _conn() as cx:
        rows = cx.execute("SELECT mbti,line1,line2,edited FROM hook WHERE campaign_id=? AND chapter=?",
                          (camp["id"], chapter)).fetchall()
    return {r["mbti"]: {"line1": r["line1"], "line2": r["line2"], "edited": r["edited"]} for r in rows}


def update_hook(chapter: int, mbti: str, line1: str, line2: str) -> dict:
    camp = ensure_campaign()
    with _conn() as cx:
        cx.execute(
            "INSERT INTO hook(campaign_id,chapter,mbti,line1,line2,edited,created) VALUES(?,?,?,?,?,1,?) "
            "ON CONFLICT(campaign_id,chapter,mbti) DO UPDATE SET line1=excluded.line1, "
            "line2=excluded.line2, edited=1",
            (camp["id"], chapter, mbti.upper(), line1, line2, _now()))
    return {"ok": True}


# ── 스케줄 (무중복) ───────────────────────────────────────────────────────────
def _schedule(camp: dict) -> List[dict]:
    chapters = camp["chapters"]
    mbti = camp["mbti_order"] or MBTI16
    n, m = len(chapters), len(mbti)
    rows = []
    if n == 0:
        return rows
    # 라운드 기반: 한 라운드(=N일) 동안 같은 MBTI로 장 1..N 을 쭉, 다음 라운드에 다음 MBTI.
    for d in range(1, n * m + 1):
        c = (d - 1) % n          # 장 인덱스 (라운드 내에서 1..N 순환)
        r = (d - 1) // n         # 라운드 인덱스 → MBTI 결정
        rows.append({"day": d, "chapter": chapters[c], "mbti": mbti[r % m]})
    return rows


def master_list() -> List[dict]:
    """272행(=장수×16) 마스터 리스트: day·장·제목·MBTI·후크·상태·video_path."""
    camp = ensure_campaign()
    with _conn() as cx:
        hooks = {(r["chapter"], r["mbti"]): r for r in cx.execute(
            "SELECT chapter,mbti,line1,line2,edited FROM hook WHERE campaign_id=?", (camp["id"],))}
        slots = {(r["chapter"], r["mbti"]): r for r in cx.execute(
            "SELECT chapter,mbti,status,video_path,youtube_video_id FROM slot WHERE campaign_id=?", (camp["id"],))}
        latest = {(r["chapter"], r["mbti"]): r["view_count"] for r in cx.execute(
            "SELECT s.chapter,s.mbti,v.view_count FROM slot s JOIN view_stat v ON v.slot_id=s.id "
            "WHERE s.campaign_id=? AND v.id=(SELECT id FROM view_stat v2 WHERE v2.slot_id=s.id "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1)", (camp["id"],))}
    moods = get_moods()
    out = []
    for row in _schedule(camp):
        key = (row["chapter"], row["mbti"])
        h = hooks.get(key)
        sl = slots.get(key)
        out.append({
            "day": row["day"], "chapter": row["chapter"],
            "title": chapter_title(row["chapter"]), "mbti": row["mbti"],
            "mood": moods.get(row["mbti"], ""),
            "line1": h["line1"] if h else "", "line2": h["line2"] if h else "",
            "edited": (h["edited"] if h else 0),
            "status": (sl["status"] if sl else "planned"),
            "video_path": (sl["video_path"] if sl else ""),
            "video_id": (sl["youtube_video_id"] if sl else "") or "",
            "views": latest.get(key),
        })
    return out


def next_assignment() -> Optional[dict]:
    """스케줄 순서상 아직 생산되지 않은 첫 셀."""
    for row in master_list():
        if row["status"] != "produced":
            return row
    return None


def mark_produced(chapter: int, mbti: str, video_path: str = "") -> dict:
    camp = ensure_campaign()
    mbti = mbti.upper()
    with _conn() as cx:
        hk = cx.execute("SELECT id FROM hook WHERE campaign_id=? AND chapter=? AND mbti=?",
                        (camp["id"], chapter, mbti)).fetchone()
        cx.execute(
            "INSERT INTO slot(campaign_id,chapter,mbti,hook_id,status,video_path,produced_at) "
            "VALUES(?,?,?,?,'produced',?,?) "
            "ON CONFLICT(campaign_id,chapter,mbti) DO UPDATE SET status='produced', "
            "video_path=excluded.video_path, produced_at=excluded.produced_at",
            (camp["id"], chapter, mbti, (hk["id"] if hk else None), video_path, _now()))
    return {"ok": True}


def progress() -> dict:
    camp = ensure_campaign()
    total = len(camp["chapters"]) * len(camp["mbti_order"] or MBTI16)
    with _conn() as cx:
        produced = cx.execute("SELECT COUNT(*) c FROM slot WHERE campaign_id=? AND status='produced'",
                              (camp["id"],)).fetchone()["c"]
        linked = cx.execute("SELECT COUNT(*) c FROM slot WHERE campaign_id=? AND youtube_video_id IS NOT NULL "
                            "AND youtube_video_id!=''", (camp["id"],)).fetchone()["c"]
    return {"series": camp["name"], "produced": produced, "total": total,
            "chapters": len(camp["chapters"]), "linked": linked,
            "youtube": _youtube.available()}


# ── 조회수 연동 (Phase 3) ─────────────────────────────────────────────────────
def set_video(chapter: int, mbti: str, video: str) -> dict:
    """발행한 쇼츠의 URL/ID 를 (장,MBTI) 셀에 연결. slot 이 없으면 생성."""
    camp = ensure_campaign()
    vid = _youtube.extract_id(video) or (video or "").strip()
    with _conn() as cx:
        cx.execute(
            "INSERT INTO slot(campaign_id,chapter,mbti,youtube_video_id) VALUES(?,?,?,?) "
            "ON CONFLICT(campaign_id,chapter,mbti) DO UPDATE SET youtube_video_id=excluded.youtube_video_id",
            (camp["id"], chapter, mbti.upper(), vid))
    return {"ok": True, "video_id": vid}


def refresh_views() -> dict:
    """연결된 모든 영상의 조회수를 가져와 view_stat 에 일자별 적재."""
    if not _youtube.available():
        raise RuntimeError("YOUTUBE_API_KEY 미설정 (.env 확인)")
    camp = ensure_campaign()
    with _conn() as cx:
        rows = cx.execute(
            "SELECT id,youtube_video_id FROM slot WHERE campaign_id=? AND youtube_video_id IS NOT NULL "
            "AND youtube_video_id!=''", (camp["id"],)).fetchall()
    idmap = {r["youtube_video_id"]: r["id"] for r in rows}
    if not idmap:
        return {"ok": True, "updated": 0, "linked": 0}
    views = _youtube.fetch_views(list(idmap.keys()))
    now = _now()
    with _conn() as cx:
        for vid, vc in views.items():
            cx.execute("INSERT INTO view_stat(slot_id,fetched_at,view_count) VALUES(?,?,?)",
                       (idmap[vid], now, vc))
    return {"ok": True, "updated": len(views), "linked": len(idmap), "at": now}


def insights() -> dict:
    """각 셀의 '최신 조회수'를 MBTI별·장별로 평균 집계 → 어떤 유형/장이 잘 먹히나."""
    camp = ensure_campaign()
    with _conn() as cx:
        rows = cx.execute(
            "SELECT s.chapter,s.mbti,v.view_count FROM slot s JOIN view_stat v ON v.slot_id=s.id "
            "WHERE s.campaign_id=? AND v.id=(SELECT id FROM view_stat v2 WHERE v2.slot_id=s.id "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1)", (camp["id"],)).fetchall()
    by_mbti: dict = {}
    by_chapter: dict = {}
    for r in rows:
        by_mbti.setdefault(r["mbti"], []).append(r["view_count"])
        by_chapter.setdefault(r["chapter"], []).append(r["view_count"])

    def agg(d, label):
        out = [{"key": k, "n": len(v), "avg": round(sum(v) / len(v), 1),
                "total": sum(v), "max": max(v)} for k, v in d.items()]
        return sorted(out, key=lambda x: -x["avg"])

    return {"samples": len(rows),
            "by_mbti": agg(by_mbti, "mbti"),
            "by_chapter": agg(by_chapter, "chapter")}

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

MBTI16 = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
          "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ"]

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
                       (name, json.dumps(chapters), json.dumps(MBTI16), _now()))
            row = cx.execute("SELECT * FROM campaign WHERE name=?", (name,)).fetchone()
        elif chapters and json.loads(row["chapters"] or "[]") != chapters:
            cx.execute("UPDATE campaign SET chapters=? WHERE id=?", (json.dumps(chapters), row["id"]))
            row = cx.execute("SELECT * FROM campaign WHERE id=?", (row["id"],)).fetchone()
        return _campaign_dict(row)


def _campaign_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"],
            "chapters": json.loads(row["chapters"] or "[]"),
            "mbti_order": json.loads(row["mbti_order"] or "[]") or MBTI16,
            "created": row["created"]}


def get_campaign() -> dict:
    return ensure_campaign()


# ── 후크 뱅크 ─────────────────────────────────────────────────────────────────
def gen_hooks(chapter: int) -> dict:
    """그 장의 16유형 후크를 LLM 으로 생성해 뱅크에 저장(이미 손수정된 행은 보존). 반환: {mbti: {...}}."""
    camp = ensure_campaign()
    bdir = _bundle_dir(chapter)
    if not bdir:
        raise FileNotFoundError(f"ch{chapter:02d}_bundle 을 활성 시리즈 input 에서 찾을 수 없습니다")
    b = _bundle.load_bundle(bdir)
    scenes = [{"scene_index": s.index, "narration": s.narration_text} for s in b.scenes]
    hooks = _llm.gen_mbti_hooks(b.title or f"{chapter}장", scenes)
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
    for d in range(1, n * m + 1):
        c = (d - 1) % n
        r = (d - 1) // n
        rows.append({"day": d, "chapter": chapters[c], "mbti": mbti[(r + c) % m]})
    return rows


def master_list() -> List[dict]:
    """272행(=장수×16) 마스터 리스트: day·장·제목·MBTI·후크·상태·video_path."""
    camp = ensure_campaign()
    with _conn() as cx:
        hooks = {(r["chapter"], r["mbti"]): r for r in cx.execute(
            "SELECT chapter,mbti,line1,line2,edited FROM hook WHERE campaign_id=?", (camp["id"],))}
        slots = {(r["chapter"], r["mbti"]): r for r in cx.execute(
            "SELECT chapter,mbti,status,video_path FROM slot WHERE campaign_id=?", (camp["id"],))}
    out = []
    for row in _schedule(camp):
        key = (row["chapter"], row["mbti"])
        h = hooks.get(key)
        sl = slots.get(key)
        out.append({
            "day": row["day"], "chapter": row["chapter"],
            "title": chapter_title(row["chapter"]), "mbti": row["mbti"],
            "line1": h["line1"] if h else "", "line2": h["line2"] if h else "",
            "edited": (h["edited"] if h else 0),
            "status": (sl["status"] if sl else "planned"),
            "video_path": (sl["video_path"] if sl else ""),
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
    return {"series": camp["name"], "produced": produced, "total": total,
            "chapters": len(camp["chapters"])}

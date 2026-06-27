"""쇼츠공방 — 독립 세로 쇼츠 제작 웹앱 (FastAPI).

번들(chNN_bundle) → 씬 자동 구성 → 씬별 문구(상단 후크 / 하단 자막) 편집 →
9:16 쇼츠 렌더 → 미리보기 + 유튜브 메타. LLM은 LiteLLM 한 곳으로 연결.

로컬 단일 사용자용. `run.bat` 으로 실행 → http://127.0.0.1:7010
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from shortsmaker import campaign, llm, series, tts
from shortsmaker.bundle import load_bundle
from shortsmaker.fonts import find_font
from shortsmaker.shorts import Beat, ShortsConfig, ShortsSpec, build_default_spec, build_shorts

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

# 번들을 찾을 위치는 .env 의 SHORTS_BUNDLE_ROOTS(세미콜론 구분)로 지정한다.
DEFAULT_ROOTS: List[str] = []


def _bundle_roots() -> List[Path]:
    # 시리즈 루트(SHORTS_SERIES_ROOT)가 설정되면 활성 시리즈의 input 만(미정이면 전체 시리즈 input) 사용.
    sroot = series.series_root()
    if sroot and sroot.is_dir():
        active_in = series.input_dir()
        if active_in and active_in.is_dir():
            return [active_in]
        return [d / "input" for d in sorted(sroot.iterdir())
                if d.is_dir() and (d / "input").is_dir()]
    # 폴백: 레거시 정적 루트(SHORTS_BUNDLE_ROOTS)
    roots = [Path(p) for p in (os.environ.get("SHORTS_BUNDLE_ROOTS") or "").split(";") if p.strip()]
    roots += [Path(p) for p in DEFAULT_ROOTS]
    return [r for r in roots if r.exists()]


def _allowed(path: Path) -> bool:
    """Only serve files that live under a known bundle root (local-safety)."""
    rp = path.resolve()
    for r in _bundle_roots():
        try:
            rp.relative_to(r.resolve())
            return True
        except ValueError:
            continue
    return False


app = FastAPI(title="쇼츠공방")


# ---------------- jobs (in-memory) ----------------
class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex
        self.logs: List[str] = []
        self.running = True
        self.error = ""
        self.path = ""
        self.data: Dict[str, Any] = {}
        self.updated = time.time()

    def log(self, msg: str) -> None:
        self.logs.append(msg)
        self.updated = time.time()


JOBS: Dict[str, Job] = {}


# ---------------- AI 후크 보관함 (영구 저장) ----------------
HOOKS_FILE = DATA / "hooks.json"


def _load_hooks() -> List[str]:
    try:
        if HOOKS_FILE.exists():
            return json.loads(HOOKS_FILE.read_text(encoding="utf-8")).get("hooks", [])
    except Exception:
        pass
    return []


def _save_hook(hook: str) -> List[str]:
    hook = (hook or "").strip()
    hooks = _load_hooks()
    if not hook:
        return hooks
    hooks = [h for h in hooks if h != hook]
    hooks.insert(0, hook)
    hooks = hooks[:50]
    try:
        HOOKS_FILE.write_text(json.dumps({"hooks": hooks}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        pass
    return hooks


# ---------------- models ----------------
class SpecRequest(BaseModel):
    bundle_dir: str
    duration: float = 30.0
    target_beats: int = 7
    speed: float = 1.0


class BeatModel(BaseModel):
    image: str = ""
    hook: str = ""
    caption: str = ""
    duration: float = 4.0
    image2: Optional[str] = None
    scene_index: int = 0
    template: Optional[int] = None
    video: Optional[str] = None
    clip_start: float = 0.0


class RenderRequest(BaseModel):
    bundle_dir: str
    beats: List[BeatModel]
    audio: Optional[str] = None
    hashtags: str = "#쇼츠"
    title: str = ""
    speed: float = 1.0
    width: int = 1080
    height: int = 1920
    hook_scale1: float = 1.0
    hook_scale2: float = 1.0
    hook_color1: str = "#111111"
    hook_color2: str = "#F4511E"


class SuggestRequest(BaseModel):
    kind: str = "hook"          # hook | caption
    narration: str = ""
    current: str = ""


class MetaRequest(BaseModel):
    text: str = ""
    original_url: str = ""
    title_hint: str = ""


# ---------------- API ----------------
@app.get("/api/health")
async def health():
    name, path = find_font()
    return {"ok": True, "font": name, "llm": llm.status(), "roots": [str(r) for r in _bundle_roots()]}


class ProviderReq(BaseModel):
    provider: str


class MaybeProviderReq(BaseModel):
    provider: Optional[str] = None


class ModelReq(BaseModel):
    model: str = ""


@app.get("/api/llm/status")
async def llm_status():
    return await asyncio.to_thread(llm.status, False)


@app.post("/api/llm/provider")
async def llm_provider(req: ProviderReq):
    try:
        return await asyncio.to_thread(llm.set_provider, req.provider)
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))


@app.post("/api/llm/login")
async def llm_login(req: MaybeProviderReq):
    try:
        return await asyncio.to_thread(llm.launch_login, req.provider)
    except llm.LLMUnavailable as e:
        raise HTTPException(500, str(e))


@app.post("/api/llm/logout")
async def llm_logout(req: MaybeProviderReq):
    try:
        return await asyncio.to_thread(llm.logout, req.provider)
    except llm.LLMUnavailable as e:
        raise HTTPException(500, str(e))


@app.get("/api/llm/models")
async def llm_models():
    models = await asyncio.to_thread(llm.list_models)
    current = await asyncio.to_thread(llm.get_model)
    return {"models": models, "current": current}


@app.post("/api/llm/model")
async def llm_set_model(req: ModelReq):
    try:
        return await asyncio.to_thread(llm.set_model, req.model)
    except llm.LLMUnavailable as e:
        raise HTTPException(400, str(e))


# ---------------- 캠페인 (MBTI 후크 × 무중복 스케줄) ----------------
class SeriesReq(BaseModel):
    series: str


class ChapterReq(BaseModel):
    chapter: int


class HookReq(BaseModel):
    chapter: int
    mbti: str
    line1: str = ""
    line2: str = ""


class ProducedReq(BaseModel):
    chapter: int
    mbti: str
    video_path: str = ""


@app.get("/api/series")
async def series_list():
    return {"series": series.list_series(), "active": series.active_series()}


@app.post("/api/series/active")
async def series_set_active(req: SeriesReq):
    active = await asyncio.to_thread(series.set_active, req.series)
    await asyncio.to_thread(campaign.ensure_campaign)   # 전환된 시리즈 캠페인 보장
    return {"ok": True, "active": active}


@app.get("/api/campaign/state")
async def campaign_state():
    return await asyncio.to_thread(campaign.progress)


@app.get("/api/campaign/list")
async def campaign_list():
    rows = await asyncio.to_thread(campaign.master_list)
    return {"rows": rows, "progress": await asyncio.to_thread(campaign.progress)}


@app.post("/api/campaign/hooks/gen")
async def campaign_hooks_gen(req: ChapterReq):
    if not llm.available():
        raise HTTPException(400, "LLM 미연결 — 로그인 후 사용하세요")
    try:
        return await asyncio.to_thread(campaign.gen_hooks, req.chapter)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.get("/api/campaign/hooks")
async def campaign_hooks_get(chapter: int):
    return await asyncio.to_thread(campaign.get_hooks, chapter)


class MbtiChapterReq(BaseModel):
    chapter: int
    mbti: str


class MbtiCaptionsReq(BaseModel):
    title: str = ""
    scenes: List[Dict[str, Any]] = []
    mbti: str


@app.post("/api/campaign/hooks/regen-one")
async def campaign_regen_one(req: MbtiChapterReq):
    if not llm.available():
        raise HTTPException(400, "LLM 미연결 — 로그인 후 사용하세요")
    try:
        return await asyncio.to_thread(campaign.regen_one_hook, req.chapter, req.mbti)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/campaign/captions")
async def campaign_captions(req: MbtiCaptionsReq):
    if not llm.available():
        raise HTTPException(400, "LLM 미연결 — 로그인 후 사용하세요")
    try:
        caps = await asyncio.to_thread(campaign.mbti_captions, req.title, req.scenes, req.mbti)
        return {"captions": caps}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/campaign/hooks")
async def campaign_hooks_set(req: HookReq):
    return await asyncio.to_thread(campaign.update_hook, req.chapter, req.mbti, req.line1, req.line2)


@app.post("/api/campaign/produced")
async def campaign_produced(req: ProducedReq):
    return await asyncio.to_thread(campaign.mark_produced, req.chapter, req.mbti, req.video_path)


class VideoReq(BaseModel):
    chapter: int
    mbti: str
    video: str = ""


@app.post("/api/campaign/video")
async def campaign_video(req: VideoReq):
    return await asyncio.to_thread(campaign.set_video, req.chapter, req.mbti, req.video)


@app.post("/api/campaign/views/refresh")
async def campaign_views_refresh():
    try:
        return await asyncio.to_thread(campaign.refresh_views)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.get("/api/campaign/insights")
async def campaign_insights():
    return await asyncio.to_thread(campaign.insights)


class MoodsReq(BaseModel):
    moods: Dict[str, str]


@app.get("/api/campaign/moods")
async def campaign_moods_get():
    return {"moods": await asyncio.to_thread(campaign.get_moods),
            "order": campaign.MBTI_ROUND_ORDER}


@app.post("/api/campaign/moods")
async def campaign_moods_set(req: MoodsReq):
    return await asyncio.to_thread(campaign.set_moods, req.moods)


@app.get("/api/bundles")
async def list_bundles(root: str = ""):
    roots = [Path(root)] if root.strip() else _bundle_roots()
    seen, out = set(), []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*_bundle"):
            if not p.is_dir() or p in seen:
                continue
            if not (p / "script").is_dir():
                continue
            seen.add(p)
            title = ""
            try:
                title = load_bundle(p).title
            except Exception:
                pass
            out.append({"dir": str(p), "name": p.name, "title": title})
    out.sort(key=lambda x: x["dir"])
    return {"bundles": out}


def _spec_to_json(spec: ShortsSpec) -> Dict[str, Any]:
    return {
        "title": spec.title,
        "audio": spec.audio,
        "hashtags": spec.hashtags,
        "speed": spec.speed,
        "beats": [
            {"image": b.image, "hook": b.hook, "caption": b.caption,
             "duration": b.duration, "scene_index": b.scene_index, "template": b.template}
            for b in spec.beats
        ],
    }


@app.post("/api/spec")
async def make_spec(req: SpecRequest):
    bdir = Path(req.bundle_dir)
    if not bdir.is_dir():
        raise HTTPException(400, "번들 폴더가 없습니다")
    try:
        bundle = load_bundle(bdir)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"번들 로드 실패: {e}")
    spec = build_default_spec(bundle, target_beats=req.target_beats,
                              duration=req.duration, speed=req.speed)
    return _spec_to_json(spec)


@app.post("/api/scenes")
async def all_scenes(req: SpecRequest):
    """번들의 모든 씬(추가/교체용) — 이미지·내레이션·자막 힌트."""
    bdir = Path(req.bundle_dir)
    try:
        bundle = load_bundle(bdir)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"번들 로드 실패: {e}")
    scenes = []
    for s in bundle.scenes:
        if not s.image_path:
            continue
        scenes.append({
            "scene_index": s.index, "title": s.title,
            "image": str(s.image_path),
            "narration": s.narration_text,
            "subtitle": (s.scene_meta or {}).get("subtitle") or "",
        })
    return {"scenes": scenes, "title": bundle.title}


@app.get("/api/image")
async def serve_image(path: str):
    p = Path(path)
    if not p.exists() or not _allowed(p):
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return FileResponse(str(p))


@app.post("/api/suggest")
async def suggest(req: SuggestRequest):
    if not llm.available():
        raise HTTPException(503, "LiteLLM 미설정 (.env 의 LITELLM_MODEL 확인)")
    try:
        if req.kind == "caption":
            text = await asyncio.to_thread(llm.suggest_caption, req.narration, req.current)
        else:
            text = await asyncio.to_thread(llm.suggest_hook, req.narration, req.current)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM 오류: {e}")
    return {"text": text}


class AiFillRequest(BaseModel):
    title: str = ""
    scenes: List[Dict[str, Any]] = []
    review_of: Optional[Dict[str, Any]] = None
    only: Optional[str] = None    # "hook" | "captions" | None(전체)


@app.post("/api/ai-fill")
async def ai_fill(req: AiFillRequest):
    if not llm.available():
        raise HTTPException(503, "LLM 미로그인 (상단 LLM 칩에서 로그인)")
    try:
        res = await asyncio.to_thread(llm.gen_fill, req.title, req.scenes, req.review_of, req.only)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM 오류: {e}")
    hk = "\n".join(x for x in [res.get("hook1"), res.get("hook2")] if x)
    if hk:
        _save_hook(hk)   # 생성된 후크 자동 보관
    return res


class HookReq(BaseModel):
    hook: str


@app.get("/api/hooks")
async def get_hooks():
    return {"hooks": _load_hooks()}


@app.post("/api/hooks")
async def add_hook(req: HookReq):
    return {"hooks": _save_hook(req.hook)}


class TidyRequest(BaseModel):
    title: str = ""
    scenes: List[Dict[str, Any]] = []   # [{scene_index, narration, caption}]


@app.post("/api/tidy")
async def tidy(req: TidyRequest):
    if not llm.available():
        raise HTTPException(503, "LLM 미로그인 (상단 LLM 칩에서 로그인)")
    try:
        return await asyncio.to_thread(llm.tidy_all, req.title, req.scenes)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM 오류: {e}")


class VerifyRequest(BaseModel):
    scenes: List[Dict[str, Any]] = []


@app.post("/api/verify")
async def verify(req: VerifyRequest):
    if not llm.available():
        raise HTTPException(503, "LLM 미로그인 (상단 LLM 칩에서 로그인)")
    try:
        return await asyncio.to_thread(llm.verify_captions, req.scenes)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM 오류: {e}")


@app.post("/api/meta")
async def meta(req: MetaRequest):
    if not llm.available():
        raise HTTPException(503, "LiteLLM 미설정 (.env 의 LITELLM_MODEL 확인)")
    try:
        text = await asyncio.to_thread(llm.shorts_meta, req.text, req.original_url, req.title_hint)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM 오류: {e}")
    return {"meta": text}


async def _run_render(job: Job, req: RenderRequest) -> None:
    try:
        spec = ShortsSpec(
            beats=[Beat(**b.model_dump()) for b in req.beats],
            audio=req.audio, hashtags=req.hashtags, title=req.title, speed=req.speed,
        )
        cfg = ShortsConfig(width=req.width, height=req.height,
                           font_name=find_font()[0], speed=req.speed,
                           hook_scale1=req.hook_scale1, hook_scale2=req.hook_scale2,
                           hook_color1=req.hook_color1, hook_color2=req.hook_color2)
        out_name = (Path(req.bundle_dir).name or "shorts").replace("_bundle", "")
        out_dir = series.output_dir() or DATA      # 활성 시리즈 output, 없으면 data 폴백
        out_path = out_dir / f"{out_name}_{job.id[:8]}_shorts.mp4"
        work = DATA / f"_work_{job.id[:8]}"

        def _log(m: str) -> None:
            job.log(m)

        await asyncio.to_thread(build_shorts, spec, out_path, work, cfg, _log)
        job.path = str(out_path)
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        job.error = str(e)
        job.log(f"[error] {e}")
    finally:
        job.running = False
        job.updated = time.time()


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _longform(bundle_dir: str):
    """씬별 타임라인 + **자막 없는 클린 롱폼**(_nosub) 경로.

    자막이 박힌 _final/_final_softsub 는 쓰지 않는다(옛 자막이 쇼츠에 겹쳐 보임).
    클린본이 없으면 None → 이미지 방식으로 폴백.
    """
    draft = Path(bundle_dir) / "draft"
    starts: Dict[int, float] = {}
    rep = draft / "render_report.json"
    if rep.exists():
        try:
            r = json.loads(rep.read_text(encoding="utf-8"))
            for s in r.get("scenes", []):
                starts[int(s["scene"])] = float(s.get("timeline_start") or 0)
        except Exception:
            pass
    nosub = sorted(draft.glob("*_final_nosub.mp4"))
    video = str(nosub[0]) if nosub else None
    return (video if (video and Path(video).exists()) else None), starts


def _concat_wavs(files: List[str], out_path: str) -> None:
    listf = Path(out_path).with_suffix(".txt")
    listf.write_text("\n".join(f"file '{Path(f).resolve().as_posix()}'" for f in files) + "\n",
                     encoding="utf-8")
    subprocess.run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
                    "-c:a", "pcm_s16le", str(out_path)], capture_output=True)


class TtsSyncRequest(BaseModel):
    bundle_dir: str
    beats: List[BeatModel]
    voice: str = "F4"
    speed: float = 1.1


async def _run_tts(job: Job, req: TtsSyncRequest) -> None:
    try:
        lines = [(b.caption or b.hook or "...").strip() for b in req.beats]
        outdir = DATA / f"_tts_{job.id[:8]}"
        job.log(f"[tts] {len(lines)}개 자막 → 음성 생성 (F4·{req.speed})…")
        res = await asyncio.to_thread(tts.synth_lines, lines, str(outdir),
                                      voice=req.voice, speed=req.speed)
        res = sorted(res, key=lambda x: x["index"])
        job.log("[tts] 음성 합치는 중…")
        audio = DATA / f"voice_{job.id[:8]}.wav"
        await asyncio.to_thread(_concat_wavs, [r["file"] for r in res], str(audio))
        video, starts = _longform(req.bundle_dir)
        beats_out = []
        for i, b in enumerate(req.beats):
            beats_out.append({"index": i, "scene_index": b.scene_index,
                              "duration": round(res[i]["duration"], 3),
                              "video": video, "clip_start": starts.get(b.scene_index, 0.0)})
        job.data = {"audio": str(audio), "video": video, "has_video": bool(video),
                    "beats": beats_out}
        job.log("[tts] 완료" + ("" if video else
                " (자막 없는 클린 롱폼 _nosub 이 없어 이미지로 렌더됩니다)"))
    except Exception as e:  # noqa: BLE001
        job.error = str(e)
        job.log(f"[error] {e}")
    finally:
        job.running = False
        job.updated = time.time()


@app.post("/api/tts-sync")
async def tts_sync(req: TtsSyncRequest):
    if not req.beats:
        raise HTTPException(400, "씬이 없습니다")
    job = Job()
    JOBS[job.id] = job
    asyncio.create_task(_run_tts(job, req))
    return {"job": job.id}


@app.post("/api/render")
async def render(req: RenderRequest):
    if not req.beats:
        raise HTTPException(400, "씬(beat)이 없습니다")
    job = Job()
    JOBS[job.id] = job
    asyncio.create_task(_run_render(job, req))
    return {"job": job.id}


@app.get("/api/render/{job_id}")
async def render_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job 없음")
    return {"running": job.running, "logs": job.logs, "error": job.error,
            "done": bool(job.path) or bool(job.data), "data": job.data, "path": job.path}


@app.get("/api/video/{job_id}")
async def video(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.path or not Path(job.path).exists():
        raise HTTPException(404, "쇼츠 없음")
    return FileResponse(job.path, media_type="video/mp4",
                        filename=Path(job.path).name, content_disposition_type="inline")


# ---------------- static SPA ----------------
def _asset_ver(name: str) -> str:
    try:
        return str(int((ROOT / "static" / name).stat().st_mtime))
    except Exception:
        return "1"


@app.get("/", response_class=HTMLResponse)
async def index():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    # 정적 파일이 바뀌면 자동으로 새로 받게 캐시버스팅(파일 mtime)
    html = html.replace("/static/style.css", f"/static/style.css?v={_asset_ver('style.css')}")
    html = html.replace("/static/app.js", f"/static/app.js?v={_asset_ver('app.js')}")
    return html


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

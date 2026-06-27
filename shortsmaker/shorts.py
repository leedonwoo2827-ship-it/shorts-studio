"""편집 가능한 세로 쇼츠 컴포지터 (요즘 릴스 스타일).

레이아웃(고정 프레임 + 영상만 변동):
  ┌───────────────┐  상단 흰 띠: 플레이어 아이콘 + 2색 후크(1줄 검정 / 2줄 주황)
  │  ▶ 🔊   ⋯ ⤢   │
  │  이렇게 엮인다고?  │
  │  진짜 보러 가고 싶다│  ← 둘째 줄(주황) = 후크에 Enter 넣으면 생김
  ├───────────────┤
  │               │  중앙: 장면 이미지(켄번스). 분할 시 좌/우 2분할.
  │   [영상/이미지]   │
  │  ─ 흰 자막 ─    │  ← 영상 하단에 자막 오버레이
  ├───────────────┤
  │  #해시 #태그  0:13 │  하단 흰 띠: 해시태그(굵은 회색) + 길이
  └───────────────┘

spec(beats)로 씬마다 후크/자막/길이를 편집한다. 캔버스 크기는 설정값이라 가로(16:9) 전환도 가능.
audio speed>1 → 오디오 가속(피치 유지)으로 쇼츠용 빠른 말속도.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .bundle import Bundle, Scene, load_bundle
from .ffmpeg_runner import dump_cmd_script, ffprobe_duration, run_ffmpeg
from .fonts import find_font
from .kenburns import for_scene as kb_for_scene

# 9:16 기본 캔버스
W = 1080
H = 1920
# 고정 밴드(흰색) 비율 — 영상만 변동, 프레임은 일정(레퍼런스 스타일).
HEADER_H = 404
FOOTER_H = 300                      # 하단 흰 띠(해시태그 3줄 수용)
VIDEO_H = H - HEADER_H - FOOTER_H   # 1216

# 비트별 영상 구성: False=단일 이미지, True=좌/우 2분할 콜라주. 인덱스로 순환(변동).
SPLIT_PATTERN = [False, False, True, False, True, False]
SPLIT_GAP = 6

# 색 (ASS &HAABBGGRR)
C_BLACK = "&H00111111"
C_ORANGE = "&H001E51F4"     # #F4511E
C_WHITE = "&H00FFFFFF"
C_GRAY = "&H00555555"
C_CHROME = "&H00C8C8C8"
C_OUTLINE = "&H00000000"


@dataclass
class ShortsConfig:
    width: int = W
    height: int = H
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    font_name: str = "Malgun Gothic"
    cta_seconds: float = 0.0    # 0이면 별도 CTA 없음(해시태그가 상시 노출)
    speed: float = 1.0
    hook_scale1: float = 1.0    # 후크 1줄 글자 크기 배율
    hook_scale2: float = 1.0    # 후크 2줄 글자 크기 배율
    hook_color1: str = "#111111"   # 후크 1줄 색(hex)
    hook_color2: str = "#F4511E"   # 후크 2줄 색(hex)


@dataclass
class Beat:
    image: str = ""
    hook: str = ""              # 1줄=검정, (Enter 후)2줄=주황
    caption: str = ""
    duration: float = 4.0
    image2: Optional[str] = None
    scene_index: int = 0
    template: Optional[int] = None   # None이면 위치 기반 분할 패턴
    video: Optional[str] = None      # 설정 시 이 영상 구간(음소거)을 중앙에 사용
    clip_start: float = 0.0          # video 시작 위치(초)


@dataclass
class ShortsSpec:
    beats: List[Beat] = field(default_factory=list)
    audio: Optional[str] = None
    hashtags: str = "#쇼츠"
    title: str = ""
    speed: float = 1.0

    @property
    def total(self) -> float:
        return sum(b.duration for b in self.beats)


# ──────────────────────────────────────────────────────────────────────────────
# 기본 spec (편집 텍스트 미리 채우기)
# ──────────────────────────────────────────────────────────────────────────────

def _scene_types(bundle: Bundle) -> dict:
    try:
        data = json.loads(bundle.script_json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for pos, raw in enumerate(data.get("scenes") or []):
        idx = raw.get("scene") or raw.get("scene_number") or (pos + 1)
        out[int(idx)] = str(raw.get("scene_type") or "")
    return out


def _first_sentence(text: str, max_chars: int = 30) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    parts = re.split(r"(?<=[\.\?\!。！？])\s+", text)
    s = (parts[0] if parts else text).strip()
    if len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    return s


def _evenly_spaced(items: list, k: int) -> list:
    if k <= 0 or not items:
        return []
    if k >= len(items):
        return list(items)
    if k == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (k - 1)
    return [items[round(i * step)] for i in range(k)]


def _select_scenes(bundle: Bundle, scene_types: dict, target: int) -> List[Scene]:
    usable = [s for s in bundle.scenes if s.image_path]
    no_preview = [s for s in usable if scene_types.get(s.index) != "next_preview"]
    usable = no_preview or usable
    if len(usable) <= target:
        return usable
    chosen: list[int] = []

    def first_of(t: str):
        for s in usable:
            if scene_types.get(s.index) == t:
                return s
        return None

    for t in ("opening_title", "climax", "closing"):
        s = first_of(t)
        if s and s.index not in chosen:
            chosen.append(s.index)
    body = [s for s in usable if s.index not in chosen]
    for s in _evenly_spaced(body, max(0, target - len(chosen))):
        if s.index not in chosen:
            chosen.append(s.index)
    by_idx = {s.index: s for s in usable}
    return [by_idx[i] for i in sorted(chosen)][:target]


def _default_hashtags(title: str) -> str:
    t = (title or "").strip()
    if not t:
        return "#쇼츠 #공부"
    head = t.split()[0][:10]
    return f"#{head} #쇼츠"


def build_default_spec(bundle: Bundle, *, target_beats: int = 7,
                       duration: float = 30.0, speed: float = 1.0) -> ShortsSpec:
    """번들에서 편집용 spec 초안 생성. speed>1 → 가속분만큼 짧아진 길이에 맞춰 타일링."""
    speed = max(0.5, min(2.0, float(speed or 1.0)))
    types = _scene_types(bundle)
    opening = None
    for s in bundle.scenes:
        if types.get(s.index) == "opening_title":
            opening = s
            break
    if opening is None and bundle.scenes:
        opening = bundle.scenes[0]
    audio = str(opening.audio_path) if (opening and opening.audio_path) else None
    if audio:
        try:
            audio_dur = ffprobe_duration(Path(audio))
        except Exception:
            audio_dur = duration
    else:
        audio_dur = float(opening.narration_seconds_hint if opening else 0.0) or duration
    total = max(5.0, min(audio_dur / speed, duration))

    selected = _select_scenes(bundle, types, target_beats)
    n = len(selected) or 1
    per = total / n
    beats: List[Beat] = []
    for i, sc in enumerate(selected):
        hook = (sc.scene_meta or {}).get("subtitle") or sc.title or bundle.title
        if i == 0 and bundle.title:
            hook = bundle.title
        beats.append(Beat(
            image=str(sc.image_path),
            hook=hook or "",
            caption=_first_sentence(sc.narration_text),
            duration=round(per, 3),
            scene_index=sc.index,
            template=None,
        ))
    return ShortsSpec(beats=beats, audio=audio, title=bundle.title,
                      hashtags=_default_hashtags(bundle.title), speed=speed)


# ──────────────────────────────────────────────────────────────────────────────
# 비트 렌더 (흰 프레임 + 영상)
# ──────────────────────────────────────────────────────────────────────────────

def _even(n) -> int:
    n = int(round(n))
    return n - (n % 2)


def _cover_kenburns(label_in: str, out: str, scene_index: int, w: int, h: int,
                    dur: float, fps: int) -> str:
    d_frames = max(1, int(round(dur * fps)))
    over = 2
    ow, oh = w * over, h * over
    kb = kb_for_scene(max(1, scene_index), dur, fps, mode="auto")
    return (
        f"{label_in}scale={ow}:{oh}:force_original_aspect_ratio=increase,"
        f"crop={ow}:{oh},setsar=1[{out}_o];"
        f"[{out}_o]zoompan=z='{kb.z_expr}':x='{kb.x_expr}':y='{kb.y_expr}':"
        f"d={d_frames}:fps={fps}:s={w}x{h}[{out}]"
    )


def _is_split(beat: Beat, idx: int) -> bool:
    if beat.template is not None:
        return bool(beat.template)
    return SPLIT_PATTERN[idx % len(SPLIT_PATTERN)]


def _render_beat(beat: Beat, idx: int, out_path: Path, cfg: ShortsConfig,
                 log_path: Path, cmd_dump: Path) -> None:
    Wd, Ht, fps = cfg.width, cfg.height, cfg.fps
    vid_h = Ht - HEADER_H - FOOTER_H
    dur = beat.duration
    use_video = bool(beat.video) and Path(beat.video).exists()
    split = (not use_video) and _is_split(beat, idx) and bool(beat.image2)
    parts: List[str] = []

    if use_video:
        # 롱폼 영상 구간을 음소거하고 중앙 영역에 cover-crop 배치
        inputs = ["-ss", f"{beat.clip_start:.3f}", "-i", beat.video]
        parts.append(
            f"[0:v]scale={Wd}:{vid_h}:force_original_aspect_ratio=increase,"
            f"crop={Wd}:{vid_h},setsar=1,fps={fps}[mv]")
        parts.append(f"color=c=white:s={Wd}x{Ht}:d={dur:.3f}:r={fps},setsar=1[bg]")
        parts.append(f"[bg][mv]overlay=x=0:y={HEADER_H}:shortest=1[ov]")
        parts.append(f"[ov]format=yuv420p[v]")
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "[v]", "-an", "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", cfg.preset, "-crf", str(cfg.crf), "-r", str(fps),
            "-movflags", "+faststart", str(out_path),
        ]
        dump_cmd_script(cmd, cmd_dump)
        run_ffmpeg(cmd, log_path=log_path)
        return

    inputs: List[str] = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", beat.image]

    parts.append(f"color=c=white:s={Wd}x{Ht}:d={dur:.3f}:r={fps},setsar=1[bg]")
    if split:
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", beat.image2]
        half = _even((Wd - SPLIT_GAP) / 2)
        parts.append(_cover_kenburns("[0:v]", "m1", beat.scene_index + 1, half, vid_h, dur, fps))
        parts.append(_cover_kenburns("[1:v]", "m2", beat.scene_index + 2, half, vid_h, dur, fps))
        parts.append(f"[bg][m1]overlay=x=0:y={HEADER_H}:shortest=1[t1]")
        parts.append(f"[t1][m2]overlay=x={Wd - half}:y={HEADER_H}:shortest=1[ov]")
    else:
        parts.append(_cover_kenburns("[0:v]", "m1", beat.scene_index + 1, Wd, vid_h, dur, fps))
        parts.append(f"[bg][m1]overlay=x=0:y={HEADER_H}:shortest=1[ov]")

    parts.append(f"[ov]format=yuv420p[v]")
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-an", "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", cfg.preset, "-crf", str(cfg.crf), "-r", str(fps),
        "-movflags", "+faststart", str(out_path),
    ]
    dump_cmd_script(cmd, cmd_dump)
    run_ffmpeg(cmd, log_path=log_path)


def _concat(segments: List[Path], out_path: Path, log_path: Path) -> None:
    if len(segments) == 1:
        run_ffmpeg(["ffmpeg", "-y", "-i", str(segments[0]), "-c", "copy", str(out_path)],
                   log_path=log_path)
        return
    listfile = out_path.parent / "segments.txt"
    listfile.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in segments) + "\n",
                        encoding="utf-8")
    run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
                "-c", "copy", str(out_path)], log_path=log_path)


# ──────────────────────────────────────────────────────────────────────────────
# ASS 오버레이 (플레이어 아이콘 + 2색 후크 + 자막 + 해시태그)
# ──────────────────────────────────────────────────────────────────────────────

def _ass_time(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs == 100:
        cs = 0; s += 1
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(t: str) -> str:
    return (t or "").replace("\\", "").replace("{", "(").replace("}", ")").strip()


def _wrap_one(text: str, max_chars: int) -> str:
    """한 줄을 max_chars 기준으로 접어 \\N 으로 연결."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return _ass_escape(text)
    out, cur = [], ""
    for w in text.split():
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return r"\N".join(_ass_escape(x) for x in out)


def _wrap_tags(text: str, max_chars: int = 22, max_lines: int = 2) -> str:
    """해시태그를 최대 max_lines 줄로 줄바꿈. 넘치는 태그는 버린다(하단 띠 밖으로 안 나가게)."""
    words = (text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            if len(lines) >= max_lines:
                cur = ""
                break
            cur = w
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return r"\N".join(_ass_escape(l) for l in lines[:max_lines])


def _hook_lines(hook: str) -> tuple[str, str]:
    """후크 → (검정줄, 주황줄). 사용자가 친 Enter/\\n 으로 분리. 한 줄이면 주황 없음."""
    raw = (hook or "").replace("\\n", "\n")
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", raw) if ln.strip()]
    if not lines:
        return "", ""
    if len(lines) == 1:
        return _wrap_one(lines[0], 16), ""
    black = _wrap_one(lines[0], 16)
    orange = _wrap_one(" ".join(lines[1:]), 16)
    return black, orange


def _octagon(cx: int, cy: int, r: int) -> str:
    pts = []
    for i in range(8):
        a = math.pi / 8 + i * math.pi / 4
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    d = f"m {pts[0][0]:.0f} {pts[0][1]:.0f} " + " ".join(f"l {x:.0f} {y:.0f}" for x, y in pts[1:])
    return d + " c"


def _chrome_events() -> List[str]:
    """상단 플레이어 아이콘(회색 원 4개 + 재생 삼각형 + 점 3개)."""
    y = 58
    r = 30
    lx = [64, 150]
    rx = [W - 150, W - 64]
    circles = " ".join(_octagon(cx, y, r) for cx in lx + rx)
    ev = [f"Dialogue: 1,0:00:00.00,9:59:59.00,Chrome,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{C_CHROME}}}{circles}{{\\p0}}"]
    # 재생 삼각형(첫 버튼)
    tx = lx[0]
    tri = f"m {tx-9} {y-13} l {tx-9} {y+13} l {tx+13} {y} c"
    # 더보기 점 3개(왼쪽 둘째 버튼 자리 대신 오른쪽 첫 버튼)
    dx = rx[0]
    dots = " ".join(_octagon(dx - 12 + j * 12, y, 3) for j in range(3))
    ev.append(f"Dialogue: 1,0:00:00.00,9:59:59.00,Chrome,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{C_BLACK}}}{tri} {dots}{{\\p0}}")
    return ev


def _write_ass(ass_path: Path, spec: ShortsSpec, cfg: ShortsConfig) -> None:
    Wd, Ht = cfg.width, cfg.height
    vid_h = Ht - HEADER_H - FOOTER_H
    font = cfg.font_name
    hook_fs1 = _even(Ht * 0.040 * (cfg.hook_scale1 or 1.0))
    hook_fs2 = _even(Ht * 0.040 * (cfg.hook_scale2 or 1.0))
    cap_fs = _even(Ht * 0.034)
    tag_fs = _even(Ht * 0.029)
    hook_c1 = _hex_to_ass(cfg.hook_color1, C_BLACK)
    hook_c2 = _hex_to_ass(cfg.hook_color2, C_ORANGE)
    header = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {Wd}\nPlayResY: {Ht}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: HookB,{font},{hook_fs1},{hook_c1},&H0,{C_OUTLINE},&H0,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1\n"
        f"Style: HookO,{font},{hook_fs2},{hook_c2},&H0,{C_OUTLINE},&H0,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1\n"
        f"Style: Cap,{font},{cap_fs},{C_WHITE},&H0,&H66000000,&H0,-1,0,0,0,100,100,0,0,3,14,0,5,60,60,0,1\n"
        f"Style: Tag,{font},{tag_fs},{C_GRAY},&H0,{C_OUTLINE},&H0,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1\n"
        f"Style: Chrome,{font},20,{C_CHROME},&H0,&H0,&H0,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    cx = Wd // 2
    hook_y1 = int(HEADER_H * 0.46)
    hook_y2 = int(HEADER_H * 0.74)
    cap_y = HEADER_H + int(vid_h * 0.74)   # 자막을 위로(하단 6%→영상 74% 지점), 3줄 여유
    tag_y = HEADER_H + vid_h + FOOTER_H // 2

    events: List[str] = list(_chrome_events())
    cursor = 0.0
    for b in spec.beats:
        b0, b1 = cursor, cursor + b.duration
        cursor = b1
        st, en = _ass_time(b0), _ass_time(b1)
        black, orange = _hook_lines(b.hook)
        if black:
            events.append(f"Dialogue: 0,{st},{en},HookB,,0,0,0,,{{\\an5\\pos({cx},{hook_y1})}}{black}")
        if orange:
            events.append(f"Dialogue: 0,{st},{en},HookO,,0,0,0,,{{\\an5\\pos({cx},{hook_y2})}}{orange}")
        if b.caption.strip():
            cap = _wrap_one(b.caption.replace("\\n", " "), 22)
            events.append(f"Dialogue: 0,{st},{en},Cap,,0,0,0,,{{\\an5\\pos({cx},{cap_y})}}{cap}")

    # 해시태그 (하단 띠, 상시 노출, 최대 3줄로 줄바꿈) — 길이 숫자는 표시하지 않음
    tags = _wrap_tags(spec.hashtags, 22, 3)
    if tags.strip():
        events.append(f"Dialogue: 0,0:00:00.00,{_ass_time(spec.total)},Tag,,0,0,0,,{{\\an5\\pos({cx},{tag_y})}}{tags}")

    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def _hex_to_ass(hexcol: str, fallback: str) -> str:
    """#RRGGBB → ASS &H00BBGGRR. 실패 시 fallback(이미 &H.. 또는 #..)."""
    s = (hexcol or "").strip()
    if s.startswith("&H"):
        return s
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s)
    if not m:
        s2 = fallback
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s2 or "")
        if not m:
            return fallback if (fallback or "").startswith("&H") else "&H00111111"
    h = m.group(1)
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H00{bb}{gg}{rr}".upper()


def _escape_ass_path(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":
        s = s[0] + r"\:" + s[2:]
    return s.replace("'", r"\'")


def _finalize(joined: Path, ass_path: Path, audio: Optional[str], out_path: Path,
              total: float, cfg: ShortsConfig, speed: float,
              log_path: Path, cmd_dump: Path) -> None:
    speed = max(0.5, min(2.0, float(speed or 1.0)))
    vfilter = f"[0:v]ass='{_escape_ass_path(ass_path)}'[v]"
    if audio and Path(audio).exists():
        inputs = ["-i", str(joined), "-i", audio]
        if abs(speed - 1.0) > 0.01:
            fc = f"{vfilter};[1:a]atempo={speed:.3f}[a]"
            amap = "[a]"
        else:
            fc = vfilter
            amap = "1:a:0"
    else:
        inputs = ["-i", str(joined), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        fc = vfilter
        amap = "1:a:0"
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", fc,
        "-map", "[v]", "-map", amap, "-t", f"{total:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", cfg.preset, "-crf", str(cfg.crf), "-r", str(cfg.fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(out_path),
    ]
    dump_cmd_script(cmd, cmd_dump)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(cmd, log_path=log_path)


def build_shorts(spec: ShortsSpec, out_path: Path, work_dir: Path, cfg: ShortsConfig,
                 log: Callable[[str], None] = print) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    beats = [b for b in spec.beats if b.image and Path(b.image).exists()]
    if not beats:
        raise ValueError("no beats with valid images")
    for i, b in enumerate(beats):
        if _is_split(b, i) and not b.image2:
            b.image2 = beats[(i + 1) % len(beats)].image

    n = len(beats)
    segments: List[Path] = []
    for i, b in enumerate(beats):
        seg = work_dir / f"beat{i:02d}.mp4"
        _render_beat(b, i, seg, cfg, work_dir / f"beat{i:02d}.log", work_dir / f"beat{i:02d}.cmd")
        segments.append(seg)
        log(f"[shorts] beat done progress={i + 1}/{n + 2}")

    joined = work_dir / "joined.mp4"
    _concat(segments, joined, work_dir / "concat.log")
    log(f"[shorts] beat done progress={n + 1}/{n + 2}")

    ass_path = work_dir / "overlay.ass"
    _write_ass(ass_path, spec, cfg)
    _finalize(joined, ass_path, spec.audio, out_path, spec.total, cfg, spec.speed,
              work_dir / "final.log", work_dir / "final.cmd")
    log(f"[shorts] beat done progress={n + 2}/{n + 2}")
    log(f"[done]  {out_path}")
    return out_path

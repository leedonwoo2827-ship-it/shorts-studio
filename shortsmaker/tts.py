"""TTS — 영상공방 VoiceWright(SuperTonic3)가 있으면 그걸로, 없으면 edge-tts 폴백.

- 백엔드(영상공방)에 voicewright 가 있으면 → 그 venv 로 engine.synth 호출(고품질 F1~F5/M1~M5).
- 없으면 → **edge-tts**(무료·모델 불필요·온라인) 로 폴백. 목소리는 한국어 보이스로 매핑.
- 둘 다 없으면 TTSUnavailable → 앱은 번들 기존 음성으로 렌더.

번들 원본 음성을 건드리지 않도록, 항상 out_dir 에만 WAV 를 떨군다.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import List

from .llm_kit import bridge_dir


class TTSUnavailable(RuntimeError):
    pass


_SENT = "\x1eRESP\x1e"


# ──────────────────────────────────────────────────────────────────────────────
# 라우팅
# ──────────────────────────────────────────────────────────────────────────────
def _has_voicewright() -> bool:
    d = bridge_dir()
    return (d / "voicewright").is_dir() and _bridge_python() is not None


def engine_name() -> str:
    if _has_voicewright():
        return "voicewright"
    if _edge_available():
        return "edge-tts"
    return "none"


def available() -> bool:
    return engine_name() != "none"


def synth_lines(lines: List[str], out_dir: str, *, voice: str = "F4", speed: float = 1.1,
                timeout: float = 600.0) -> List[dict]:
    """각 줄을 음성 생성 → out_dir/line_NN.wav. [{index,file,duration}] 반환."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    if _has_voicewright():
        return _synth_voicewright(lines, out_dir, voice, speed, timeout)
    if _edge_available():
        return _synth_edge(lines, out_dir, voice, speed)
    raise TTSUnavailable("TTS 엔진 없음: 영상공방(VoiceWright)도, edge-tts(pip install edge-tts)도 없습니다.")


# ──────────────────────────────────────────────────────────────────────────────
# 1) VoiceWright (영상공방 venv 브리지)
# ──────────────────────────────────────────────────────────────────────────────
def _bridge_python():
    d = bridge_dir()
    for c in (d / "venv" / "Scripts" / "python.exe", d / "venv" / "bin" / "python",
              d / ".venv" / "Scripts" / "python.exe", d / ".venv" / "bin" / "python"):
        if c.is_file():
            return str(c)
    return None


_VW_SCRIPT = (
    "import asyncio, json, sys\n"
    "from voicewright.engine import Engine\n"
    "from voicewright.audio_io import write_wav\n"
    "data = json.loads(sys.stdin.read())\n"
    "async def main():\n"
    "    eng = await Engine.get()\n"
    "    out = []\n"
    "    for i, line in enumerate(data['lines']):\n"
    "        t = (line or '').strip() or '...'\n"
    "        try:\n"
    "            wav = await eng.synth(t, voice_code=data['voice'], speed=data['speed'])\n"
    "        except TypeError:\n"
    "            wav = await eng.synth(t, voice_code=data['voice'], total_step=8, speed=data['speed'])\n"
    "        p = data['out_dir'] + '/line_%02d.wav' % i\n"
    "        write_wav(p, wav, eng.sample_rate)\n"
    "        out.append({'index': i, 'file': p, 'duration': len(wav)/float(eng.sample_rate)})\n"
    "    return out\n"
    "res = asyncio.run(main())\n"
    "sys.stdout.write('\\x1eRESP\\x1e'); sys.stdout.write(json.dumps(res))\n"
)


def _synth_voicewright(lines, out_dir, voice, speed, timeout):
    py = _bridge_python()
    d = bridge_dir()
    payload = json.dumps({"lines": list(lines), "voice": voice,
                          "speed": float(speed), "out_dir": Path(out_dir).resolve().as_posix()})
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(d)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run([py, "-c", _VW_SCRIPT], input=payload, cwd=str(d),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TTSUnavailable(f"TTS 시간 초과({timeout:.0f}s)")
    if _SENT in (proc.stdout or ""):
        return json.loads(proc.stdout.split(_SENT, 1)[1].strip())
    raise TTSUnavailable(f"VoiceWright 실패: {(proc.stderr or proc.stdout or '').strip()[:300]}")


# ──────────────────────────────────────────────────────────────────────────────
# 2) edge-tts 폴백 (무료·온라인·모델 불필요)
# ──────────────────────────────────────────────────────────────────────────────
def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


# SuperTonic 코드(F1~F5/M1~M5) → edge-tts 한국어 보이스 매핑(가용 보이스 한정)
_EDGE_VOICE = {
    "F1": "ko-KR-SunHiNeural", "F2": "ko-KR-SunHiNeural", "F3": "ko-KR-SunHiNeural",
    "F4": "ko-KR-SunHiNeural", "F5": "ko-KR-SunHiNeural",
    "M1": "ko-KR-InJoonNeural", "M2": "ko-KR-InJoonNeural", "M3": "ko-KR-InJoonNeural",
    "M4": "ko-KR-InJoonNeural", "M5": "ko-KR-InJoonNeural",
}


def _ffmpeg() -> str:
    import shutil
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_dur(path: str) -> float:
    import shutil
    fp = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", path],
                       capture_output=True, text=True)
    try:
        return float((r.stdout or "0").strip())
    except Exception:
        return 0.0


def _synth_edge(lines, out_dir, voice, speed):
    import edge_tts
    vname = _EDGE_VOICE.get((voice or "F4").upper(), "ko-KR-SunHiNeural")
    rate = f"{int(round((float(speed) - 1.0) * 100)):+d}%"   # 1.2 → "+20%"
    out = []

    async def _run():
        for i, line in enumerate(lines):
            t = (line or "").strip() or "..."
            mp3 = str(Path(out_dir) / f"line_{i:02d}.mp3")
            wav = str(Path(out_dir) / f"line_{i:02d}.wav")
            await edge_tts.Communicate(t, vname, rate=rate).save(mp3)
            subprocess.run([_ffmpeg(), "-y", "-i", mp3, "-ar", "44100", "-ac", "1", wav],
                           capture_output=True)
            out.append({"index": i, "file": wav, "duration": _ffprobe_dur(wav)})

    try:
        asyncio.run(_run())
    except Exception as e:  # noqa: BLE001
        raise TTSUnavailable(f"edge-tts 실패(인터넷 연결 필요): {e}")
    if not out:
        raise TTSUnavailable("edge-tts 결과 없음")
    return out

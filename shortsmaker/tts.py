"""VoiceWright(SuperTonic3) TTS 브리지 — 영상공방 venv 로 음성 생성.

번들 원본 음성을 건드리지 않도록, voice_studio 의 번들 기록 함수 대신 **voicewright 엔진을
직접** 호출(engine.synth)해 임의 텍스트를 임의 위치(out_dir)에 WAV 로 떨군다.
엔진은 무거우므로 여러 줄을 한 subprocess 에서 한 번에 합성(엔진 1회 로드).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import List

from .llm_kit import bridge_dir   # 영상공방 경로(= LLM_BRIDGE_DIR / SHORTS_VODSTUDIO_DIR)

_SENT = "\x1eRESP\x1e"


class TTSUnavailable(RuntimeError):
    pass


def _bridge_python() -> str:
    d = bridge_dir()
    for c in (d / "venv" / "Scripts" / "python.exe", d / "venv" / "bin" / "python",
              d / ".venv" / "Scripts" / "python.exe", d / ".venv" / "bin" / "python"):
        if c.is_file():
            return str(c)
    raise TTSUnavailable(f"영상공방 venv 를 찾을 수 없습니다: {d}\\venv")


_SCRIPT = (
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


def synth_lines(lines: List[str], out_dir: str, *, voice: str = "F4", speed: float = 1.1,
                timeout: float = 600.0) -> List[dict]:
    """각 줄을 voice/speed 로 음성 생성 → out_dir/line_NN.wav. [{index,file,duration}] 반환."""
    py = _bridge_python()
    d = bridge_dir()
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"lines": list(lines), "voice": voice,
                          "speed": float(speed), "out_dir": Path(out_dir).resolve().as_posix()})
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(d)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run([py, "-c", _SCRIPT], input=payload, cwd=str(d),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TTSUnavailable(f"TTS 시간 초과({timeout:.0f}s)")
    if _SENT in (proc.stdout or ""):
        return json.loads(proc.stdout.split(_SENT, 1)[1].strip())
    raise TTSUnavailable(f"TTS 실패: {(proc.stderr or proc.stdout or '').strip()[:300]}")

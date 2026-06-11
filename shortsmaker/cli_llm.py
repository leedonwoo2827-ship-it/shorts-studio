"""내장 LLM 클라이언트 — 외부 백엔드(영상공방) 없이 codex/agy CLI를 직접 호출.

영상공방 백엔드가 없을 때의 폴백. codex/agy 는 사용자가 설치+로그인하는 외부 CLI 툴이며,
이 모듈은 그걸 subprocess 로 호출하는 가벼운 래퍼다(영상공방 코드를 복사하지 않음).
- codex: `codex exec - -s read-only` (stdin 프롬프트) — 의존성 없음.
- agy:   `agy --print ...` — agy 는 콘솔에 출력하므로 pywinpty(있으면)로 캡처, 없으면 subprocess.

설치 안 된 공급자는 자동으로 '없음' 처리(setup 에서 건너뛰어도 됨).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import List, Optional

_CTRL_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def _clean(s: str) -> str:
    return _CTRL_RE.sub("", s or "").strip()


def _which(name_env: str, default: str, extra: List[str]) -> Optional[str]:
    name = os.environ.get(name_env, default)
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return name if os.path.isfile(name) else None
    found = shutil.which(name)
    if found:
        return found
    for p in extra:
        p = os.path.expandvars(p)
        if p and os.path.isfile(p):
            return p
    return None


def _codex_path() -> Optional[str]:
    return _which("CODEX_BIN", "codex", [
        r"%APPDATA%\npm\codex.cmd", r"%LOCALAPPDATA%\npm\codex.cmd",
        r"%ProgramFiles%\nodejs\codex.cmd",
    ])


def _agy_path() -> Optional[str]:
    return _which("AGY_BIN", "agy", [
        r"%LOCALAPPDATA%\Antigravity\agy.exe", r"%APPDATA%\npm\agy.cmd",
    ])


# ── 설치/로그인 상태 ────────────────────────────────────────────────────────
def installed(provider: str) -> bool:
    return bool(_codex_path() if provider == "codex" else _agy_path())


def authed(provider: str) -> bool:
    if provider == "codex":
        p = _codex_path()
        if not p:
            return False
        try:
            r = subprocess.run([p, "login", "status"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=20)
            return r.returncode == 0
        except Exception:
            return False
    # agy: 설치돼 있으면 로그인된 것으로 간주(자격증명 확인은 호출 시 판별)
    return bool(_agy_path())


def status() -> dict:
    out = {}
    for prov in ("codex", "agy"):
        out[prov] = {"installed": installed(prov), "authenticated": authed(prov)}
    # 활성 공급자: 환경변수 LLM_PROVIDER, 없으면 로그인된 것 우선(codex 먼저)
    pref = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if pref not in ("codex", "agy"):
        pref = "codex" if out["codex"]["authenticated"] else ("agy" if out["agy"]["authenticated"] else "codex")
    active = out.get(pref, {})
    return {"ready": bool(active.get("installed") and active.get("authenticated")),
            "provider": pref, "label": {"codex": "OpenAI (ChatGPT)", "agy": "Gemini (Antigravity)"}.get(pref, pref),
            "providers": out, "active": {"provider": pref, **active}, "builtin": True}


def available() -> bool:
    return bool(status().get("ready"))


def login_cmd(provider: Optional[str] = None) -> List[str]:
    provider = provider or status().get("provider")
    if provider == "codex":
        return [_codex_path() or "codex", "login"]
    return [_agy_path() or "agy"]


_GUARD = ("You are a text generation assistant. Do NOT run shell commands, read/write files, "
          "or use tools. Respond with ONLY the requested content.")
_TIMEOUT = int(os.environ.get("CLI_LLM_TIMEOUT", "180"))


def _codex_complete(prompt: str) -> str:
    path = _codex_path()
    if not path:
        raise RuntimeError("codex CLI 없음")
    model = (os.environ.get("CODEX_MODEL") or "").strip()
    cmd = [path, "exec", "-", "-s", "read-only"] + (["-m", model] if model else [])
    proc = subprocess.run(cmd, input=f"{_GUARD}\n\n{prompt}", capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=_TIMEOUT + 30)
    text = _clean(proc.stdout or "")
    if not text:
        raise RuntimeError(f"codex 응답 없음: {_clean(proc.stderr or '')[:200]}")
    return text


def _pty_capture(argv: List[str], timeout: int) -> Optional[str]:
    try:
        from winpty import PtyProcess  # pywinpty
    except Exception:
        return None
    import time
    try:
        proc = PtyProcess.spawn(argv, dimensions=(60, 220))
    except Exception:
        return None
    chunks, deadline, last = [], time.monotonic() + timeout, time.monotonic()
    try:
        while True:
            if time.monotonic() > deadline:
                break
            try:
                data = proc.read(65536)
            except EOFError:
                break
            except Exception:
                break
            if data:
                chunks.append(data); last = time.monotonic()
            else:
                if not proc.isalive():
                    break
                if chunks and time.monotonic() - last > 30:
                    break
                time.sleep(0.05)
    finally:
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
    return "".join(chunks)


def _agy_complete(prompt: str) -> str:
    path = _agy_path()
    if not path:
        raise RuntimeError("agy CLI 없음")
    model = (os.environ.get("AGY_MODEL") or "").strip()
    full = f"{_GUARD}\n\n{prompt}"
    argv = [path, "--print", full, "--dangerously-skip-permissions"] + (["--model", model] if model else [])
    out = _pty_capture(argv, _TIMEOUT)         # agy는 콘솔 출력 → PTY 우선
    if out is not None and _clean(out):
        return _clean(out)
    # 폴백: 일반 subprocess (pywinpty 없을 때)
    proc = subprocess.run([path, "--print", full], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=_TIMEOUT + 30)
    text = _clean(proc.stdout or "")
    if not text:
        raise RuntimeError("agy 응답 없음 (pywinpty 설치 권장: pip install pywinpty)")
    return text


def complete(prompt: str, *, max_tokens: int = 800) -> str:
    prov = status().get("provider")
    return _agy_complete(prompt) if prov == "agy" else _codex_complete(prompt)

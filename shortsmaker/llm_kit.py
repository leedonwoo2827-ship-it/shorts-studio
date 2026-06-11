"""llm_kit — OAuth 로그인 기반 LLM 브리지 (드롭인 키트, 단일 파일·표준 라이브러리만).

여러 앱에서 매번 LLM 연결을 새로 짜지 않도록, **이미 OAuth 로그인 백엔드를 가진 프로젝트**
(영상공방: `services/llm_backend.py` + codex/agy CLI)의 venv 파이썬을 subprocess 로 호출해
결과만 받아온다. API 키 불필요, codex(ChatGPT)·agy(Antigravity/Gemini) 모두 그대로 사용.

────────────────────────────────────────────────────────────────────────
새 프로젝트에 쓰는 법:
  1) 이 파일(llm_kit.py)을 프로젝트에 복사
  2) 환경변수 LLM_BRIDGE_DIR = 백엔드 프로젝트 경로(services/llm_backend.py + venv 가 있는 곳)
  3) from llm_kit import complete, status, set_provider, logout, launch_login
     text = complete("한국어로 인사해줘")
계정 전환: set_provider("agy") → launch_login() (새 터미널에서 OAuth) → logout() 으로 계정 비우기
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

# ANSI/OSC 제어 시퀀스 제거용. codex.cmd/agy 등 CLI 래퍼가 stdout 에 터미널 타이틀(OSC)·색상(CSI)
# 을 흘리면 응답 텍스트에 섞여 들어온다(드물게 창 제목에 든 비밀값까지). 모두 걸러낸다.
_CTRL_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b[@-Z\\-_]"
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def _clean(s: str) -> str:
    return _CTRL_RE.sub("", s or "").strip()

# 백엔드(services/llm_backend.py + venv 보유) 프로젝트 경로. 환경변수 LLM_BRIDGE_DIR 로 지정.
DEFAULT_BRIDGE_DIR = os.environ.get("LLM_BRIDGE_DIR", "")
VALID_PROVIDERS = ("codex", "agy")
_SENT = "\x1eRESP\x1e"
_DEFAULT_TIMEOUT = int(os.environ.get("LLM_KIT_TIMEOUT", "300"))


class LLMUnavailable(RuntimeError):
    """브리지/백엔드/로그인 문제로 LLM 을 쓸 수 없음."""


def bridge_dir() -> Path:
    return Path(os.environ.get("LLM_BRIDGE_DIR") or DEFAULT_BRIDGE_DIR)


def _bridge_python() -> Optional[str]:
    d = bridge_dir()
    for c in (d / "venv" / "Scripts" / "python.exe", d / "venv" / "bin" / "python",
              d / ".venv" / "Scripts" / "python.exe", d / ".venv" / "bin" / "python"):
        if c.is_file():
            return str(c)
    return None


def backend_available() -> bool:
    """외부 백엔드(영상공방)가 연결 가능한지 — services/llm_backend.py + venv 둘 다 있어야 True.
    (LLM_BRIDGE_DIR 미설정/빈 값이면 False → 내장 폴백으로)."""
    raw = (os.environ.get("LLM_BRIDGE_DIR") or DEFAULT_BRIDGE_DIR or "").strip()
    if not raw:
        return False
    d = Path(raw)
    return (d / "services" / "llm_backend.py").is_file() and _bridge_python() is not None


def _child_env() -> dict:
    # 공급자는 백엔드의 data/llm_provider.json(UI 토글)이 결정 → LLM_PROVIDER 를 덮지 않는다.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(script: str, stdin_text: str = "", timeout: int = 60) -> Tuple[int, str, str]:
    py = _bridge_python()
    if not py:
        raise LLMUnavailable(
            f"브리지 venv 를 찾을 수 없습니다: {bridge_dir()}\\venv "
            "(LLM_BRIDGE_DIR 확인, 그 프로젝트에서 setup 했는지 확인)")
    try:
        proc = subprocess.run(
            [py, "-c", script], input=stdin_text, cwd=str(bridge_dir()),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_child_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise LLMUnavailable(f"LLM 응답 시간 초과({timeout}s)")
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def _eval(body: str, timeout: int = 45) -> Any:
    """백엔드 venv 에서 `result` 를 만든 뒤 JSON 으로 받아온다."""
    script = ("import json,sys\nfrom services import llm_backend as lb\n"
              + body + f"\nsys.stdout.write({_SENT!r}); "
              "sys.stdout.write(json.dumps(result, ensure_ascii=False))")
    rc, so, se = _run(script, timeout=timeout)
    if _SENT in so:
        return json.loads(so.split(_SENT, 1)[1].strip())
    raise LLMUnavailable((se or so).strip()[:300] or "브리지 응답 없음")


# ── 상태 (짧은 캐시) ──────────────────────────────────────────────────────────
_cache = {"t": 0.0, "val": None}


def status(use_cache: bool = True) -> dict:
    now = time.time()
    if use_cache and _cache["val"] is not None and now - _cache["t"] < 20:
        return _cache["val"]
    out: dict = {"ready": False, "bridge_dir": str(bridge_dir())}
    try:
        data = _eval("result = lb.status_all()", timeout=40)
        active = data.get("active") or {}
        out.update({
            "ready": bool(active.get("installed") and active.get("authenticated")),
            "provider": data.get("provider"), "label": active.get("label"),
            "email": active.get("email"), "providers": data.get("providers"),
        })
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    _cache.update(t=now, val=out)
    return out


def available() -> bool:
    return bool(status().get("ready"))


def _invalidate():
    _cache.update(t=0.0, val=None)


# ── 계정/공급자 관리 ──────────────────────────────────────────────────────────
def set_provider(name: str) -> dict:
    if name not in VALID_PROVIDERS:
        raise LLMUnavailable(f"알 수 없는 공급자: {name} ({'|'.join(VALID_PROVIDERS)})")
    res = _eval(f"result = {{'ok': lb.set_provider({name!r}), 'status': lb.status_all()}}")
    _invalidate()
    return res


def logout(provider: Optional[str] = None) -> dict:
    res = _eval(
        f"p = ({provider!r} or lb.get_provider())\n"
        "_r, a, _c = lb._modules(p)\n"
        "result = {'ok': bool(a.logout()), 'provider': p}")
    _invalidate()
    return res


def login_cmd(provider: Optional[str] = None) -> dict:
    return _eval(
        f"p = ({provider!r} or lb.get_provider())\n"
        "result = {'provider': p, 'cmd': lb.login_cmd(p)}")


# ── 모델 선택 ─────────────────────────────────────────────────────────────────
def list_models() -> list:
    try:
        r = _eval("result = list(lb.list_models())", timeout=40)
        return r if isinstance(r, list) else []
    except Exception:
        return []


def get_model() -> str:
    try:
        return _eval("result = (lb.get_model() or '')") or ""
    except Exception:
        return ""


def set_model(name: str) -> dict:
    res = _eval(f"lb.set_model({name!r})\nresult = {{'ok': True, 'model': (lb.get_model() or '')}}")
    _invalidate()
    return res


def launch_login(provider: Optional[str] = None) -> dict:
    """로그인 명령(codex login / agy)을 새 터미널에서 실행 → 브라우저 OAuth. 계정 전환에 사용."""
    info = login_cmd(provider)
    cmd = info.get("cmd") or []
    if not cmd:
        raise LLMUnavailable("로그인 명령을 가져오지 못했습니다.")
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", *cmd])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", cmd[0]])
        else:
            subprocess.Popen(cmd)
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"로그인 터미널 실행 실패: {e}")
    _invalidate()
    return {"ok": True, **info}


# ── 텍스트 생성 ───────────────────────────────────────────────────────────────
_COMPLETE = (
    "import sys\nfrom services import llm_backend as lb\n"
    "prompt = sys.stdin.read()\n"
    "client = lb.active_client()\n"
    "mdl = (lb.get_model() or '').strip() or None\n"
    "resp = client.chat(mdl, [{'role':'user','content':prompt}], max_tokens=__MAXTOK__)\n"
    f"sys.stdout.write({_SENT!r}); sys.stdout.write(getattr(resp,'text',None) or str(resp))"
)


def complete(prompt: str, *, max_tokens: int = 800, timeout: int = _DEFAULT_TIMEOUT) -> str:
    rc, so, se = _run(_COMPLETE.replace("__MAXTOK__", str(int(max_tokens))),
                      stdin_text=prompt, timeout=timeout)
    if _SENT in so:
        text = _clean(so.split(_SENT, 1)[1])
        if text:
            return text
    raise LLMUnavailable(f"LLM 호출 실패. {_clean(se or so)[:300]}")
